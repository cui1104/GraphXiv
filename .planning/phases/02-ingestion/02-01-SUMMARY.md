---
phase: 02-ingestion
plan: 01
subsystem: ingestion
tags: [crawler, arxiv, pmc, alembic, sqlalchemy, httpx, tenacity, aiolimiter, sickle, lxml, pytest]

# Dependency graph
requires:
  - phase: 01-foundation
    provides: "CrawlState, Paper, PaperSource SQLAlchemy models; alembic migration 0001"

provides:
  - "Alembic migration 0002 adding UNIQUE constraint on crawl_state.source (uq_crawl_state_source)"
  - "app/crawler/utils.py with normalize_arxiv_id, save_crawl_state, load_crawl_state, is_already_ingested"
  - "ARXIV_OAI_BASE, ARXIV_SETS, CONTENT_TYPE_TO_EXT constants"
  - "mock_db_session pytest fixture (SQLite in-memory)"
  - "tests/test_ingest.py with 9 passing unit tests"

affects:
  - 02-02-arxiv-crawler
  - 02-03-pmc-crawler
  - 02-04-celery-enqueue

# Tech tracking
tech-stack:
  added:
    - "httpx==0.28.1 (async HTTP client)"
    - "tenacity==9.1.4 (retry with backoff)"
    - "aiolimiter==1.2.1 (async token-bucket rate limiter)"
    - "sickle==0.7.0 (OAI-PMH client)"
    - "lxml==6.0.4 (XML parsing)"
    - "pytest-httpx (HTTP mocking in tests)"
  patterns:
    - "PostgreSQL pg_insert().on_conflict_do_update() for crawl_state upsert keyed on source"
    - "normalize_arxiv_id strips version suffix before storing in papers.arxiv_id"
    - "SQLite raw DDL fixture for unit tests that cannot use PostgreSQL-specific types"

key-files:
  created:
    - "alembic/versions/0002_crawl_state_unique_source.py"
    - "app/crawler/utils.py"
    - "tests/test_ingest.py"
  modified:
    - "app/models.py (UniqueConstraint on CrawlState)"
    - "pyproject.toml (5 new deps + pytest-httpx)"
    - "tests/conftest.py (mock_db_session fixture)"

key-decisions:
  - "mock_db_session uses raw SQL DDL (not Base.metadata.create_all) because Paper model contains JSONB/Vector types incompatible with SQLite"
  - "ARXIV_OAI_BASE is oaipmh.arxiv.org/oai (not export.arxiv.org/oai2) — new endpoint per March 2025 arXiv OAI migration"
  - "ARXIV_SETS uses colon-separated format cs:cs:LG per March 2025 arXiv set name change"

patterns-established:
  - "Pattern: crawl_state upsert via pg_insert().on_conflict_do_update(index_elements=['source'])"
  - "Pattern: arXiv ID normalization via regex stripping version suffix before DB insert"

requirements-completed: [INGEST-04, INGEST-05]

# Metrics
duration: 3min
completed: 2026-04-15
---

# Phase 02 Plan 01: Ingestion Bootstrap Summary

**Alembic UNIQUE constraint migration on crawl_state.source, shared crawler utilities (ID normalization, upsert, dedup) with 9 passing unit tests**

## Performance

- **Duration:** 3 min
- **Started:** 2026-04-15T17:23:06Z
- **Completed:** 2026-04-15T17:26:22Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments

- Added `0002_crawl_state_unique_source.py` migration enabling `ON CONFLICT DO UPDATE` upserts on `crawl_state` (prerequisite for all crawlers)
- Implemented `app/crawler/utils.py` with all 4 shared utilities: `normalize_arxiv_id`, `save_crawl_state`, `load_crawl_state`, `is_already_ingested`, plus all constants from RESEARCH.md
- Added 9 unit tests in `tests/test_ingest.py` covering ID normalization, content-type routing, dedup detection, and constant values — all passing

## Task Commits

Each task was committed atomically:

1. **Task 1: Alembic migration + dependencies + crawl_state model update** - `e305721` (chore)
2. **Task 2: Shared crawler utilities and test scaffold** - `17eed77` (feat)

**Plan metadata:** (docs commit below)

## Files Created/Modified

- `alembic/versions/0002_crawl_state_unique_source.py` — Alembic migration adding `uq_crawl_state_source` UNIQUE constraint on `crawl_state.source`
- `app/models.py` — Added `UniqueConstraint("source", name="uq_crawl_state_source")` to `CrawlState.__table_args__`
- `pyproject.toml` — Added httpx, tenacity, aiolimiter, sickle, lxml, pytest-httpx
- `app/crawler/__init__.py` — Module docstring
- `app/crawler/utils.py` — normalize_arxiv_id, save_crawl_state, load_crawl_state, is_already_ingested, ARXIV_OAI_BASE, ARXIV_SETS, CONTENT_TYPE_TO_EXT
- `tests/conftest.py` — Added mock_db_session fixture with raw SQLite DDL
- `tests/test_ingest.py` — 9 unit tests, all passing

## Decisions Made

- `mock_db_session` fixture uses raw SQL DDL instead of `Base.metadata.create_all` because the `Paper` model uses `JSONB` and `Vector(768)` which SQLite cannot compile. Raw DDL creates minimal SQLite-compatible tables with only the columns needed for unit tests.
- ARXIV_OAI_BASE uses the March 2025 new endpoint (`oaipmh.arxiv.org/oai`), not the deprecated `export.arxiv.org/oai2`.
- ARXIV_SETS uses colon-separated format per March 2025 arXiv set name migration.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] SQLite incompatibility with PostgreSQL JSONB/Vector types in mock_db_session**
- **Found during:** Task 2 (test execution)
- **Issue:** `Base.metadata.create_all` on SQLite failed with `UnsupportedCompilationError: can't render element of type JSONB` because `Paper` model uses PostgreSQL-specific column types
- **Fix:** Replaced `Base.metadata.create_all(engine)` in `mock_db_session` fixture with raw DDL creating minimal SQLite-compatible tables; updated `test_is_already_ingested_true` to use raw SQL insert instead of ORM Paper object
- **Files modified:** `tests/conftest.py`, `tests/test_ingest.py`
- **Verification:** All 9 tests pass
- **Committed in:** `17eed77` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug)
**Impact on plan:** Required to make unit tests work without a live PostgreSQL instance. No scope creep.

## Issues Encountered

None beyond the auto-fixed SQLite incompatibility above.

## User Setup Required

None — no external service configuration required. Tests run offline with SQLite in-memory.

## Next Phase Readiness

- All crawler utilities are importable and tested
- UNIQUE constraint migration ready to apply against live PostgreSQL (`alembic upgrade 0002`)
- `save_crawl_state` and `load_crawl_state` are ready for arXiv/PMC crawlers (02-02, 02-03)
- `normalize_arxiv_id` ready for arXiv OAI-PMH harvest loop
- `is_already_ingested` ready for dedup checks in both crawlers

## Self-Check: PASSED

- FOUND: alembic/versions/0002_crawl_state_unique_source.py
- FOUND: app/crawler/utils.py
- FOUND: tests/test_ingest.py
- FOUND: .planning/phases/02-ingestion/02-01-SUMMARY.md
- FOUND: commit e305721
- FOUND: commit 17eed77

---
*Phase: 02-ingestion*
*Completed: 2026-04-15*
