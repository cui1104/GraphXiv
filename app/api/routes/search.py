"""Route handler for the hybrid search endpoint.

Supports three search modes:
- bm25: PostgreSQL full-text search (ts_rank + plainto_tsquery)
- vector: pgvector cosine similarity search on embeddings
- hybrid: BM25 + vector combined with 50/50 weighting

Falls back to BM25-only when search_mode is hybrid/vector but no papers
have embeddings in the database.

Uses async def handler with cache-aside pattern (D-16/D-17):
- Cache key: search:{md5(q:limit:search_mode)}, TTL 300s.
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.cache import SEARCH_TTL, get_cached, search_cache_key, set_cache
from app.api.deps import get_db, get_redis
from app.api.schemas import SearchResponse, SearchResultItem
from redis.asyncio import Redis

logger = logging.getLogger(__name__)

router = APIRouter()

SEARCH_TTL = SEARCH_TTL  # re-export for grep-ability in tests


# ---------------------------------------------------------------------------
# Search helper functions
# ---------------------------------------------------------------------------

def _bm25_search(db: Session, q: str, limit: int) -> list:
    """Full-text BM25 search using PostgreSQL ts_rank + plainto_tsquery."""
    sql = text("""
        SELECT canonical_id, title, abstract, arxiv_id, pmc_id, doi,
               tldr, token_count, year, venue, parse_source,
               content->'authors' AS authors_json,
               ts_rank(
                   to_tsvector('english', coalesce(title,'') || ' ' || coalesce(abstract,'')),
                   plainto_tsquery('english', :q)
               ) AS score
        FROM papers
        WHERE to_tsvector('english', coalesce(title,'') || ' ' || coalesce(abstract,''))
              @@ plainto_tsquery('english', :q)
        ORDER BY score DESC
        LIMIT :limit
    """)
    return db.execute(sql, {"q": q, "limit": limit}).fetchall()


def _vector_search(db: Session, query_vec: list, limit: int) -> list:
    """Vector similarity search using pgvector cosine distance."""
    vec_str = "[" + ",".join(str(v) for v in query_vec) + "]"
    sql = text("""
        SELECT canonical_id, title, abstract, arxiv_id, pmc_id, doi,
               tldr, token_count, year, venue, parse_source,
               content->'authors' AS authors_json,
               1 - (embeddings <=> CAST(:vec AS vector)) AS score
        FROM papers WHERE embeddings IS NOT NULL
        ORDER BY score DESC LIMIT :limit
    """)
    return db.execute(sql, {"vec": vec_str, "limit": limit}).fetchall()


def _hybrid_search(db: Session, q: str, query_vec: list, limit: int) -> list:
    """Hybrid BM25 + vector search with 50/50 score weighting."""
    vec_str = "[" + ",".join(str(v) for v in query_vec) + "]"
    sql = text("""
        WITH bm25 AS (
            SELECT canonical_id,
                   ts_rank(to_tsvector('english', coalesce(title,'') || ' ' || coalesce(abstract,'')),
                           plainto_tsquery('english', :q)) AS bm25_score
            FROM papers
            WHERE to_tsvector('english', coalesce(title,'') || ' ' || coalesce(abstract,''))
                  @@ plainto_tsquery('english', :q)
        ),
        vec AS (
            SELECT canonical_id, 1 - (embeddings <=> CAST(:vec AS vector)) AS vec_score
            FROM papers WHERE embeddings IS NOT NULL
        )
        SELECT p.canonical_id, p.title, p.abstract, p.arxiv_id, p.pmc_id, p.doi,
               p.tldr, p.token_count, p.year, p.venue, p.parse_source,
               p.content->'authors' AS authors_json,
               (COALESCE(b.bm25_score, 0) * 0.5 + COALESCE(v.vec_score, 0) * 0.5) AS score
        FROM papers p
        LEFT JOIN bm25 b ON b.canonical_id = p.canonical_id
        LEFT JOIN vec v ON v.canonical_id = p.canonical_id
        WHERE b.canonical_id IS NOT NULL OR v.canonical_id IS NOT NULL
        ORDER BY score DESC LIMIT :limit
    """)
    return db.execute(sql, {"q": q, "vec": vec_str, "limit": limit}).fetchall()


def _check_has_embeddings(db: Session) -> bool:
    """Check if any papers have embeddings stored."""
    sql = text("SELECT 1 FROM papers WHERE embeddings IS NOT NULL LIMIT 1")
    row = db.execute(sql).fetchone()
    return row is not None


def _get_or_load_embedding_model(request: Request):
    """Lazy-load the sentence-transformers embedding model on first use."""
    from sentence_transformers import SentenceTransformer
    if request.app.state.embedding_model is None:
        settings = request.app.state.settings
        request.app.state.embedding_model = SentenceTransformer(settings.embedding_model)
    return request.app.state.embedding_model


def _rows_to_search_results(rows: list) -> list[SearchResultItem]:
    """Convert DB result rows to SearchResultItem list."""
    results = []
    for row in rows:
        authors_json = row.authors_json
        if authors_json is None:
            authors = []
        elif isinstance(authors_json, str):
            authors = json.loads(authors_json)
        else:
            # Already parsed (some DB drivers return Python objects for JSONB)
            authors = authors_json if isinstance(authors_json, list) else json.loads(str(authors_json))

        # Derive src_url from identifiers
        if row.arxiv_id:
            src_url = f"https://arxiv.org/abs/{row.arxiv_id}"
        elif row.pmc_id:
            src_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{row.pmc_id}/"
        else:
            src_url = ""

        results.append(SearchResultItem(
            paper_id=str(row.canonical_id),
            arxiv_id=row.arxiv_id,
            pmc_id=row.pmc_id,
            title=row.title,
            abstract=row.abstract,
            tldr=row.tldr,
            authors=authors,
            year=row.year,
            src_url=src_url,
            token_count=row.token_count or 0,
        ))
    return results


# ---------------------------------------------------------------------------
# Search endpoint
# ---------------------------------------------------------------------------

@router.get("/arxiv/search", response_model=SearchResponse)
async def arxiv_search(
    request: Request,
    q: str,
    limit: int = 10,
    search_mode: str = "hybrid",
    db: Session = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    """API-05: Hybrid search endpoint supporting bm25, vector, and hybrid modes."""
    cache_key = search_cache_key(q, limit, search_mode)
    cached = await get_cached(redis, cache_key)
    if cached is not None:
        return cached

    def _run_search():
        rows: list = []
        if search_mode == "bm25":
            rows = _bm25_search(db, q, limit)
        elif search_mode == "vector":
            if not _check_has_embeddings(db):
                logger.warning("No embeddings found, falling back to BM25 search")
                rows = _bm25_search(db, q, limit)
            else:
                model = _get_or_load_embedding_model(request)
                query_vec = model.encode(q).tolist()
                rows = _vector_search(db, query_vec, limit)
        else:
            # Default: hybrid
            if not _check_has_embeddings(db):
                logger.warning("No embeddings found, falling back to BM25 search")
                rows = _bm25_search(db, q, limit)
            else:
                model = _get_or_load_embedding_model(request)
                query_vec = model.encode(q).tolist()
                rows = _hybrid_search(db, q, query_vec, limit)
        return rows

    rows = await asyncio.to_thread(_run_search)
    results = _rows_to_search_results(rows)
    response_dict = {"total": len(results), "results": [r.model_dump() for r in results]}
    await set_cache(redis, cache_key, response_dict, SEARCH_TTL)
    return SearchResponse(total=len(results), results=results)
