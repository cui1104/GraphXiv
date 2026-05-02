# Phase 5: REST API - Research

**Researched:** 2026-04-15
**Domain:** FastAPI, SQLAlchemy async, Redis cache-aside, pgvector hybrid search, Pydantic v2
**Confidence:** HIGH (all findings verified against existing codebase + official library patterns)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** All 10 endpoints ship in Phase 5:
  - 7 core: `GET /arxiv/{id}/head`, `/brief`, `/sections`, `/full`, `/search`, `/pmc/{id}/head`, `/pmc/{id}/full`
  - 3 citation graph: `GET /arxiv/{id}/references`, `/cited_by`, `/related`
- **D-02:** Citation graph endpoints are included because `paper_citations` table is already populated and Phase 6 (SDK fork) needs them immediately
- **D-03:** `/related` uses co-citation query (papers frequently cited alongside this one via GROUP BY on `paper_citations`)
- **D-04:** Hybrid search — BM25 (PostgreSQL `tsvector` via `idx_papers_fts` GIN index) + pgvector semantic similarity
- **D-05:** `search_mode` query param: `bm25` | `vector` | `hybrid` (default: `hybrid`)
- **D-06:** Embedding model: `sentence-transformers/all-MiniLM-L6-v2` (384-dim, CPU-safe)
- **D-07:** Model is configurable via `EMBEDDING_MODEL` env var — when a GPU VM is available, swap model + re-embed all papers via a migration script + Alembic migration for new vector dim
- **D-08:** Embeddings are computed at normalize time (inside `normalize_paper` Celery task) and stored in `papers.embeddings` (vector(384))
- **D-09:** BM25 score: `ts_rank(to_tsvector('english', title || ' ' || abstract), plainto_tsquery('english', query))`; vector score: `1 - (embeddings <=> query_vector)`; hybrid score: `0.5 * bm25 + 0.5 * vector`
- **D-10:** New `api` service in `docker-compose.yml` — separate container from Celery worker
- **D-11:** Command: `uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --reload` (dev) / without `--reload` (prod)
- **D-12:** Host port mapping: `8000:8000`
- **D-13:** No authentication, no rate limiting — open API for local research use
- **D-14:** Cache-aside pattern on all endpoints: check Redis → hit: return cached JSON → miss: query DB → serialize → cache → return
- **D-15:** Cache key format: `papers:{canonical_id}:{view}` where view ∈ {head, brief, sections, full, references, cited_by, related}
- **D-16:** Search results cached at key `search:{md5(q+limit+search_mode)}`, TTL 300s
- **D-17:** Paper view TTL: 3600s; search TTL: 300s
- **D-18:** Cache invalidation: on `normalize_paper` upsert, delete all `papers:{canonical_id}:*` keys
- **D-19:** 404 returns `{"error": "not_found", "message": "Paper {id} not found"}` — structured body, not bare HTTP error
- **D-20:** ID resolution: any input ID (arxiv_id with/without version suffix, pmcid, doi) resolved to `canonical_id` via `id_map` table before querying `papers`
- **D-21:** Version suffix is stripped from arXiv IDs on input (e.g., `2401.00001v2` → `2401.00001`)
- **D-22:** Pydantic v2 models for all response types — field names exactly match FEATURES.md schema (HeadResponse, BriefResponse, SectionsResponse, FullResponse, SearchResponse, PmcHeadResponse, PmcFullResponse, ReferencesResponse, CitedByResponse, RelatedResponse)
- **D-23:** SQLAlchemy 2.x async queries (AsyncSession) for non-blocking DB access under concurrent requests

### Claude's Discretion

- Exact Pydantic model inheritance structure (whether Head/Brief share a base model)
- Uvicorn worker count and concurrency settings
- Order of middleware (CORS, logging, etc.)
- Whether to use FastAPI's dependency injection for DB sessions and Redis client

### Deferred Ideas (OUT OF SCOPE)

- Re-embedding all papers with a larger model (e.g., `BAAI/bge-large-en-v1.5`) — when GPU VM is available; requires re-embed Celery task + Alembic migration
- Per-paragraph cite_spans / ref_spans in sections (v2 feature per REQUIREMENTS.md EXT-01)
- Table HTML rendering in ref_entries (v2, EXT-03)
- Rate limiting / API key auth — not needed for local research use
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| API-01 | `GET /arxiv/{id}/head` returns metadata-only response | HeadResponse Pydantic model; id_map resolution pattern documented |
| API-02 | `GET /arxiv/{id}/brief` returns same shape as head | BriefResponse = same model as HeadResponse; confirmed by FEATURES.md |
| API-03 | `GET /arxiv/{id}/sections` returns sections-only response (paper_id, title, sections[], token_count) | SectionsResponse model; sections read from `papers.content` JSONB |
| API-04 | `GET /arxiv/{id}/full` returns complete paper object including sections, citations, ref_entries, back_matter | FullResponse model; full content JSONB pass-through |
| API-05 | `GET /arxiv/search?q=&limit=` returns SearchResponse with BM25/vector/hybrid search | GIN index `idx_papers_fts` exists; pgvector `<=>` operator; hybrid scoring formula documented |
| API-06 | `GET /pmc/{id}/head` returns metadata-only response | Same HeadResponse shape; pmc_id lookup path via id_map |
| API-07 | `GET /pmc/{id}/full` returns complete paper object for PMC papers | Same FullResponse shape; pmc_id lookup path |
| API-08 | All endpoints return HTTP 404 with structured error body when ID not found | 404 body format: `{"error": "not_found", "message": "Paper {id} not found"}` |
| API-09 | Redis caching active; keys follow `papers:{canonical_id}:{view}` pattern with TTLs | Redis 5.2.1 already in pyproject.toml; cache-aside pattern documented |
</phase_requirements>

---

## Summary

Phase 5 builds a FastAPI application (`app/api/main.py`) that serves 10 REST endpoints across three routers: arxiv paper routes, PMC paper routes, and search. The API reads pre-computed data from the `papers` table (structured columns + JSONB `content` field) and the `paper_citations` edge table. Redis cache-aside reduces DB load for repeated lookups.

The two highest-risk items are: (1) **schema mismatch** — the live DB has `embeddings vector(768)` but CONTEXT.md specifies 384-dim (`all-MiniLM-L6-v2`); planning must include an Alembic migration to correct this AND add embedding computation to `normalize_paper` (D-08 says embeddings are already in normalize task — the actual code does not write them yet); (2) **async session setup** — the existing `app/db.py` is synchronous only (sync `SessionLocal`); Phase 5 needs to either add `AsyncSession` via `create_async_engine` or use the sync session in a thread pool via `run_in_executor`. The simplest correct approach for this codebase is sync-over-thread-pool using `asyncio.to_thread` or FastAPI's built-in `run_in_executor` path, which avoids adding `asyncpg` as a new dependency.

**Primary recommendation:** Structure the API as three files — `app/api/main.py` (app factory, middleware, startup), `app/api/routes/` (arxiv.py, pmc.py, search.py), `app/api/schemas.py` (all Pydantic v2 response models). Use sync SQLAlchemy with `asyncio.to_thread` for DB calls, and the existing `redis` client (already installed) for cache-aside. Add `sentence-transformers` to pyproject.toml for query embedding in vector/hybrid search.

---

## Critical Schema Discrepancy — Must Resolve in Plan

**Issue:** `papers.embeddings` column is `vector(768)` in all existing migrations and ORM model. CONTEXT.md D-06/D-08 specifies 384-dim (`all-MiniLM-L6-v2`). These are incompatible.

**Required actions before vector search works:**
1. New Alembic migration: `ALTER TABLE papers ALTER COLUMN embeddings TYPE vector(384) USING NULL` — drops and re-creates the column (no data exists yet since normalize does not write embeddings)
2. Update `app/models.py`: `Vector(768)` → `Vector(384)`
3. Add embedding computation to `normalize_paper` task (currently the task writes `content` JSONB but does NOT set `paper.embeddings`)

**Planning note:** This schema fix is a prerequisite for API-05 vector search. Must be its own task (Wave 0 or Wave 1).

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| fastapi | already installed (via `pydantic-settings`) | HTTP framework, routing, OpenAPI | Project standard; D-11 specifies uvicorn/fastapi |
| uvicorn | install needed | ASGI server | D-11 explicit |
| pydantic v2 | already installed (via pydantic-settings 2.13.1) | Response models, validation | D-22 explicit; pydantic-settings 2.x pulls pydantic v2 |
| redis | 5.2.1 (already in pyproject.toml) | Cache-aside client | D-14 through D-18; already present |
| sqlalchemy | 2.0.49 (already installed) | DB queries (sync) | Project standard |
| sentence-transformers | latest stable (~2.7.0) | Query embedding for vector/hybrid search | D-06: all-MiniLM-L6-v2 |
| psycopg2-binary | 2.9.11 (already installed) | PostgreSQL driver | Project standard |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| hashlib | stdlib | MD5 key for search cache (D-16) | `search:{md5(q+limit+search_mode)}` |
| asyncio | stdlib | `asyncio.to_thread()` to run sync DB calls from async handlers | Avoids adding asyncpg dependency |

### Dependencies to ADD to pyproject.toml
```bash
pip install fastapi uvicorn[standard] sentence-transformers
```

Add to `[project.dependencies]`:
```
"fastapi>=0.115.0",
"uvicorn[standard]>=0.30.0",
"sentence-transformers>=2.7.0",
```

**Version verification note:** fastapi latest is 0.115.x (2025). uvicorn[standard] includes websockets + httptools for production. sentence-transformers 2.7+ includes `all-MiniLM-L6-v2` natively.

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| sync + asyncio.to_thread | asyncpg + create_async_engine | asyncpg adds a new driver dependency; sync-over-thread-pool avoids it and works fine for 10k paper corpus with small concurrency |
| redis-py sync | aioredis | redis 5.2.1 already installed; redis-py 5.x has async support built-in via `redis.asyncio.Redis` — use that sub-module to avoid a new package |

**Better path for Redis:** Use `redis.asyncio.Redis` (built into redis-py 5.x, already installed) instead of sync Redis in async routes — no new package needed.

---

## Architecture Patterns

### Recommended Project Structure
```
app/
├── api/
│   ├── __init__.py          # exists (empty)
│   ├── main.py              # FastAPI app factory, lifespan, middleware
│   ├── schemas.py           # All Pydantic v2 response models
│   ├── deps.py              # FastAPI dependency providers (DB session, Redis)
│   └── routes/
│       ├── __init__.py
│       ├── arxiv.py         # /arxiv/* routes (head, brief, sections, full, references, cited_by, related)
│       ├── pmc.py           # /pmc/* routes (head, full)
│       └── search.py        # /arxiv/search route
```

### Pattern 1: FastAPI App Factory with Lifespan

```python
# app/api/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
import redis.asyncio as aioredis
from app.config import get_settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    yield
    await app.state.redis.aclose()

app = FastAPI(title="Research Knowledge Graph API", lifespan=lifespan)
```

**When to use:** Lifespan events replace deprecated `on_startup`/`on_shutdown` in FastAPI 0.93+. Ensures Redis connection is properly cleaned up.

### Pattern 2: Dependency Injection for DB Session and Redis

```python
# app/api/deps.py
from typing import Generator, AsyncGenerator
from fastapi import Request
from sqlalchemy.orm import Session
from app.db import SessionLocal
import redis.asyncio as aioredis

def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

async def get_redis(request: Request) -> aioredis.Redis:
    return request.app.state.redis
```

**When to use:** FastAPI `Depends()` — every route handler receives a fresh DB session and the shared Redis client. Ensures proper session lifecycle without try/finally in every handler.

### Pattern 3: Cache-Aside with Redis (D-14 through D-18)

```python
import json, hashlib
from redis.asyncio import Redis

PAPER_TTL = 3600
SEARCH_TTL = 300

async def get_cached_or_fetch(redis: Redis, key: str, ttl: int, fetch_fn):
    cached = await redis.get(key)
    if cached:
        return json.loads(cached)
    result = fetch_fn()          # sync DB call
    if result is not None:
        await redis.set(key, json.dumps(result), ex=ttl)
    return result

# Key formats (D-15, D-16):
# papers:{canonical_id}:{view}   TTL 3600s
# search:{md5(q+limit+search_mode)}  TTL 300s
```

**Invalidation (D-18):** In `normalize_paper` task, after upsert:
```python
# delete all views for this canonical_id
pattern = f"papers:{paper.canonical_id}:*"
# redis SCAN + DEL (do not use KEYS in production):
async for key in redis.scan_iter(match=pattern):
    await redis.delete(key)
```
Note: The invalidation in `normalize_paper` is a Celery task (sync context). Use sync `redis.Redis` client there, not `redis.asyncio.Redis`.

### Pattern 4: ID Resolution (D-20, D-21)

```python
import re
from sqlalchemy.orm import Session
from app.models import IdMap, Paper

ARXIV_VERSION_RE = re.compile(r"v\d+$", re.IGNORECASE)

def strip_arxiv_version(arxiv_id: str) -> str:
    return ARXIV_VERSION_RE.sub("", arxiv_id)

def resolve_arxiv_id(db: Session, arxiv_id: str) -> Paper | None:
    clean_id = strip_arxiv_version(arxiv_id)
    # First try direct column
    paper = db.query(Paper).filter(Paper.arxiv_id == clean_id).first()
    if paper:
        return paper
    # Then via id_map (for cross-linked papers)
    row = db.query(IdMap).filter(IdMap.arxiv_id == clean_id).first()
    if row:
        return db.query(Paper).filter(Paper.canonical_id == row.canonical_id).first()
    return None
```

### Pattern 5: Hybrid Search Query (D-04, D-09)

The GIN index `idx_papers_fts` already exists on:
```sql
to_tsvector('english', coalesce(title, '') || ' ' || coalesce(abstract, ''))
```

BM25-only query:
```python
from sqlalchemy import text

def bm25_search(db: Session, q: str, limit: int) -> list[dict]:
    sql = text("""
        SELECT canonical_id, title, abstract, arxiv_id, pmc_id, doi,
               tldr, token_count, year, src_url,
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
```

Vector-only query (requires embeddings to be populated):
```python
def vector_search(db: Session, query_vector: list[float], limit: int) -> list[dict]:
    sql = text("""
        SELECT canonical_id, title, abstract, arxiv_id, pmc_id, doi,
               tldr, token_count, year,
               1 - (embeddings <=> CAST(:vec AS vector)) AS score
        FROM papers
        WHERE embeddings IS NOT NULL
        ORDER BY score DESC
        LIMIT :limit
    """)
    return db.execute(sql, {"vec": str(query_vector), "limit": limit}).fetchall()
```

Hybrid query (D-09 formula: `0.5 * bm25 + 0.5 * vector`):
```python
def hybrid_search(db: Session, q: str, query_vector: list[float], limit: int):
    sql = text("""
        WITH bm25 AS (
            SELECT canonical_id,
                   ts_rank(
                       to_tsvector('english', coalesce(title,'') || ' ' || coalesce(abstract,'')),
                       plainto_tsquery('english', :q)
                   ) AS bm25_score
            FROM papers
            WHERE to_tsvector('english', coalesce(title,'') || ' ' || coalesce(abstract,''))
                  @@ plainto_tsquery('english', :q)
        ),
        vec AS (
            SELECT canonical_id,
                   1 - (embeddings <=> CAST(:vec AS vector)) AS vec_score
            FROM papers
            WHERE embeddings IS NOT NULL
        )
        SELECT p.canonical_id, p.title, p.abstract, p.arxiv_id, p.pmc_id, p.doi,
               p.tldr, p.token_count, p.year,
               (COALESCE(b.bm25_score, 0) * 0.5 + COALESCE(v.vec_score, 0) * 0.5) AS score
        FROM papers p
        LEFT JOIN bm25 b ON b.canonical_id = p.canonical_id
        LEFT JOIN vec v ON v.canonical_id = p.canonical_id
        WHERE b.canonical_id IS NOT NULL OR v.canonical_id IS NOT NULL
        ORDER BY score DESC
        LIMIT :limit
    """)
    return db.execute(sql, {"q": q, "vec": str(query_vector), "limit": limit}).fetchall()
```

### Pattern 6: Citation Graph Queries

References (papers this paper cites):
```python
def get_references(db: Session, canonical_id: uuid.UUID) -> list[dict]:
    sql = text("""
        SELECT pc.target_arxiv_id, pc.target_doi, pc.context_text,
               p.canonical_id, p.title, p.abstract, p.year, p.arxiv_id,
               p.pmc_id, p.doi, p.tldr, p.token_count,
               (p.canonical_id IS NOT NULL) AS in_corpus
        FROM paper_citations pc
        LEFT JOIN papers p ON p.canonical_id = pc.target_paper_id
        WHERE pc.source_paper_id = :cid
    """)
    return db.execute(sql, {"cid": str(canonical_id)}).fetchall()
```

Cited-by (papers in corpus that cite this paper):
```python
def get_cited_by(db: Session, canonical_id: uuid.UUID) -> list[dict]:
    sql = text("""
        SELECT p.canonical_id, p.title, p.abstract, p.arxiv_id, p.pmc_id,
               p.doi, p.tldr, p.token_count, p.year, pc.context_text
        FROM paper_citations pc
        JOIN papers p ON p.canonical_id = pc.source_paper_id
        WHERE pc.target_paper_id = :cid
    """)
    return db.execute(sql, {"cid": str(canonical_id)}).fetchall()
```

Related (co-cited papers, D-03):
```python
def get_related(db: Session, canonical_id: uuid.UUID, limit: int = 20) -> list[dict]:
    sql = text("""
        SELECT p.canonical_id, p.title, p.abstract, p.arxiv_id, p.pmc_id,
               p.doi, p.tldr, p.token_count, p.year,
               COUNT(*) AS co_citation_count
        FROM paper_citations pc1
        JOIN paper_citations pc2
            ON pc2.source_paper_id = pc1.source_paper_id
            AND pc2.target_paper_id != :cid
        JOIN papers p ON p.canonical_id = pc2.target_paper_id
        WHERE pc1.target_paper_id = :cid
          AND p.canonical_id IS NOT NULL
        GROUP BY p.canonical_id, p.title, p.abstract, p.arxiv_id, p.pmc_id,
                 p.doi, p.tldr, p.token_count, p.year
        ORDER BY co_citation_count DESC
        LIMIT :limit
    """)
    return db.execute(sql, {"cid": str(canonical_id), "limit": limit}).fetchall()
```

### Pattern 7: Pydantic v2 Response Models (D-22)

```python
# app/api/schemas.py
from __future__ import annotations
from typing import Any
from pydantic import BaseModel

class SectionObject(BaseModel):
    heading: str
    sec_num: str | None = None
    text: str
    paragraphs: list[dict] = []
    token_count: int = 0

class CitationObject(BaseModel):
    ref_id: str | None = None
    title: str | None = None
    authors: list[str] = []
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    raw_text: str | None = None

class HeadResponse(BaseModel):
    paper_id: str
    arxiv_id: str | None = None
    pmc_id: str | None = None
    doi: str | None = None
    title: str | None = None
    abstract: str | None = None
    tldr: str | None = None
    authors: list[str] = []
    year: int | None = None
    venue: str | None = None
    src_url: str = ""
    token_count: int = 0
    parse_source: str | None = None

# BriefResponse is the same shape as HeadResponse (D-02, REQUIREMENTS API-02)
BriefResponse = HeadResponse

class SectionsResponse(BaseModel):
    paper_id: str
    title: str | None = None
    sections: list[SectionObject] = []
    token_count: int = 0

class FullResponse(BaseModel):
    paper_id: str
    arxiv_id: str | None = None
    pmc_id: str | None = None
    doi: str | None = None
    title: str | None = None
    abstract: str | None = None
    tldr: str | None = None
    authors: list[str] = []
    year: int | None = None
    venue: str | None = None
    src_url: str = ""
    token_count: int = 0
    parse_source: str | None = None
    sections: list[SectionObject] = []
    citations: list[CitationObject] = []
    ref_entries: dict[str, Any] = {}
    back_matter: list[dict] = []

class SearchResultItem(BaseModel):
    paper_id: str
    arxiv_id: str | None = None
    pmc_id: str | None = None
    title: str | None = None
    abstract: str | None = None
    tldr: str | None = None
    authors: list[str] = []
    year: int | None = None
    src_url: str = ""
    token_count: int = 0

class SearchResponse(BaseModel):
    total: int
    results: list[SearchResultItem]

class ReferenceItem(BaseModel):
    # From paper_citations row
    target_arxiv_id: str | None = None
    target_doi: str | None = None
    context_text: str | None = None
    in_corpus: bool = False
    # Populated if in_corpus=True (head fields from joined papers row)
    paper_id: str | None = None
    title: str | None = None
    abstract: str | None = None
    authors: list[str] = []
    year: int | None = None
    arxiv_id: str | None = None
    pmc_id: str | None = None
    doi: str | None = None
    tldr: str | None = None
    token_count: int | None = None

class ReferencesResponse(BaseModel):
    paper_id: str
    references: list[ReferenceItem]

class CitedByItem(BaseModel):
    paper_id: str
    arxiv_id: str | None = None
    pmc_id: str | None = None
    title: str | None = None
    abstract: str | None = None
    authors: list[str] = []
    year: int | None = None
    tldr: str | None = None
    token_count: int | None = None
    context_text: str | None = None

class CitedByResponse(BaseModel):
    paper_id: str
    cited_by: list[CitedByItem]

class RelatedItem(BaseModel):
    paper_id: str
    arxiv_id: str | None = None
    pmc_id: str | None = None
    title: str | None = None
    abstract: str | None = None
    authors: list[str] = []
    year: int | None = None
    tldr: str | None = None
    token_count: int | None = None
    co_citation_count: int

class RelatedResponse(BaseModel):
    paper_id: str
    related: list[RelatedItem]

class ErrorResponse(BaseModel):
    error: str
    message: str
```

### Pattern 8: 404 Handling (D-19)

FastAPI's `HTTPException` allows custom detail bodies; but D-19 specifies a structured JSON body. Use `JSONResponse` directly for 404:

```python
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()

@router.get("/arxiv/{arxiv_id}/head")
async def get_arxiv_head(arxiv_id: str, db=Depends(get_db), redis=Depends(get_redis)):
    paper = resolve_arxiv_id(db, arxiv_id)
    if paper is None:
        return JSONResponse(
            status_code=404,
            content={"error": "not_found", "message": f"Paper {arxiv_id} not found"}
        )
    # ... continue
```

### Anti-Patterns to Avoid

- **Raw `KEYS *` in Redis:** Use `SCAN` iterator for pattern matching (D-18 invalidation). `KEYS` blocks the Redis server.
- **Calling `sentence-transformers` model inside a request handler without caching the model:** Load the model once at startup in `lifespan`, store on `app.state.embedding_model`. Per-request model loading takes 5-10 seconds.
- **Returning `None` fields as absent from JSON:** Pydantic v2 serializes `None` fields as `null` by default. deepxiv_sdk expects the key present with `null` value for `tldr`. Do not use `model_config = ConfigDict(exclude_none=True)`.
- **Using `paper.content` JSONB directly as response without Pydantic validation:** The JSONB may have extra internal keys (`dedup_fingerprint`, etc.) not in the response schema. Always construct response model from the JSONB, not pass it through verbatim.
- **Sync DB calls directly in async def handlers:** Blocks the event loop. Use `asyncio.to_thread(db_func)` or FastAPI's thread pool via standard `def` route handlers (FastAPI automatically runs sync `def` routes in a thread pool — this is the simplest approach).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Query embedding for vector search | Custom HTTP call to embedding service | `sentence_transformers.SentenceTransformer("all-MiniLM-L6-v2").encode(query)` | Model is local CPU-safe; no HTTP overhead; already specified in D-06 |
| Redis pattern-delete for invalidation | `KEYS papers:{id}:*` + bulk delete | `redis.scan_iter(match=pattern)` | KEYS blocks Redis; SCAN is non-blocking |
| Pydantic v2 JSON serialization | Manual `json.dumps` with custom encoder | `model.model_dump_json()` | Handles UUID, datetime, None correctly |
| API routing | Custom WSGI dispatcher | FastAPI `APIRouter` with `include_router` | Standard FastAPI pattern |

**Key insight:** The DB already holds all pre-computed content in `papers.content` JSONB. The API is mostly a read-and-reshape layer, not a compute layer. Complexity lives in the query logic (ID resolution, hybrid search ranking, co-citation query), not serialization.

---

## Common Pitfalls

### Pitfall 1: Schema Vector Dimension Mismatch
**What goes wrong:** `papers.embeddings` is `vector(768)` in the DB but `all-MiniLM-L6-v2` produces 384-dim vectors. Writing a 384-dim vector to a `vector(768)` column raises a PostgreSQL error. Vector search with mismatched dimensions fails silently or raises.
**Why it happens:** CONTEXT.md specifies 384 but the existing migration used 768.
**How to avoid:** Add Alembic migration 0004 to `ALTER TABLE papers ALTER COLUMN embeddings TYPE vector(384)`. Do this before any embedding write or vector search. Also update `app/models.py` `Vector(768)` → `Vector(384)`.
**Warning signs:** `ValueError: expected 768 dimensions, got 384` or `operator does not exist: vector <=> vector(384)` in logs.

### Pitfall 2: sentence-transformers Model Loading Latency
**What goes wrong:** Loading `all-MiniLM-L6-v2` takes 2-5 seconds. If loaded per-request, the first search request times out or is very slow.
**Why it happens:** Model weights (~90MB) need to be read from disk and loaded into RAM.
**How to avoid:** Load at startup in `lifespan` context manager; store on `app.state.embedding_model`. Inject via `request.app.state.embedding_model` in route handlers.
**Warning signs:** Search endpoint takes >5s for first request.

### Pitfall 3: JSONB Content Field Has Extra Internal Keys
**What goes wrong:** `papers.content` stores the full `paper_json` dict including internal keys like `dedup_fingerprint`, `parse_quality`, and the `src_url` as written by `normalize_paper`. Some of these fields may be stale or internally structured differently than the response schema expects.
**Why it happens:** The normalize task writes the full dict to `content` — it was not designed with the API response shape in mind.
**How to avoid:** Always extract specific fields from `paper.content` rather than passing the JSONB dict through. `src_url` should be re-derived from `paper.arxiv_id`/`paper.pmc_id` columns (same `_build_src_url` logic) rather than trusting `content["src_url"]` which may be empty string for newly inserted papers.
**Warning signs:** SDK receives unexpected fields or `src_url` is empty string for papers that have `arxiv_id`.

### Pitfall 4: ID Resolution Missing id_map Lookup
**What goes wrong:** A paper with `arxiv_id="2401.00001"` in the `papers` table was also catalogued under a PMC ID, creating an `id_map` record. A request for `/arxiv/2401.00001` finds the paper directly, but a request for `/arxiv/2401.00001v2` (with version suffix) does NOT find it because the version was not stripped.
**Why it happens:** Version suffix stripping must happen before both the direct column lookup and the id_map lookup (D-21).
**How to avoid:** Always apply `strip_arxiv_version()` before any query. Test with both `2401.00001` and `2401.00001v2` inputs.
**Warning signs:** 404 for version-suffixed IDs that exist in corpus.

### Pitfall 5: Sync DB Call Inside Async Handler Blocks Event Loop
**What goes wrong:** FastAPI handlers marked `async def` run in the event loop. Calling sync SQLAlchemy operations directly blocks the loop, causing all concurrent requests to stall.
**Why it happens:** SQLAlchemy sync sessions use blocking socket calls.
**How to avoid:** Either (a) declare route handlers as `def` instead of `async def` — FastAPI automatically runs sync `def` routes in a thread pool — or (b) wrap DB calls in `asyncio.to_thread(db_func, args)`. Option (a) is simpler for this codebase.
**Warning signs:** Concurrent requests serialize (no parallelism) or event loop warnings in uvicorn logs.

### Pitfall 6: Redis `scan_iter` for Cache Invalidation in Celery Task
**What goes wrong:** `normalize_paper` is a Celery task (sync). Using `redis.asyncio.Redis` there requires an event loop. Using sync `redis.Redis` for the task but `redis.asyncio.Redis` for the API creates two separate connections.
**Why it happens:** Celery workers are synchronous; FastAPI handlers are async.
**How to avoid:** In `normalize_paper` task, use sync `redis.Redis.from_url(settings.redis_url)` for cache invalidation. In API, use `redis.asyncio.Redis`. Both point to the same Redis instance.
**Warning signs:** `RuntimeError: no running event loop` in Celery worker logs.

### Pitfall 7: co-citation query returns source paper itself
**What goes wrong:** The `/related` co-citation query (D-03) may return the source paper itself if it cites papers that other papers also cite and those other papers cite the source back.
**Why it happens:** The JOIN logic without explicit exclusion of the source paper's canonical_id.
**How to avoid:** Add `AND pc2.target_paper_id != :cid` AND `AND p.canonical_id != :cid` to the related query.
**Warning signs:** `/related` response includes the paper itself in the results.

---

## Code Examples

### Embedding Model Setup at Startup

```python
# app/api/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from sentence_transformers import SentenceTransformer
import redis.asyncio as aioredis
from app.config import get_settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    app.state.embedding_model = SentenceTransformer(settings.embedding_model)
    yield
    await app.state.redis.aclose()

app = FastAPI(title="Research Knowledge Graph API", lifespan=lifespan)
app.include_router(arxiv_router, prefix="")
app.include_router(pmc_router, prefix="")
app.include_router(search_router, prefix="")
```

### Docker Service Addition

```yaml
# docker-compose.yml addition
  api:
    build: .
    env_file: .env
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    command: uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --reload
    restart: unless-stopped
```

### Embedding Model Config Setting

```python
# app/config.py additions
class Settings(BaseSettings):
    # ... existing fields ...
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    # redis_url already present
```

### Embedding Computation in normalize_paper

```python
# In normalize_paper task, after _upsert_paper, before session.commit():
def _write_embedding(session, paper, paper_json: dict, model_name: str) -> None:
    from sentence_transformers import SentenceTransformer
    import numpy as np
    model = SentenceTransformer(model_name)
    text = f"{paper_json.get('title', '')} {paper_json.get('abstract', '')}"
    vec = model.encode(text).tolist()
    paper.embeddings = vec
    session.add(paper)
```

Note: Loading the model in every Celery task invocation is expensive (~2-5s). Recommend caching the model at module level in `normalize.py` using a module-level dict keyed by model name.

---

## Embedding Dimension Fix — Alembic Migration Required

Phase 5 Wave 0 MUST include this migration before any embedding write:

```python
# alembic/versions/0004_fix_embeddings_dim.py
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0004"
down_revision = "0003a4f8c21b"

def upgrade():
    # Drop and recreate embeddings column with correct dimension
    op.drop_column("papers", "embeddings")
    op.add_column("papers", sa.Column("embeddings", Vector(384), nullable=True))
    # Also add HNSW index for fast vector search
    op.execute("""
        CREATE INDEX idx_papers_embeddings
        ON papers USING hnsw (embeddings vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)

def downgrade():
    op.drop_index("idx_papers_embeddings")
    op.drop_column("papers", "embeddings")
    op.add_column("papers", sa.Column("embeddings", Vector(768), nullable=True))
```

**Note on HNSW index:** pgvector supports two index types — IVFFlat and HNSW. HNSW (added in pgvector 0.5.0) provides better recall with no training data requirement. For a 10k paper corpus, HNSW with default params is appropriate. pgvector 0.4.2 (currently installed) may not support HNSW — verify. If not available, use IVFFlat: `USING ivfflat (embeddings vector_cosine_ops) WITH (lists = 100)`.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `on_startup`/`on_shutdown` decorators | `lifespan` context manager | FastAPI 0.93 (2023) | Must use lifespan for startup resources |
| `pydantic v1` `.dict()` method | `pydantic v2` `.model_dump()` | Pydantic 2.0 (2023) | `.dict()` still works but deprecated |
| `aioredis` separate package | `redis.asyncio` sub-module | redis-py 4.2+ (2022) | No separate aioredis install needed |
| `uvicorn` sync-only | `uvicorn[standard]` with httptools | uvicorn 0.17+ | `[standard]` extras add performance httptools + websockets |
| pgvector IVFFlat only | HNSW index also available | pgvector 0.5.0 (2023) | HNSW preferred for small-medium datasets |

---

## Open Questions

1. **pgvector version and HNSW support**
   - What we know: `pgvector==0.4.2` is in pyproject.toml; HNSW was added in pgvector 0.5.0 (library). The Docker image is `pgvector/pgvector:pg16` which may include a newer server-side pgvector.
   - What's unclear: Whether the `pgvector/pgvector:pg16` Docker image's server-side extension version supports HNSW, even if the Python client is 0.4.2.
   - Recommendation: In the migration, wrap the HNSW create in a try/except or check `SELECT extversion FROM pg_extension WHERE extname='vector'` first. Fall back to IVFFlat if HNSW unavailable.

2. **Embeddings not yet written by normalize_paper**
   - What we know: The existing `normalize_paper` task does NOT write embeddings (confirmed by code review of `app/tasks/normalize.py`). CONTEXT.md D-08 says they should be.
   - What's unclear: Whether Phase 5 adds embedding writing to the normalize task (retroactively populating embeddings for already-normalized papers via a backfill script) or only for new papers going forward.
   - Recommendation: Phase 5 should (a) add embedding writing to `normalize_paper`, and (b) include a one-shot backfill Celery task that re-runs embedding computation for all papers with `embeddings IS NULL`. Vector search degrades gracefully to empty results until backfill completes.

3. **`src_url` field — column vs. JSONB**
   - What we know: `papers` table has no `src_url` column. The value is written into `papers.content["src_url"]` by `normalize_paper`. The content JSONB may be null for newly ingested but not-yet-normalized papers.
   - What's unclear: Whether to read `src_url` from `content["src_url"]` or re-derive it from `arxiv_id`/`pmc_id` columns in the API handler.
   - Recommendation: Re-derive in the API using the same `_build_src_url` logic. This is more robust than trusting JSONB content.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (already in pyproject.toml dev deps) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` testpaths = ["tests"] |
| Quick run command | `pytest tests/test_api.py -x -q` |
| Full suite command | `pytest tests/ -x -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| API-01 | `/arxiv/{id}/head` returns HeadResponse shape | unit (TestClient) | `pytest tests/test_api.py::test_arxiv_head -x` | Wave 0 |
| API-02 | `/arxiv/{id}/brief` returns same shape as head | unit (TestClient) | `pytest tests/test_api.py::test_arxiv_brief -x` | Wave 0 |
| API-03 | `/arxiv/{id}/sections` returns SectionsResponse | unit (TestClient) | `pytest tests/test_api.py::test_arxiv_sections -x` | Wave 0 |
| API-04 | `/arxiv/{id}/full` returns FullResponse | unit (TestClient) | `pytest tests/test_api.py::test_arxiv_full -x` | Wave 0 |
| API-05 | Search returns SearchResponse; search_mode param accepted | unit (TestClient) | `pytest tests/test_api.py::test_search -x` | Wave 0 |
| API-06 | `/pmc/{id}/head` returns HeadResponse shape | unit (TestClient) | `pytest tests/test_api.py::test_pmc_head -x` | Wave 0 |
| API-07 | `/pmc/{id}/full` returns FullResponse | unit (TestClient) | `pytest tests/test_api.py::test_pmc_full -x` | Wave 0 |
| API-08 | All endpoints return 404 structured body for missing IDs | unit (TestClient) | `pytest tests/test_api.py::test_404 -x` | Wave 0 |
| API-09 | Redis cache active; second identical request returns cached value | unit (mock Redis) | `pytest tests/test_api.py::test_redis_cache -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_api.py -x -q`
- **Per wave merge:** `pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_api.py` — covers all API-01 through API-09 using `fastapi.testclient.TestClient`
- [ ] `tests/conftest.py` — shared fixtures: mock DB session with fixture papers, mock Redis client

*(No framework install needed — pytest already in dev deps)*

---

## Sources

### Primary (HIGH confidence)
- `app/models.py` — ORM column types, vector dim discrepancy confirmed (768 vs 384)
- `app/tasks/normalize.py` — confirmed embeddings are NOT written; `_build_src_url` exists and is reusable
- `alembic/versions/0001_initial_schema.py` — GIN FTS index shape confirmed (`idx_papers_fts`)
- `alembic/versions/0003_paper_citations_unique.py` — constraint name `uq_paper_citations_source_target_arxiv` confirmed
- `app/db.py` — sync-only session, no async engine
- `app/config.py` — `redis_url` already present; `embedding_model` field missing
- `pyproject.toml` — dependency list; fastapi/uvicorn/sentence-transformers NOT yet installed
- `docker-compose.yml` — no `api` service exists yet

### Secondary (MEDIUM confidence)
- redis-py 5.x documentation: `redis.asyncio` sub-module confirmed available in redis 5.x
- FastAPI lifespan pattern: documented in FastAPI 0.93+ official docs
- pgvector HNSW: added in pgvector extension 0.5.0; pgvector Python package 0.4.2 may use newer server extension

### Tertiary (LOW confidence)
- pgvector Docker image server-side extension version — not directly verified; assume `pgvector/pgvector:pg16` ships extension version >= 0.5.0 (image is actively maintained)

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — verified against pyproject.toml and existing codebase
- Architecture: HIGH — patterns derived from existing code structure and locked decisions
- Pitfalls: HIGH — identified from code inspection (vector dim mismatch confirmed by reading migrations, async issue confirmed by reading db.py)
- Schema discrepancy: HIGH — confirmed by direct code reading

**Research date:** 2026-04-15
**Valid until:** 2026-05-15 (stable libraries)
