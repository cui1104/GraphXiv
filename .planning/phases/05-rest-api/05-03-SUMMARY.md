---
phase: 05-rest-api
plan: "03"
subsystem: api-caching
tags: [redis, cache-aside, celery, invalidation, fastapi]
dependency_graph:
  requires: [05-02]
  provides: [API-09, redis-cache-layer]
  affects: [app/api/cache.py, app/api/routes/arxiv.py, app/api/routes/pmc.py, app/api/routes/search.py, app/tasks/normalize.py]
tech_stack:
  added: [redis-cache-aside]
  patterns: [cache-aside, asyncio.to_thread, SCAN-cursor-invalidation]
key_files:
  created:
    - app/api/cache.py
  modified:
    - app/api/routes/arxiv.py
    - app/api/routes/pmc.py
    - app/api/routes/search.py
    - app/tasks/normalize.py
    - tests/test_api.py
decisions:
  - "D-23: Convert route handlers from sync def to async def; wrap sync SQLAlchemy calls in asyncio.to_thread() — no asyncpg or AsyncSession introduced"
  - "D-18: Cache invalidation in normalize_paper uses sync redis.Redis (not asyncio) because Celery tasks are synchronous; SCAN cursor loop not KEYS"
  - "MockRedis autouse fixture injects async dict-backed store for all API tests — avoids needing live Redis in CI"
metrics:
  duration: "8min"
  completed: "2026-04-15"
  tasks: 2
  files: 5
---

# Phase 5 Plan 3: Redis Cache-Aside Layer Summary

**One-liner:** Redis cache-aside on all 9 API endpoints (PAPER_TTL=3600s, SEARCH_TTL=300s) with SCAN-based invalidation in normalize_paper Celery task.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Add cache-aside to all route handlers | 35689f4 | app/api/cache.py, arxiv.py, pmc.py, search.py |
| 2 | Cache invalidation in normalize_paper + cache behavior tests | e892dbc | app/tasks/normalize.py, tests/test_api.py |

## What Was Built

### app/api/cache.py (new)
Central cache utility module:
- `PAPER_TTL = 3600` — 1 hour TTL for paper views (D-17)
- `SEARCH_TTL = 300` — 5 minute TTL for search results (D-17)
- `get_cached(redis, key)` — async cache lookup, returns parsed dict or None
- `set_cache(redis, key, data, ttl)` — async cache write with `json.dumps(default=str)` for UUID serialization
- `paper_cache_key(canonical_id, view)` — returns `papers:{canonical_id}:{view}` (D-15)
- `search_cache_key(q, limit, search_mode)` — returns `search:{md5(q:limit:mode)}` (D-16)

### Route Handler Changes
All 9 handlers converted to `async def` with cache-aside pattern:
- Check `await get_cached(redis, key)` before DB query
- On miss: run sync DB calls via `await asyncio.to_thread(...)` (D-23)
- After building response: `await set_cache(redis, key, response_dict, TTL)`
- 404 paths (paper not found) are NOT cached — only successful lookups

View names follow D-15: `head`, `brief`, `sections`, `full`, `references`, `cited_by`, `related`

### Cache Invalidation (normalize.py)
`_invalidate_cache(paper)` function added:
- Uses sync `redis.Redis` (not asyncio) — Celery tasks are synchronous
- Pattern `papers:{paper.canonical_id}:*` matched via SCAN cursor loop (not KEYS)
- Called after `_upsert_citations()` and before `session.commit()`
- Wrapped in `try/except` so Redis failures never break the normalization task

### Test Changes (tests/test_api.py)
- Added `MockRedis` — async dict-backed store (no live Redis required)
- Added `override_get_redis()` dependency override factory
- Updated `reset_dependency_overrides` autouse fixture to inject fresh MockRedis for every test — fixes all 9 existing tests that were broken by async Redis requirement
- `test_redis_cache`: verifies `papers:{canonical_id}:head` key set after first request; verifies second request returns identical response
- `test_cache_invalidation`: verifies `_invalidate_cache` imports and uses SCAN + canonical_id

## Deviations from Plan

None — plan executed exactly as written. The route files and cache.py were already in their final form (written ahead in 05-02 planning cycle). The only work needed was Task 2 (invalidation + tests).

## Verification

```
pytest tests/test_api.py -x -q -m "not integration"  → 11 passed
pytest tests/ -x -q -m "not integration"              → 70 passed, 5 skipped
```

## Self-Check: PASSED

- app/api/cache.py: FOUND
- app/tasks/normalize.py contains _invalidate_cache: FOUND
- Commit 35689f4: FOUND (feat(05-03): cache-aside)
- Commit e892dbc: FOUND (feat(05-03): invalidation + tests)
- PAPER_TTL=3600: VERIFIED
- SEARCH_TTL=300: VERIFIED
- papers:{canonical_id}:{view} key format: VERIFIED
- search:{md5} key format: VERIFIED
- SCAN cursor loop (not KEYS): VERIFIED
- Sync redis in Celery, async in API: VERIFIED
