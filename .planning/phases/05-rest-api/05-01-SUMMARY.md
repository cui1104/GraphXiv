---
phase: 05-rest-api
plan: 01
subsystem: api
tags: [fastapi, pydantic, uvicorn, redis, sentence-transformers, pgvector, alembic, docker]

# Dependency graph
requires:
  - phase: 04-normalizer-storage
    provides: Paper model with JSONB content, normalize_paper task, db.py SessionLocal
  - phase: 01-foundation
    provides: SQLAlchemy models, Alembic migrations, Docker Compose stack
provides:
  - FastAPI app factory (app/api/main.py) with lifespan for Redis and lazy embedding model
  - All 14 Pydantic v2 response models matching FEATURES.md / deepxiv_sdk field names exactly
  - FastAPI dependency injection (get_db, get_redis) in app/api/deps.py
  - Stub route handlers for all 10 endpoints (7 arXiv + 2 PMC + 1 search) returning 501
  - Docker api service on port 8000
  - Alembic migration 0004 fixing embeddings column from Vector(768) to Vector(384) with HNSW index
  - Test scaffold with 9 stubs (API-01..09) all passing
affects:
  - 05-02 (endpoint logic — implements against these route stubs and schemas)
  - 05-03 (caching + search — uses get_redis dep and SearchResponse schema)
  - 06-sdk-fork (SDK will consume these exact Pydantic field names)

# Tech tracking
tech-stack:
  added:
    - fastapi>=0.115.0
    - uvicorn[standard]>=0.30.0
    - sentence-transformers>=2.7.0 (lazy-loaded on first search request)
  patterns:
    - FastAPI app factory with asynccontextmanager lifespan (not deprecated on_event)
    - Sync route handlers (def not async def) for SQLAlchemy threadpool integration
    - Dependency injection: get_db yields SessionLocal, get_redis returns app.state.redis
    - BriefResponse = HeadResponse alias pattern (same schema, separate route)
    - Lazy embedding model (app.state.embedding_model = None at startup, loaded on first /search)

key-files:
  created:
    - app/api/main.py
    - app/api/schemas.py
    - app/api/deps.py
    - app/api/routes/__init__.py
    - app/api/routes/arxiv.py
    - app/api/routes/pmc.py
    - app/api/routes/search.py
    - alembic/versions/0004_fix_embeddings_dim.py
    - tests/test_api.py
  modified:
    - pyproject.toml (added fastapi, uvicorn, sentence-transformers)
    - app/config.py (added embedding_model field)
    - app/models.py (Vector(768) -> Vector(384))
    - docker-compose.yml (added api service)

key-decisions:
  - "Lazy embedding model load: app.state.embedding_model = None at startup, loaded on first /search request to avoid ~30s startup delay when not searching"
  - "BriefResponse = HeadResponse alias (not a subclass) — deepxiv_sdk brief/head distinction is purely a routing concern; schema is identical"
  - "Sync route handlers (def not async def) for all DB-touching endpoints — FastAPI runs sync handlers in threadpool, avoiding asyncio event loop blocking with sync SQLAlchemy"
  - "exclude_none=True NOT used on model_config — deepxiv_sdk expects tldr key present as null, not omitted"
  - "HNSW index preferred for embeddings with IVFFlat fallback for pgvector < 0.5.0"

patterns-established:
  - "Pattern: FastAPI lifespan context manager for startup/shutdown resource management"
  - "Pattern: Stub routes return 501 with consistent error body {error, message} for Plan 02 skeleton"

requirements-completed: [API-01, API-02, API-03, API-04, API-05, API-06, API-07, API-08]

# Metrics
duration: 3min
completed: 2026-04-15
---

# Phase 5 Plan 01: REST API Scaffold Summary

**FastAPI skeleton with 14 Pydantic v2 models matching deepxiv_sdk schema, 10 stub endpoints, Docker api service, and Alembic migration fixing embeddings from Vector(768) to Vector(384)**

## Performance

- **Duration:** 3 min
- **Started:** 2026-04-15T01:21:29Z
- **Completed:** 2026-04-15T01:24:49Z
- **Tasks:** 2
- **Files modified:** 13

## Accomplishments

- All 14 Pydantic v2 response models created with exact field names from FEATURES.md — HeadResponse, BriefResponse (alias), SectionsResponse, FullResponse, SearchResponse, ReferencesResponse, CitedByResponse, RelatedResponse, ErrorResponse, plus sub-objects SectionObject, CitationObject, SearchResultItem, ReferenceItem, CitedByItem, RelatedItem
- FastAPI app factory with asynccontextmanager lifespan wiring Redis and all 3 routers; all 10 routes registered and confirmed via `python3 -c "from app.api.main import app; print(app.routes)"`
- Test scaffold with 9 stub tests all passing: `pytest tests/test_api.py -x -q` → 9 passed in 0.15s

## Task Commits

1. **Task 1: Dependencies, config, Alembic migration, ORM fix, Docker api service** - `7678256` (feat)
2. **Task 2: Pydantic schemas, deps, FastAPI main app, route stubs, test scaffold** - `d68fb1f` (feat)

## Files Created/Modified

- `app/api/main.py` - FastAPI app factory with lifespan, CORS, 3 routers, /health endpoint
- `app/api/schemas.py` - 14 Pydantic v2 response models matching FEATURES.md schema
- `app/api/deps.py` - get_db (SessionLocal generator) and get_redis (from app.state) deps
- `app/api/routes/arxiv.py` - 7 arXiv stub handlers returning 501
- `app/api/routes/pmc.py` - 2 PMC stub handlers returning 501
- `app/api/routes/search.py` - 1 search stub handler returning 501
- `app/api/routes/__init__.py` - empty package marker
- `alembic/versions/0004_fix_embeddings_dim.py` - drop/recreate embeddings as Vector(384) with HNSW index
- `tests/test_api.py` - 9 test stubs for API-01..09
- `pyproject.toml` - added fastapi, uvicorn[standard], sentence-transformers
- `app/config.py` - added embedding_model field
- `app/models.py` - Vector(768) -> Vector(384)
- `docker-compose.yml` - added api service on port 8000

## Decisions Made

- Lazy embedding model: `app.state.embedding_model = None` at startup — avoids 30s sentence-transformers load when not running searches
- BriefResponse is an alias `BriefResponse = HeadResponse` not a subclass — schema is identical, distinction is routing-only
- Sync `def` route handlers throughout — FastAPI threadpool handles sync SQLAlchemy calls safely
- `exclude_none=True` NOT set on model_config — deepxiv_sdk Reader expects `tldr` key present as null

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Known Stubs

All route handlers are intentional stubs returning HTTP 501 until Plan 05-02 implements the endpoint logic. This is the plan's stated goal — skeleton only. Plan 05-02 will replace these stubs with real DB queries.

## User Setup Required

None - no external service configuration required for this scaffold plan.

## Next Phase Readiness

- Plan 05-02 (endpoint logic) can now implement against known route signatures, Pydantic schemas, and dependency contracts
- Plan 05-03 (caching + search) has get_redis dep and SearchResponse schema ready
- Docker api service is defined; starts with `docker compose up api`
- Alembic migration 0004 must be applied before Plan 05-02 (`alembic upgrade head`)

---
*Phase: 05-rest-api*
*Completed: 2026-04-15*
