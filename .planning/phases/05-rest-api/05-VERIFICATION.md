---
phase: 05-rest-api
verified: 2026-04-15T20:00:00Z
status: passed
score: 13/13 requirements verified
re_verification: false
gaps: []
human_verification:
  - test: "Make two identical GET /arxiv/{id}/head requests against a running stack (docker compose up) and check Redis with KEYS papers:*"
    expected: "Second request served in < 5ms; KEYS shows entries matching papers:{uuid}:head"
    why_human: "TestClient runs in-process with MockRedis; real TTL expiry and Redis persistence cannot be verified without a live Redis instance"
  - test: "GET /arxiv/search?q=attention&limit=5 (hybrid mode) against a stack with embeddings populated"
    expected: "Returns at least one result; search falls back to BM25 gracefully if no embeddings; no 500 error"
    why_human: "Vector/hybrid path requires a live pgvector-enabled PostgreSQL with populated embeddings column; unit tests mock the DB layer"
---

# Phase 5: REST API Verification Report

**Phase Goal:** All 7 FastAPI endpoints return correctly shaped JSON that the deepxiv_sdk `Reader` class can consume without empty-value responses, with Redis caching active.
**Verified:** 2026-04-15T20:00:00Z
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Note on Requirement Scope

The ROADMAP lists "Requirements: API-01, API-02, API-03, API-04, API-05, API-06, API-07, API-08, API-09" for Phase 5. However, REQUIREMENTS.md and all three PLAN frontmatter files together claim API-01 through API-13 for Phase 5. All 13 are verified below. The prompt's listed IDs (API-01 through API-09) are a subset; no requirements in the full set are orphaned.

---

### Observable Truths

| #  | Truth | Status | Evidence |
|----|-------|--------|----------|
| 1  | FastAPI app starts via uvicorn without import errors | VERIFIED | `from app.api.main import app` succeeds; all routers register cleanly |
| 2  | All Pydantic response models exist with exact field names matching FEATURES.md schema | VERIFIED | `app/api/schemas.py` defines HeadResponse, BriefResponse, SectionsResponse, FullResponse, SearchResponse, ReferencesResponse, CitedByResponse, RelatedResponse, ErrorResponse with correct fields |
| 3  | Alembic migration 0004 changes embeddings column from vector(768) to vector(384) | VERIFIED | `alembic/versions/0004_fix_embeddings_dim.py` exists; `app/models.py` uses `Vector(384)` |
| 4  | Docker api service defined in docker-compose.yml | VERIFIED | `docker-compose.yml` line 71: `api:` service with `command: uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --reload` and port `8000:8000` |
| 5  | GET /arxiv/{id}/head, /brief, /sections, /full return 200 with correct shape | VERIFIED | Unit tests pass; handlers use real ORM queries via `asyncio.to_thread`; 404 path returns structured error |
| 6  | GET /arxiv/search returns {total, results} supporting bm25/vector/hybrid modes | VERIFIED | `_bm25_search`, `_vector_search`, `_hybrid_search` implemented; graceful fallback to BM25 when no embeddings |
| 7  | GET /pmc/{id}/head and /full return correctly shaped responses | VERIFIED | `pmc.py` implements `resolve_pmc_id`, both endpoints wired with cache-aside |
| 8  | Unknown ID returns HTTP 404 with {error, message} body | VERIFIED | All 9 endpoint handlers return `JSONResponse(status_code=404, content={"error": "not_found", ...})`; `test_404` asserts this |
| 9  | Redis cache-aside active on all endpoints with correct TTLs and key format | VERIFIED | `app/api/cache.py` defines `PAPER_TTL=3600`, `SEARCH_TTL=300`; all handlers call `await get_cached` / `await set_cache`; `test_redis_cache` asserts key set after first request |
| 10 | Cache invalidated when normalize_paper upserts a paper | VERIFIED | `_invalidate_cache` in `normalize.py` uses SCAN cursor loop; called inside try/except in normalize_paper |
| 11 | arXiv version suffix stripped (2401.00001v2 -> 2401.00001) | VERIFIED | `strip_arxiv_version` with `ARXIV_VERSION_RE`; `test_arxiv_version_stripping` unit test passes |
| 12 | GET /arxiv/{id}/references returns citation list with in_corpus flag | VERIFIED | SQL LEFT JOIN on paper_citations; `in_corpus = row.canonical_id is not None`; cached under `references` view |
| 13 | GET /arxiv/{id}/cited_by and /related return co-citation graph data | VERIFIED | `arxiv_cited_by` and `arxiv_related` with correct SQL; co_citation_count in RelatedItem |

**Score:** 13/13 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `app/api/main.py` | FastAPI app factory with lifespan | VERIFIED | `app = FastAPI(...)` with async lifespan; 3 `include_router` calls |
| `app/api/schemas.py` | All Pydantic v2 response models | VERIFIED | 14 classes including all required exports; `BriefResponse = HeadResponse` alias present |
| `app/api/deps.py` | DB session and Redis dependency injection | VERIFIED | `get_db()` and `async def get_redis(request)` both present; imports from `app.db` |
| `app/api/cache.py` | Cache utility module | VERIFIED | `PAPER_TTL=3600`, `SEARCH_TTL=300`, `paper_cache_key`, `search_cache_key` with MD5 |
| `app/api/routes/arxiv.py` | All 7 arXiv endpoint implementations | VERIFIED | 7 routes: head, brief, sections, full, references, cited_by, related — all async, all cached |
| `app/api/routes/pmc.py` | PMC head and full implementations | VERIFIED | `resolve_pmc_id`, 2 routes both async with cache-aside |
| `app/api/routes/search.py` | Hybrid search with bm25/vector/hybrid | VERIFIED | All 3 modes implemented; `CAST(:vec AS vector)` for pgvector; authors from content JSONB |
| `app/tasks/normalize.py` | Embedding write + cache invalidation | VERIFIED | `_write_embedding` with module-level `_EMBEDDING_MODEL` cache; `_invalidate_cache` with SCAN |
| `tests/test_api.py` | Tests for all endpoints with mock DB | VERIFIED | 11 tests collected; all 11 pass; `MockRedis` class; autouse fixture for clean overrides |
| `alembic/versions/0004_fix_embeddings_dim.py` | Migration for Vector(768)->Vector(384) | VERIFIED | Exists; `Vector(384)` in add_column; HNSW index creation |
| `docker-compose.yml` | `api:` service | VERIFIED | Service defined with port 8000, uvicorn command, health check depends_on |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `app/api/main.py` | `app/api/routes/arxiv.py` | `include_router` | WIRED | Line 44: `app.include_router(arxiv_router)` |
| `app/api/main.py` | `app/api/routes/pmc.py` | `include_router` | WIRED | Line 45: `app.include_router(pmc_router)` |
| `app/api/main.py` | `app/api/routes/search.py` | `include_router` | WIRED | Line 46: `app.include_router(search_router)` |
| `app/api/deps.py` | `app/db.py` | `SessionLocal import` | WIRED | `from app.db import SessionLocal` present |
| `app/api/routes/arxiv.py` | `app/models.py` | `Paper, IdMap, PaperCitation ORM queries` | WIRED | `from app.models import Paper, IdMap, PaperCitation` |
| `app/api/routes/arxiv.py` | redis | `await get_cached / await set_cache` | WIRED | All 7 handlers call both functions |
| `app/api/routes/pmc.py` | `app/api/routes/arxiv.py` | `_paper_to_head` import | WIRED | `from app.api.routes.arxiv import _paper_to_head` |
| `app/api/routes/search.py` | sentence_transformers | `embedding_model.encode` | WIRED | Lazy-loads SentenceTransformer on first use; checked against `app.state.embedding_model` |
| `app/tasks/normalize.py` | redis | `r.scan cursor + delete` | WIRED | `_invalidate_cache` uses sync `redis.from_url`; SCAN loop pattern confirmed |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| API-01 | 05-01, 05-02 | GET /arxiv/{id}/head metadata response | SATISFIED | Route at line 98 of arxiv.py; unit test passes |
| API-02 | 05-01, 05-02 | GET /arxiv/{id}/brief same shape as head | SATISFIED | Route at line 120; `BriefResponse = HeadResponse` alias |
| API-03 | 05-01, 05-02 | GET /arxiv/{id}/sections sections-only response | SATISFIED | Route at line 142; returns `sections` list from content JSONB |
| API-04 | 05-01, 05-02 | GET /arxiv/{id}/full complete paper object | SATISFIED | Route at line 171; includes sections, citations, ref_entries, back_matter |
| API-05 | 05-01, 05-02 | GET /arxiv/search keyword search | SATISFIED | Route in search.py; BM25 implemented; test passes with bm25 mode |
| API-06 | 05-01, 05-02 | GET /pmc/{id}/head | SATISFIED | Route at line 47 of pmc.py; `resolve_pmc_id` helper |
| API-07 | 05-01, 05-02 | GET /pmc/{id}/full | SATISFIED | Route at line 69 of pmc.py |
| API-08 | 05-01, 05-02 | HTTP 404 with structured error body | SATISFIED | All 9 handlers return `{"error": "not_found", ...}`; `test_404` asserts 404 status and error key |
| API-09 | 05-03 | Redis caching layer active; cache keys papers:{canonical_id}:{view} | SATISFIED | `app/api/cache.py` complete; `test_redis_cache` verifies key format and population |
| API-10 | 05-02 | Hybrid search with search_mode parameter (bm25/vector/hybrid) | SATISFIED | All 3 modes in search.py; fallback to BM25 when no embeddings |
| API-11 | 05-02 | GET /arxiv/{id}/references with in_corpus flag and context_text | SATISFIED | Route at line 201 of arxiv.py; LEFT JOIN on paper_citations; in_corpus derived from canonical_id presence |
| API-12 | 05-02 | GET /arxiv/{id}/cited_by | SATISFIED | Route at line 258 of arxiv.py; JOIN on paper_citations.target_paper_id |
| API-13 | 05-02 | GET /arxiv/{id}/related co-cited papers | SATISFIED | Route at line 310; co-citation SQL with COUNT(*) + ORDER BY; limit param |

**Note:** The ROADMAP Phase 5 header lists "Requirements: API-01 through API-09" but REQUIREMENTS.md and the PLAN files together cover API-01 through API-13. All 13 are implemented and verified. No orphaned requirements.

---

### Anti-Patterns Found

No blocking anti-patterns found.

| File | Pattern | Severity | Notes |
|------|---------|----------|-------|
| `app/api/routes/search.py` line 33 | `SEARCH_TTL = SEARCH_TTL` re-assignment | Info | Harmless self-assignment left for grep-ability per comment; no behavioral impact |
| Route registration order | `/arxiv/search` registered after `/arxiv/{arxiv_id}/...` in route list | Info | Not a real issue — FastAPI/Starlette distinguishes path segment count; `/arxiv/search` (1 segment after /arxiv/) does not conflict with `/arxiv/{id}/head` (2 segments). Confirmed working by test. |

---

### Human Verification Required

#### 1. Live Redis cache behavior

**Test:** `docker compose up`, make `GET /arxiv/{id}/head` twice for a known paper, then run `redis-cli KEYS 'papers:*'`
**Expected:** Second request faster (< 5ms); KEYS shows `papers:{canonical_id}:head` entry with TTL ~3600s
**Why human:** TestClient uses an in-process MockRedis; real network round-trip, TTL expiry, and Redis persistence cannot be verified programmatically without a live stack

#### 2. Hybrid search with populated embeddings

**Test:** After running the normalizer on a batch of papers, `GET /arxiv/search?q=attention&limit=5&search_mode=hybrid`
**Expected:** Returns results with non-empty `results` array; no 500 error; `search_mode=vector` also returns results
**Why human:** Requires live pgvector-enabled PostgreSQL with embeddings column populated by `_write_embedding`; unit tests mock the DB execute path

---

### Test Suite Results

```
pytest tests/test_api.py -x -q -m "not integration"
11 passed in 0.29s
```

All 11 tests collected and pass:
- `test_arxiv_head` — API-01
- `test_arxiv_brief` — API-02
- `test_arxiv_sections` — API-03
- `test_arxiv_full` — API-04
- `test_search` — API-05
- `test_pmc_head` — API-06
- `test_pmc_full` — API-07
- `test_404` — API-08
- `test_arxiv_version_stripping` — version normalization
- `test_redis_cache` — API-09 cache key format and population
- `test_cache_invalidation` — API-09 SCAN-based invalidation

---

### Summary

Phase 5 goal is fully achieved. The 10 endpoints (7 arXiv + 2 PMC + 1 search) are all implemented with real DB queries, ID resolution (version stripping + id_map fallback), 404 structured error handling, and Redis cache-aside. The three citation graph endpoints (references, cited_by, related — API-11/12/13) exceeded the ROADMAP minimum of 9 endpoints and are also complete. Cache key format matches the `papers:{canonical_id}:{view}` and `search:{md5}` specs. Cache invalidation in `normalize_paper` uses SCAN (not KEYS). All 11 unit tests pass without a live database or Redis.

Two items require human testing against a live stack: real Redis TTL behavior and the vector/hybrid search path with populated embeddings.

---

_Verified: 2026-04-15T20:00:00Z_
_Verifier: Claude (gsd-verifier)_
