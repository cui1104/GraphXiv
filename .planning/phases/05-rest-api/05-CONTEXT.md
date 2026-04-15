# Phase 5: REST API - Context

**Gathered:** 2026-04-15
**Status:** Ready for planning

<domain>
## Phase Boundary

Build and expose all REST API endpoints that the deepxiv_sdk `Reader` class consumes, plus citation graph endpoints and hybrid search. All 7 core endpoints, 3 citation graph endpoints, and 1 search endpoint (BM25 + pgvector hybrid). Redis cache-aside active on all endpoints. FastAPI app runs as a separate `api` Docker service on port 8000.

</domain>

<decisions>
## Implementation Decisions

### Endpoint scope
- **D-01:** All 10 endpoints ship in Phase 5:
  - 7 core: `GET /arxiv/{id}/head`, `/brief`, `/sections`, `/full`, `/search`, `/pmc/{id}/head`, `/pmc/{id}/full`
  - 3 citation graph: `GET /arxiv/{id}/references`, `/cited_by`, `/related`
- **D-02:** Citation graph endpoints are included because `paper_citations` table is already populated and Phase 6 (SDK fork) needs them immediately
- **D-03:** `/related` uses co-citation query (papers frequently cited alongside this one via GROUP BY on `paper_citations`)

### Search implementation
- **D-04:** Hybrid search — BM25 (PostgreSQL `tsvector` via `idx_papers_fts` GIN index) + pgvector semantic similarity
- **D-05:** `search_mode` query param: `bm25` | `vector` | `hybrid` (default: `hybrid`)
- **D-06:** Embedding model: `sentence-transformers/all-MiniLM-L6-v2` (384-dim, CPU-safe)
- **D-07:** Model is configurable via `EMBEDDING_MODEL` env var — when a GPU VM is available, swap model + re-embed all papers via a migration script + Alembic migration for new vector dim
- **D-08:** Embeddings are computed at normalize time (inside `normalize_paper` Celery task) and stored in `papers.embeddings` (vector(384))
- **D-09:** BM25 score: `ts_rank(to_tsvector('english', title || ' ' || abstract), plainto_tsquery('english', query))`; vector score: `1 - (embeddings <=> query_vector)`; hybrid score: `0.5 * bm25 + 0.5 * vector`

### Docker service
- **D-10:** New `api` service in `docker-compose.yml` — separate container from Celery worker
- **D-11:** Command: `uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --reload` (dev) / without `--reload` (prod)
- **D-12:** Host port mapping: `8000:8000`
- **D-13:** No authentication, no rate limiting — open API for local research use

### Redis caching
- **D-14:** Cache-aside pattern on all endpoints: check Redis → hit: return cached JSON → miss: query DB → serialize → cache → return
- **D-15:** Cache key format: `papers:{canonical_id}:{view}` where view ∈ {head, brief, sections, full, references, cited_by, related}
- **D-16:** Search results cached at key `search:{md5(q+limit+search_mode)}`, TTL 300s
- **D-17:** Paper view TTL: 3600s; search TTL: 300s
- **D-18:** Cache invalidation: on `normalize_paper` upsert, delete all `papers:{canonical_id}:*` keys

### Error handling
- **D-19:** 404 returns `{"error": "not_found", "message": "Paper {id} not found"}` — structured body, not bare HTTP error
- **D-20:** ID resolution: any input ID (arxiv_id with/without version suffix, pmcid, doi) resolved to `canonical_id` via `id_map` table before querying `papers`
- **D-21:** Version suffix is stripped from arXiv IDs on input (e.g., `2401.00001v2` → `2401.00001`)

### Response schemas
- **D-22:** Pydantic v2 models for all response types — field names exactly match FEATURES.md schema (HeadResponse, BriefResponse, SectionsResponse, FullResponse, SearchResponse, PmcHeadResponse, PmcFullResponse, ReferencesResponse, CitedByResponse, RelatedResponse)
- **D-23:** SQLAlchemy 2.x async queries (AsyncSession) for non-blocking DB access under concurrent requests

### Claude's Discretion
- Exact Pydantic model inheritance structure (whether Head/Brief share a base model)
- Uvicorn worker count and concurrency settings
- Order of middleware (CORS, logging, etc.)
- Whether to use FastAPI's dependency injection for DB sessions and Redis client

</decisions>

<specifics>
## Specific Ideas

- Embedding model upgrade path: when VM is available, set `EMBEDDING_MODEL=BAAI/bge-large-en-v1.5` (1024-dim), run re-embed Celery task on all papers, add Alembic migration to resize `embeddings` column to `vector(1024)`
- `/related` endpoint: co-citation query — find all papers in corpus that share ≥1 cited paper with the target, ranked by co-citation count
- The `api` Docker service shares the same image base as `worker` (same `pyproject.toml` deps) but runs Uvicorn instead of Celery

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### API contract (field names, response shapes)
- `.planning/research/FEATURES.md` — Complete JSON schema for all response types; deepxiv_sdk Reader field names; endpoint URL patterns; section/citation object shapes

### Database schema
- `app/models.py` — ORM models for Paper, PaperSource, IdMap, PaperCitation; column names and types used by all query handlers
- `alembic/versions/` — Migration history; current schema state

### Existing app structure
- `app/api/__init__.py` — Empty package; Phase 5 creates `app/api/main.py`, `app/api/routes/`, `app/api/schemas.py`
- `app/db.py` — `SessionLocal` and connection setup (async session pattern to be added)
- `app/config.py` — Settings class; `EMBEDDING_MODEL` env var to be added here

### Normalization output (what the API serves)
- `.planning/phases/04-normalizer-storage/04-RESEARCH.md` — PaperJSON field names as stored in `papers.content` JSONB; exact key names the API reads from DB

### Phase requirements
- `.planning/REQUIREMENTS.md` §REST API — API-01 through API-13 requirement IDs

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `app/db.py` → `SessionLocal`: sync SQLAlchemy session factory — Phase 5 needs async equivalent (`AsyncSession`) or can use sync with threadpool
- `app/models.py` → `Paper`, `IdMap`, `PaperCitation`: ORM models used directly in route handlers
- `app/tasks/normalize.py` → `_build_src_url()`: reusable for constructing `src_url` in responses (already produces arXiv/PMC canonical URLs)
- `app/config.py` → `Settings`: add `EMBEDDING_MODEL`, `REDIS_URL` settings here

### Established Patterns
- `shared_task` decorator: all tasks use this — API routes do NOT use it
- `SessionLocal()` context manager pattern: established in tasks — replicate for route handlers
- `paper.canonical_id` (UUID): primary key for all cross-table joins

### Integration Points
- `papers.content` JSONB: the API reads from this column; field names must match what Phase 4 normalizer wrote
- `paper_citations` table: populated by `_upsert_citations` in Phase 4; `/references`, `/cited_by`, `/related` read from this
- `papers.embeddings` vector(384): populated by Phase 5's embedding task; vector search queries this column
- Redis: already running in Docker Compose; Phase 5 connects via `REDIS_URL` setting
- `docker-compose.yml`: Phase 5 adds `api` service here

</code_context>

<deferred>
## Deferred Ideas

- Re-embedding all papers with a larger model (e.g., `BAAI/bge-large-en-v1.5`) — when GPU VM is available; requires re-embed Celery task + Alembic migration
- Per-paragraph cite_spans / ref_spans in sections (v2 feature per REQUIREMENTS.md EXT-01)
- Table HTML rendering in ref_entries (v2, EXT-03)
- Rate limiting / API key auth — not needed for local research use

</deferred>

---

*Phase: 05-rest-api*
*Context gathered: 2026-04-15*
