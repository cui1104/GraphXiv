---
phase: 02-ingestion
plan: 03
subsystem: ingestion
tags: [pmc, oai-pmh, sickle, crawler, deep-learning, keyword-filter, resumption-token, checkpointing]

# Dependency graph
requires:
  - phase: 02-01
    provides: save_crawl_state, load_crawl_state, is_already_ingested, PMC_OAI_BASE, mock_db_session fixture

provides:
  - app/crawler/pmc_oai.py: PMC OAI-PMH harvester using sickle with token checkpointing
  - harvest_pmc(from_date, max_records) -> int: main entry point for PMC ingestion
  - harvest_pmc_ids(from_date, max_records) -> list[str]: Phase 1 ID harvest
  - process_pmc_record(session, pmc_id, title, abstract) -> bool: Phase 2 filter + insert
  - 6 PMC unit tests covering ID extraction, DL keyword filter, insert path, constants

affects: [02-04, 03-parser-layer, 04-normalizer]

# Tech tracking
tech-stack:
  added: [sickle==0.7.0]
  patterns:
    - Two-phase OAI harvest (fast ID collection then filter/insert) to avoid token expiry during slow processing
    - pmc_fm metadataPrefix for front-matter-only harvest (faster than full pmc XML)
    - ResumptionToken checkpointed via save_crawl_state after every 10-record page boundary
    - pg_insert().on_conflict_do_nothing(index_elements=["pmc_id"]) for safe upsert
    - DL keyword regex filter (re.IGNORECASE) on title+abstract before DB insert

key-files:
  created:
    - app/crawler/pmc_oai.py
  modified:
    - tests/test_ingest.py

key-decisions:
  - "Use pmc_fm metadataPrefix (front matter only) instead of full pmc JATS XML for the harvest phase — much faster, avoids token timeout"
  - "parse_status lives on PaperSource, not Paper — PaperSource inserted with parse_status=pending"
  - "DL keyword filter uses re.IGNORECASE regex covering 13 key terms: deep learning, neural network, transformer, convolutional, recurrent neural, attention mechanism, generative adversarial, reinforcement learning, language model, BERT, GPT, diffusion model, graph neural"
  - "harvest_pmc and harvest_pmc_ids both use load_crawl_state to support checkpoint-resume; token saved after every 10 records"

patterns-established:
  - "PMC OAI-PMH page = 10 records; checkpoint token at count % 10 == 0"
  - "Two-phase crawler pattern: bulk ID collection then per-record filter+insert"

requirements-completed: [INGEST-03, INGEST-04]

# Metrics
duration: 2min
completed: 2026-04-15
---

# Phase 02 Plan 03: PMC OAI-PMH Crawler Summary

**PMC OAI-PMH harvester using sickle with resumptionToken checkpointing after every 10-record page, DL keyword filter on title/abstract, and pg_insert dedup — 265-line module + 6 unit tests all passing**

## Performance

- **Duration:** 2 min
- **Started:** 2026-04-15T17:28:03Z
- **Completed:** 2026-04-15T17:29:57Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- PMC OAI-PMH harvester (`app/crawler/pmc_oai.py`) with sickle, using `pmc_fm` metadataPrefix for fast front-matter-only harvest
- ResumptionToken persisted via `save_crawl_state` after every page boundary (10 records), enabling crash-safe resume
- DL keyword regex filter (`DL_KEYWORDS`) applied before DB insert — only biomedical deep learning papers ingested
- `pg_insert().on_conflict_do_nothing(index_elements=["pmc_id"])` prevents duplicate Paper rows on re-run
- 6 new unit tests covering ID extraction, keyword filter (positive + negative), insert path via mocked `pg_insert`, skip logic for non-DL papers, and PMC URL constant

## Task Commits

1. **Task 1: PMC OAI-PMH harvester with sickle** - `a406714` (feat)
2. **Task 2: PMC crawler tests** - `30947c3` (test)

## Files Created/Modified

- `app/crawler/pmc_oai.py` - PMC OAI-PMH harvester: harvest_pmc, harvest_pmc_ids, process_pmc_record, _extract_pmc_id, _is_dl_paper
- `tests/test_ingest.py` - Added 6 PMC-specific tests (test_extract_pmc_id, test_is_dl_paper_positive, test_is_dl_paper_negative, test_process_pmc_record_inserts, test_process_pmc_record_skips_non_dl, test_pmc_constants)

## Decisions Made

- Used `pmc_fm` metadataPrefix (front-matter only) rather than full `pmc` JATS XML for the harvest — significantly faster and avoids OAI token expiry during slow iteration
- `parse_status` is tracked on `PaperSource` (not on `Paper`) — PaperSource inserted with `parse_status="pending"` per the existing schema
- DL keyword regex uses `re.IGNORECASE` and covers 13 key terms to ensure broad capture of the biomedical deep learning literature

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed duplicate paper_stmt assignment**
- **Found during:** Task 1 (code review before commit)
- **Issue:** Initial draft had two sequential `paper_stmt = pg_insert(Paper).values(...)` assignments (one with a dead `parse_status` kwarg that doesn't exist on Paper), causing the first to be silently discarded
- **Fix:** Removed the dead first assignment and its comment; kept the correct single statement
- **Files modified:** app/crawler/pmc_oai.py
- **Verification:** Import check passed; `process_pmc_record` logic verified
- **Committed in:** a406714 (Task 1 commit)

**2. [Rule 1 - Bug] Removed dead walrus-operator placeholder in harvest_pmc**
- **Found during:** Task 1 (code review before commit)
- **Issue:** `if resumption_token := None:` was a leftover dead-code stub with no effect
- **Fix:** Removed the dead block entirely; the real `resumption_token` assignment follows immediately via `load_crawl_state`
- **Files modified:** app/crawler/pmc_oai.py
- **Verification:** Import check passed
- **Committed in:** a406714 (Task 1 commit, cleaned up before final commit)

---

**Total deviations:** 2 auto-fixed (2 Rule 1 bugs — dead code removed)
**Impact on plan:** Both fixes were cleanup of draft artifacts. No scope change.

## Issues Encountered

- `sickle` was already present in `pyproject.toml` (`sickle==0.7.0`) but not installed in the system Python. Installed via `pip3 install sickle --break-system-packages` for local verification; Docker environment already has the dependency declared.

## Next Phase Readiness

- `harvest_pmc` is importable and wired into the `ingest_paper` Celery task (source='pmc' branch set up in 02-02)
- PMC crawler ready for 02-04 or any integration test that exercises the full ingestion pipeline
- No blockers for Phase 03 parser layer

---
*Phase: 02-ingestion*
*Completed: 2026-04-15*

## Self-Check: PASSED

- FOUND: app/crawler/pmc_oai.py
- FOUND: tests/test_ingest.py
- FOUND: .planning/phases/02-ingestion/02-03-SUMMARY.md
- FOUND commit: a406714 (feat - PMC harvester)
- FOUND commit: 30947c3 (test - PMC tests)
- All 6 PMC tests pass
