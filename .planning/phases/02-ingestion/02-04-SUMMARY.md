---
phase: 02-ingestion
plan: 04
subsystem: ingestion
tags: [arxiv, oai-pmh, cli, smoke-test, resumability, crawl-state, celery, redis]

# Dependency graph
requires:
  - phase: 02-02
    provides: harvest_all_arxiv, harvest_arxiv_set — arXiv OAI-PMH harvester
  - phase: 02-03
    provides: harvest_pmc — PMC OAI-PMH harvester with token checkpointing

provides:
  - app/crawler/run_harvest.py: CLI entry point with --source, --max-records, --from-date, --status flags
  - show_status(): live DB + crawl_state introspection
  - Human-verified end-to-end harvest: 105,300 arXiv cs:LG papers ingested, resumption token confirmed working

affects: [03-parser-layer, 04-normalizer]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - import app.celery_app at module top of run_harvest.py to force broker initialization before any task imports
    - CLI dispatches to async harvest_all_arxiv via asyncio.run() and sync harvest_pmc directly
    - --status queries papers, paper_sources, and crawl_state via SQLAlchemy 2.x select() / scalar_one()

key-files:
  created:
    - app/crawler/run_harvest.py
  modified:
    - tests/test_ingest.py

key-decisions:
  - "Added `import app.celery_app` to run_harvest.py to fix Celery broker ImportError — lazy task imports fail when broker is not initialized at module load"
  - "UNIQUE constraint on crawl_state.source applied via Alembic migration 0002 — prevents duplicate state rows on concurrent harvest restarts"
  - "Full arXiv harvest run against 2024-01-01 cutoff resulted in 105,300 cs:LG papers (far exceeds the ~10,000 corpus target)"

patterns-established:
  - "run_harvest.py pattern: import broker at top, lazy-import crawler modules inside run_* functions to avoid circular imports"

requirements-completed: [INGEST-04, INGEST-06]

# Metrics
duration: ~2h (including full 105k arXiv harvest run time)
completed: 2026-04-15
---

# Phase 02 Plan 04: CLI Harvest Runner + Smoke Test Summary

**CLI harvest runner with --source/--status flags verified end-to-end: 105,300 arXiv cs:LG papers ingested since 2024-01-01, resumption token correctly restored on restart (no re-fetching), 24/24 unit tests passing**

## Performance

- **Duration:** ~2h (dominated by live 105k-paper arXiv OAI-PMH harvest)
- **Started:** 2026-04-15 (continuation of phase 02)
- **Completed:** 2026-04-15
- **Tasks:** 2 (1 auto + 1 human-verify checkpoint)
- **Files modified:** 2

## Accomplishments

- `app/crawler/run_harvest.py` (151 lines) — CLI runner with argparse: `--source arxiv|pmc|all`, `--max-records` (default 10000), `--from-date` (default 2020-01-01), `--status`
- `show_status()` queries and prints total papers, arxiv/pmc source counts, pending parse count, and all crawl_state rows (source, record_count, token present/absent, last_harvested_at)
- Live smoke test results: 105,300 arXiv cs:LG papers ingested, 105,300 paper_sources with parse_status='pending'
- Resumability verified: second run correctly resumed from saved resumption token rather than re-fetching from the beginning
- UNIQUE constraint on crawl_state.source applied via migration 0002, preventing duplicate state rows
- Celery broker initialization fixed: `import app.celery_app` added to run_harvest.py top-level

## Task Commits

1. **Task 1: CLI harvest runner and integration test** - `4f6487d` (feat)
2. **Task 2: Human verify — end-to-end smoke test** - (approved, no separate commit)

## Files Created/Modified

- `app/crawler/run_harvest.py` — CLI entry point: main(), show_status(), run_arxiv(), run_pmc(); 151 lines
- `tests/test_ingest.py` — Added integration test marker registration in conftest.py and `test_harvest_runner_status` marked with `@pytest.mark.integration`

## Decisions Made

- Added `import app.celery_app` as a top-level import in run_harvest.py to force broker initialization before any task module is imported — without this, the Celery app isn't registered and Redis broker raises ImportError on task dispatch
- UNIQUE constraint migration (0002) was already planned in the phase and confirmed applied cleanly via `alembic upgrade head`
- Full harvest result (105,300 papers) vastly exceeds the ~10,000 corpus target — Phase 3 can begin immediately with a rich corpus

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added `import app.celery_app` to resolve Celery broker ImportError**
- **Found during:** Task 2 (smoke test execution in Docker)
- **Issue:** Running `python -m app.crawler.run_harvest` failed with an ImportError because the Celery app and Redis broker were not initialized before the crawler task imports fired
- **Fix:** Added `import app.celery_app  # noqa: F401` at module top of run_harvest.py with explanatory comment
- **Files modified:** app/crawler/run_harvest.py
- **Verification:** `python -m app.crawler.run_harvest --status` ran without error; 105,300-paper harvest completed
- **Committed in:** 4f6487d (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 3 - blocking import error)
**Impact on plan:** Required for the CLI to be runnable at all. No scope change.

## Issues Encountered

- Celery broker not initialized on CLI entry — resolved via top-level `import app.celery_app` (see Deviations above)
- Corpus scale: 105,300 papers harvested for cs:LG alone since 2024-01-01 (well above the 10,000 target). Phase 3 has ample data to work with.

## User Setup Required

None — no external service configuration required beyond what was already set up in Phase 1 (Docker Compose services).

## Next Phase Readiness

- Full ingestion pipeline verified end-to-end: arXiv OAI-PMH, asset downloader, PMC OAI-PMH, crawl state persistence, dedup, CLI runner
- 105,300 papers with parse_status='pending' in paper_sources — ready for Phase 3 parser tasks
- Celery broker (Redis) confirmed working with live harvest tasks
- No blockers for Phase 3 (Parser Layer)

---
*Phase: 02-ingestion*
*Completed: 2026-04-15*

## Self-Check: PASSED

- FOUND: app/crawler/run_harvest.py (151 lines, >= 30 line requirement met)
- FOUND commit: 4f6487d (feat - CLI harvest runner)
- FOUND: .planning/phases/02-ingestion/02-04-SUMMARY.md
- Smoke test results confirmed by user: 24/24 unit tests passed, 105,300 papers ingested, resumption token working
