"""Phase 1 infrastructure verification tests.

INFRA-01: Docker Compose services (manual — docker compose ps)
INFRA-02: PostgreSQL schema tables + indexes
INFRA-03: Redis as broker + KV store
INFRA-04: Celery fast/slow queues
INFRA-05: Alembic migration applies cleanly
INFRA-06: paper_citations table + pgvector extension
"""
import pytest
from sqlalchemy import text, inspect


class TestSchema:
    """INFRA-02: All 5 tables exist with correct columns and indexes."""

    def test_tables_exist(self, db_engine):
        """papers, paper_sources, id_map, crawl_state, paper_citations tables must exist."""
        inspector = inspect(db_engine)
        tables = inspector.get_table_names()
        for expected in ["papers", "paper_sources", "id_map", "crawl_state", "paper_citations"]:
            assert expected in tables, f"Table '{expected}' not found. Existing tables: {tables}"

    def test_papers_columns(self, db_engine):
        """papers table must have all structured columns from CONTEXT.md."""
        inspector = inspect(db_engine)
        columns = {c["name"] for c in inspector.get_columns("papers")}
        required = {
            "canonical_id", "arxiv_id", "pmc_id", "doi", "title", "abstract",
            "year", "venue", "parse_source", "parse_quality", "token_count",
            "tldr", "embeddings", "content", "created_at", "updated_at",
        }
        missing = required - columns
        assert not missing, f"papers table missing columns: {missing}"

    def test_papers_unique_constraints(self, db_engine):
        """arxiv_id and pmc_id must have UNIQUE constraints."""
        inspector = inspect(db_engine)
        unique_cols = set()
        for idx in inspector.get_indexes("papers"):
            if idx.get("unique"):
                for col in idx["column_names"]:
                    unique_cols.add(col)
        # Also check unique constraints
        for uc in inspector.get_unique_constraints("papers"):
            for col in uc["column_names"]:
                unique_cols.add(col)
        assert "arxiv_id" in unique_cols, "arxiv_id must be UNIQUE"
        assert "pmc_id" in unique_cols, "pmc_id must be UNIQUE"

    def test_papers_fts_index(self, db_engine):
        """GIN index on tsvector(title, abstract) must exist."""
        with db_engine.connect() as conn:
            result = conn.execute(text(
                "SELECT indexname FROM pg_indexes WHERE tablename = 'papers' AND indexdef LIKE '%gin%'"
            ))
            gin_indexes = [row[0] for row in result]
            assert len(gin_indexes) > 0, "No GIN index found on papers table"

    def test_paper_sources_table(self, db_engine):
        """paper_sources must have id, canonical_id, source_type, asset_path, parse_status, created_at."""
        inspector = inspect(db_engine)
        columns = {c["name"] for c in inspector.get_columns("paper_sources")}
        required = {"id", "canonical_id", "source_type", "asset_path", "parse_status", "created_at"}
        missing = required - columns
        assert not missing, f"paper_sources missing columns: {missing}"

    def test_id_map_table(self, db_engine):
        """id_map must have arxiv_id, pmc_id, doi, canonical_id."""
        inspector = inspect(db_engine)
        columns = {c["name"] for c in inspector.get_columns("id_map")}
        required = {"arxiv_id", "pmc_id", "doi", "canonical_id"}
        missing = required - columns
        assert not missing, f"id_map missing columns: {missing}"

    def test_crawl_state_table(self, db_engine):
        """crawl_state must have id, source, resumption_token, last_harvested_at, record_count."""
        inspector = inspect(db_engine)
        columns = {c["name"] for c in inspector.get_columns("crawl_state")}
        required = {"id", "source", "resumption_token", "last_harvested_at", "record_count"}
        missing = required - columns
        assert not missing, f"crawl_state missing columns: {missing}"


class TestPgvector:
    """INFRA-06: pgvector extension enabled and paper_citations table exists."""

    def test_pgvector_extension(self, db_engine):
        """pgvector extension must be installed."""
        with db_engine.connect() as conn:
            result = conn.execute(text("SELECT extname FROM pg_extension WHERE extname = 'vector'"))
            extensions = [row[0] for row in result]
            assert "vector" in extensions, "pgvector extension not installed"

    def test_embeddings_column_type(self, db_engine):
        """papers.embeddings must be vector(768) type."""
        with db_engine.connect() as conn:
            result = conn.execute(text(
                "SELECT data_type, udt_name FROM information_schema.columns "
                "WHERE table_name = 'papers' AND column_name = 'embeddings'"
            ))
            row = result.fetchone()
            assert row is not None, "embeddings column not found on papers table"
            assert "vector" in row[1].lower(), f"embeddings column type is '{row[1]}', expected vector"

    def test_paper_citations_table(self, db_engine):
        """paper_citations must have correct columns."""
        inspector = inspect(db_engine)
        columns = {c["name"] for c in inspector.get_columns("paper_citations")}
        required = {"id", "source_paper_id", "target_paper_id", "target_arxiv_id", "target_doi", "context_text"}
        missing = required - columns
        assert not missing, f"paper_citations missing columns: {missing}"

    def test_paper_citations_indexes(self, db_engine):
        """paper_citations must have indexes on source_paper_id and target_paper_id."""
        inspector = inspect(db_engine)
        indexed_cols = set()
        for idx in inspector.get_indexes("paper_citations"):
            for col in idx["column_names"]:
                indexed_cols.add(col)
        assert "source_paper_id" in indexed_cols, "source_paper_id not indexed"
        assert "target_paper_id" in indexed_cols, "target_paper_id not indexed"


class TestAlembic:
    """INFRA-05: Alembic migration applies cleanly."""

    def test_alembic_current(self, db_engine):
        """alembic_version table must exist after migration."""
        inspector = inspect(db_engine)
        tables = inspector.get_table_names()
        assert "alembic_version" in tables, "alembic_version table not found — migration not applied"


class TestRedis:
    """INFRA-03: Redis is reachable and works as KV store."""

    def test_redis_ping(self, redis_client):
        """Redis must respond to PING."""
        assert redis_client.ping() is True

    def test_redis_write_read(self, redis_client):
        """Redis must support write and read with TTL."""
        redis_client.setex("test:infra:key", 60, "test_value")
        value = redis_client.get("test:infra:key")
        assert value == b"test_value"
        redis_client.delete("test:infra:key")


class TestCeleryQueues:
    """INFRA-04: Celery fast/slow queues are configured and tasks route correctly."""

    def test_celery_app_importable(self):
        """Celery app must be importable from app.celery_app."""
        from app.celery_app import celery_app
        assert celery_app is not None
        assert celery_app.main == "app"

    def test_celery_queues_configured(self):
        """fast and slow queues must be defined."""
        from app.celery_app import celery_app
        queue_names = {q.name for q in celery_app.conf.task_queues}
        assert "fast" in queue_names, f"'fast' queue not found. Queues: {queue_names}"
        assert "slow" in queue_names, f"'slow' queue not found. Queues: {queue_names}"

    def test_task_routes_exist(self):
        """task_routes must map task paths to queues."""
        from app.celery_app import celery_app
        routes = celery_app.conf.task_routes
        assert routes is not None, "task_routes not configured"
        assert len(routes) > 0, "task_routes is empty"

    def test_fast_task_time_limit(self):
        """Ingest task must have time_limit=300 (real harvest replaced stub in Phase 2)."""
        from app.tasks.ingest import ingest_paper
        assert ingest_paper.time_limit == 300, f"ingest_paper time_limit is {ingest_paper.time_limit}, expected 300"

    def test_slow_task_time_limit(self):
        """PDF parse stub task must have time_limit=300."""
        from app.tasks.parse import parse_pdf_mineru
        assert parse_pdf_mineru.time_limit == 300, f"parse_pdf_mineru time_limit is {parse_pdf_mineru.time_limit}, expected 300"
