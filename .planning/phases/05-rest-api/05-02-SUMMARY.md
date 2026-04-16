---
phase: 05-rest-api
plan: 02
subsystem: api
tags: [fastapi, sqlalchemy, pgvector, bm25, sentence-transformers, citations, hybrid-search]

# Dependency graph
requires:
  - phase: 05-rest-api/05-01
    provides: FastAPI app factory, Pydantic schemas, stub route handlers
  - phase: 04-normalizer-storage
    provides: Paper ORM with JSONB content, normalize_paper task
  - phase: 01-foundation
    provides: SQLAlchemy models (Paper, IdMap, PaperCitation), db.py SessionLocal
provides:
  - All 7 arXiv endpoints implemented: head, brief, sections, full, references, cited_by, related
  - All 2 PMC endpoints implemented: head, full
  - Search endpoint with BM25/vector/hybrid modes (graceful embedding fallback)
  - arXiv ID version stripping (strip_arxiv_version) on all lookups
  - 404 handling returning {error: not_found, message: ...} JSON
  - _write_embedding() in normalize.py — stores sentence-transformer vec after normalize_paper
  - Real test suite (9 non-integration tests passing, mock DB via dependency_overrides)
affects:
  - app/api/routes/arxiv.py
  - app/api/routes/pmc.py
  - app/api/routes/search.py
  - app/tasks/normalize.py
  - tests/test_api.py

# Tech stack
added: []
patterns:
  - sync def route handlers with FastAPI threadpool (Pitfall 5)
  - id_map fallback lookup for both arxiv_id and pmc_id resolution
  - LEFT JOIN for out-of-corpus references (in_corpus = canonical_id IS NOT NULL)
  - Co-citation query for related papers ranked by COUNT(*) DESC
  - Hybrid search: BM25 ts_rank + pgvector cosine with COALESCE 50/50 blend
  - content->'authors' JSONB operator in all search queries
  - Module-level _EMBEDDING_MODEL dict cache to avoid per-task model reload
  - dependency_overrides[get_db] pattern for mock-DB unit tests

# Key files
created: []
modified:
  - app/api/routes/arxiv.py
  - app/api/routes/pmc.py
  - app/api/routes/search.py
  - app/tasks/normalize.py
  - tests/test_api.py

# Decisions
decisions:
  - "Import _paper_to_head from arxiv.py into pmc.py (shared helper, single source of truth)"
  - "Search BM25 mode uses plainto_tsquery (not to_tsquery) — handles multi-word queries safely"
  - "Graceful embedding fallback logs warning but never fails — BM25 always available"
  - "test_404 uses dependency_overrides returning None from all filter().first() calls"
  - "vec_str built as [v1,v2,...] string — avoids psycopg2 array binding issues with pgvector CAST"

# Metrics
duration: 10min
completed: "2026-04-16T01:31:58Z"
tasks_completed: 2
files_modified: 5
---

# Phase 05 Plan 02: API Endpoint Implementations Summary

**One-liner:** Replaced 501 stubs with real DB query handlers for all 10 endpoints — arXiv ID resolution with version stripping, citation graph queries, hybrid BM25/pgvector search, and sentence-transformer embedding writes during normalization.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | arXiv + PMC route handlers with ID resolution and 404 | ed55884 | app/api/routes/arxiv.py, app/api/routes/pmc.py |
| 2 | Search endpoint + embedding model + tests | d645190 | app/api/routes/search.py, app/tasks/normalize.py, tests/test_api.py |

## What Was Built

### Task 1: arXiv + PMC Route Handlers

**app/api/routes/arxiv.py** — All 7 arXiv endpoints implemented:

- `strip_arxiv_version()` strips `v\d+` suffix from arXiv IDs via regex
- `resolve_arxiv_id()` checks `papers.arxiv_id` first, falls back to `id_map.arxiv_id` → `canonical_id` lookup
- `_paper_to_head()` extracts HeadResponse fields from Paper ORM + content JSONB (authors from content)
- `src_url` always re-derived from `paper.arxiv_id`/`paper.pmc_id` columns (not from stored content field)
- `/head`, `/brief` return HeadResponse; `/sections` returns SectionsResponse; `/full` adds sections+citations+ref_entries+back_matter
- `/references`: LEFT JOIN paper_citations with papers — `in_corpus = canonical_id IS NOT NULL`
- `/cited_by`: JOIN from paper_citations where `target_paper_id = :cid`
- `/related`: Co-citation subquery joining paper_citations twice, grouped by canonical_id, ordered by COUNT(*) DESC, LIMIT param

**app/api/routes/pmc.py** — 2 PMC endpoints:

- `resolve_pmc_id()` checks `papers.pmc_id`, falls back to `id_map.pmc_id` lookup
- Imports `_paper_to_head` from arxiv.py (shared helper, not duplicated)
- `/head` and `/full` follow same pattern as arXiv equivalents

**404 handling:** All routes return `JSONResponse(status_code=404, content={"error": "not_found", "message": f"Paper {id} not found"})` when paper is None.

### Task 2: Search + Embedding Writes + Tests

**app/api/routes/search.py** — 3 search modes:

- **BM25**: `ts_rank(to_tsvector(...), plainto_tsquery(...))` with ORDER BY score DESC
- **Vector**: `1 - (embeddings <=> CAST(:vec AS vector))` — cosine similarity on stored embeddings
- **Hybrid**: CTE combining BM25 and vector scores with `COALESCE * 0.5 + COALESCE * 0.5` blend
- All three queries select `content->'authors' AS authors_json` for author extraction
- Embedding model lazy-loaded from `request.app.state` on first vector/hybrid call
- Fallback: if no embeddings exist in DB, hybrid/vector silently falls back to BM25 with a log warning

**app/tasks/normalize.py** — `_write_embedding()` added:

- Module-level `_EMBEDDING_MODEL: dict = {}` caches loaded model by name
- Called after `_upsert_paper()` before `session.commit()`
- Encodes `f"{title} {abstract}"` text; skips if empty
- Sets `paper.embeddings = vec` (list of floats for pgvector column)

**tests/test_api.py** — Real assertions replacing 501 stubs:

- `_make_mock_paper()` builds a MagicMock Paper with content JSONB
- `app.dependency_overrides[get_db] = override_get_db_with_paper(paper)` pattern
- `autouse` fixture clears overrides after each test
- Tests verify: 200 status, shape of response (keys present), 404 body `{error: not_found}`
- `test_arxiv_version_stripping` directly tests strip_arxiv_version() function
- Search test uses BM25 mode (db.execute().fetchall() returns []) — no embeddings needed

## Verification

```
pytest tests/test_api.py -x -q -m "not integration"
9 passed, 1 deselected in 0.20s
```

All 10 endpoint paths registered:
```
/arxiv/{arxiv_id}/head
/arxiv/{arxiv_id}/brief
/arxiv/{arxiv_id}/sections
/arxiv/{arxiv_id}/full
/arxiv/{arxiv_id}/references
/arxiv/{arxiv_id}/cited_by
/arxiv/{arxiv_id}/related
/pmc/{pmc_id}/head
/pmc/{pmc_id}/full
/arxiv/search
```

## Deviations from Plan

### Auto-fixed Issues

None — plan executed exactly as written.

Minor implementation note: vector search SQL builds `vec_str` as `[v1,v2,...] ` string instead of relying on psycopg2 list binding, to ensure pgvector receives the correct `CAST(:vec AS vector)` input. This follows standard pgvector SQLAlchemy usage and is consistent with the plan's intent.

## Known Stubs

None — all endpoints return real data from DB queries. Authors populated from content JSONB. Embedding writes active during normalization.

## Self-Check: PASSED

All 5 modified files exist on disk. Both commits (ed55884, d645190) confirmed in git log.
