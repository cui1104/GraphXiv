# Phase 1: Foundation - Context

**Gathered:** 2026-04-13
**Status:** Ready for planning

<domain>
## Phase Boundary

Stand up all infrastructure services locally via Docker Compose and lock in the full database schema before any data flows through it. No ingestion, no parsing, no API — only the skeleton that every later phase builds on.

Delivers: docker-compose.yml, Alembic migration (all tables + indexes), Celery app config with fast/slow queues and stub tasks, Redis wired as broker + KV store.

</domain>

<decisions>
## Implementation Decisions

### Project directory structure
- Single flat Python package named `app/` at project root
- Layout:
  ```
  project_root/
  ├── docker-compose.yml
  ├── .env                   ← gitignored; VM gets its own copy
  ├── .env.example           ← committed; placeholder values
  ├── pyproject.toml
  ├── alembic.ini
  ├── alembic/
  │   └── versions/
  ├── app/
  │   ├── celery_app.py      ← Celery app instance + queue/route config
  │   ├── config.py          ← reads .env via pydantic-settings or python-dotenv
  │   ├── db.py              ← SQLAlchemy engine + session factory
  │   ├── models.py          ← ORM models (all tables)
  │   ├── tasks/
  │   │   ├── __init__.py
  │   │   ├── ingest.py      ← stub tasks for Phase 2
  │   │   ├── parse.py       ← stub tasks for Phase 3
  │   │   └── normalize.py   ← stub tasks for Phase 4
  │   ├── api/               ← empty __init__.py; Phase 5 fills this
  │   └── crawler/           ← empty __init__.py; Phase 2 fills this
  └── tests/
  ```
- Paper assets (tar.gz, PDFs) stored under `./data/` as a bind mount into containers

### Environment config
- `.env` file at project root with all secrets and config (DATABASE_URL, REDIS_URL, data paths, etc.)
- `.env.example` committed to git with placeholder values for all required keys
- `docker-compose.yml` reads from `.env` via `env_file: .env`
- Same file structure on local dev and VM; values differ (VM gets higher resource limits, real paths)
- No docker-compose.override.yml approach — single compose file for simplicity

### Docker Compose services
- Services: PostgreSQL 16, Redis 7, Celery worker (fast + slow queues), Flower, GROBID 0.8
- All services always-on when `docker compose up` runs
- GROBID: always-on with health check polling `/api/isalive`; `mem_limit: 8g` (VM deployment; largest practical allocation)
- NVIDIA GPU available → Celery worker service uses `runtime: nvidia` + `NVIDIA_VISIBLE_DEVICES=all`; MinerU runs GPU-accelerated on the slow queue
- `./data/` bind mount exposed into worker container for paper assets
- PostgreSQL data persisted via Docker named volume (`pgdata`)
- Redis data persisted via Docker named volume (`redisdata`)

### papers table — structured columns vs JSONB split
- **Structured columns** (indexed, directly filterable):
  - `canonical_id UUID PRIMARY KEY`
  - `arxiv_id TEXT UNIQUE`
  - `pmc_id TEXT UNIQUE`
  - `doi TEXT`
  - `title TEXT` (also indexed via tsvector for FTS)
  - `abstract TEXT` (also indexed via tsvector for FTS)
  - `year INTEGER`
  - `venue TEXT`
  - `parse_source TEXT` — values: `latex`, `jats`, `pdf_mineru`, `pdf_grobid`
  - `parse_quality TEXT` — values: `ok`, `degraded`, `scanned_skip`
  - `token_count INTEGER`
  - `tldr TEXT`
  - `embeddings vector(768)` — pgvector column (Phase 5 populates; NULL until then)
  - `created_at TIMESTAMPTZ`
  - `updated_at TIMESTAMPTZ`
- **JSONB `content` blob** (not individually indexed):
  - `sections`, `citations`, `ref_entries`, `back_matter`, `authors`

### Database tables — full set in Phase 1 migration
All five tables created in the initial Alembic migration (schema fully locked before any data):

1. **`papers`** — as specified above (canonical record per unique paper)
2. **`paper_sources`** — `(id, canonical_id FK, source_type TEXT, asset_path TEXT, parse_status TEXT, created_at)`; tracks each raw source file and its parse status
3. **`id_map`** — `(arxiv_id, pmc_id, doi, canonical_id FK)`; cross-source ID linking
4. **`crawl_state`** — `(id, source TEXT, resumption_token TEXT, last_harvested_at TIMESTAMPTZ, record_count INTEGER)`; resumable crawler state
5. **`paper_citations`** — `(id, source_paper_id UUID FK, target_paper_id UUID FK NULLABLE, target_arxiv_id TEXT, target_doi TEXT, context_text TEXT)`; citation graph edges (INFRA-06 included in Phase 1)

### Indexes
- `papers`: UNIQUE on `arxiv_id`, UNIQUE on `pmc_id`; GIN on `tsvector(title || ' ' || abstract)` for FTS; index on `year`
- `paper_citations`: index on `source_paper_id`, index on `target_paper_id`

### pgvector
- `CREATE EXTENSION IF NOT EXISTS vector` in Alembic migration
- `embeddings vector(768)` column on `papers` (NULL until Phase 5 populates it)

### Celery configuration
- `fast` queue: LaTeX/XML tasks, `time_limit=60`
- `slow` / `gpu` queue: PDF ML tasks (MinerU), `time_limit=300`
- `max_retries=3` on all tasks
- `task_routes` maps stub task names to correct queue
- Workers for both queues started in a single container with concurrency config in Compose

### Claude's Discretion
- Exact SQLAlchemy ORM model style (declarative vs dataclass)
- Health check intervals and retry counts in docker-compose.yml
- Celery concurrency setting per queue (can tune after Phase 2)
- Python dependency management tool (poetry vs pip + pyproject.toml)

</decisions>

<specifics>
## Specific Ideas

- VM deployment is the target for running the full 10k paper corpus; local Docker Compose is for development
- GROBID gets 8GB RAM because VM has plenty; don't constrain it
- NVIDIA GPU on VM → `runtime: nvidia` in Docker Compose for the worker service
- `.env.example` must include all keys so VM setup is just "copy and fill in values"
- `paper_citations` and pgvector are included in Phase 1 schema (INFRA-06) to avoid mid-pipeline migrations

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

No external specs committed to this repo — requirements are fully captured in decisions above.

### Project requirements
- `.planning/REQUIREMENTS.md` §Infrastructure — INFRA-01 through INFRA-06 (all in Phase 1)
- `.planning/ROADMAP.md` §Phase 1 — success criteria and plan list

</canonical_refs>

<deferred>
## Deferred Ideas

- pgvector embeddings population — Phase 5 (REST API) populates the `embeddings` column; column exists in schema from Phase 1 but stays NULL until then
- Celery beat / scheduled tasks — not needed in Phase 1; add if crawl scheduling is needed in Phase 2
- Horizontal scaling / multiple workers — single worker container is sufficient for Phase 1 verification

</deferred>

---

*Phase: 01-foundation*
*Context gathered: 2026-04-13*
