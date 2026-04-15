---
phase: 03-parser-layer
plan: 04
subsystem: api
tags: [grobid, httpx, lxml, tei-xml, celery, celery-group, celery-chain, parser, routing]

# Dependency graph
requires:
  - phase: 03-01
    provides: parse_latex task with D-03 internal cascade logic, _count_pdf_tables helper
  - phase: 03-02
    provides: parse_jats task
  - phase: 03-03
    provides: parse_pdf_mineru task

provides:
  - GROBID httpx client (app/parsers/grobid.py) posting to /api/processReferences and parsing TEI XML citations
  - parse_pdf_grobid Celery task implementing non-blocking citation enrichment (D-07) with D-03 cascade awareness
  - Smart router (app/tasks/router.py) dispatching correct parse chain by source_type priority
  - dispatch_pending_batch fanout for 10k-scale processing via celery.group
  - app/parsers/ package init

affects: [04-normalizer-storage, 05-rest-api]

# Tech tracking
tech-stack:
  added: [httpx, lxml (TEI XML parsing)]
  patterns:
    - "Celery .si() immutable signatures in chains to avoid large dict serialization through Redis"
    - "celery.group for batch fan-out of parse chains"
    - "Non-blocking GROBID via try/except returning [] on any failure (D-07)"
    - "app/parsers/ package for parser client modules"

key-files:
  created:
    - app/parsers/__init__.py
    - app/parsers/grobid.py
    - app/tasks/router.py
  modified:
    - app/tasks/parse.py
    - app/celery_app.py
    - tests/test_parse.py

key-decisions:
  - "GROBID non-blocking (D-07): extract_references returns [] on any exception -- never fails parse chain"
  - "parse_pdf_grobid sets parse_source=pdf_grobid only when ps.parse_status==cascade_to_pdf_grobid (D-03 cascade path is PRIMARY parser)"
  - "Router does NOT have D-03 branch -- parse_latex handles it internally by dispatching pdf_grobid/pdf_mineru directly"
  - "app/parsers/ package created for GROBID and future parser client modules"
  - "celery_app.py updated with app.tasks.router in include list and fast queue routing for router.*"

patterns-established:
  - "Parser client modules live in app/parsers/ (not inlined in tasks)"
  - "All chain .si() calls use immutable signatures (Pitfall 7)"
  - "dispatch_pending_batch is the batch entry point for the full 10k corpus"

requirements-completed: [PARSE-04, PARSE-05]

# Metrics
duration: 2min
completed: 2026-04-15
---

# Phase 03 Plan 04: GROBID Client + Smart Parser Router Summary

**GROBID httpx client posting to /api/processReferences with TEI XML parser, non-blocking parse_pdf_grobid task, and smart router dispatching correct Celery chains by source_type priority with celery.group batch fan-out**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-04-15T19:32:21Z
- **Completed:** 2026-04-15T19:34:25Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments

- Created `app/parsers/grobid.py` with full GROBID httpx client — posts PDF bytes to `/api/processReferences`, parses TEI XML biblStruct elements to extract title, authors, year, doi, raw_text
- Replaced `parse_pdf_grobid` stub with production implementation: non-blocking on failure (stores `citations=[]` on error), D-03 aware (sets `parse_source="pdf_grobid"` when `cascade_to_pdf_grobid` status), merges citations into `paper.content["grobid_citations"]`
- Created `app/tasks/router.py` with `_build_parse_chain` (source_type priority dispatch), `route_paper` (single paper routing), `dispatch_pending_batch` (celery.group fan-out for 10k corpus)
- All `.si()` immutable signatures used in chains (Pitfall 7 compliance)
- D-03 routing documented in router module: no router branch needed since parse_latex handles internally

## Task Commits

1. **Task 1: GROBID httpx client and parse_pdf_grobid task** - `7d442a1` (feat)
2. **Task 2: Smart router and batch dispatcher** - `25f4cd4` (feat)

## Files Created/Modified

- `app/parsers/__init__.py` — Empty package init for parser client modules
- `app/parsers/grobid.py` — GROBID httpx client with TEI XML parser; `extract_references()` and `_parse_tei_references()`
- `app/tasks/parse.py` — `parse_pdf_grobid` stub replaced with full non-blocking implementation
- `app/tasks/router.py` — Smart router with `_build_parse_chain`, `route_paper`, `dispatch_pending_batch`
- `app/celery_app.py` — Added `app.tasks.router` to include list and fast queue routing
- `tests/test_parse.py` — `test_grobid_references` and `test_router_dispatch` stubs replaced with real unit tests

## Decisions Made

- GROBID is non-blocking (D-07): `extract_references()` returns `[]` on any exception and never raises, ensuring GROBID failures don't break the parse chain
- `parse_pdf_grobid` sets `parse_source="pdf_grobid"` only when `ps.parse_status == "cascade_to_pdf_grobid"` — this distinguishes the D-03 cascade path (where GROBID is primary) from the enrichment path (where it's appended to a chain)
- D-03 branching is confirmed as internal to `parse_latex`, not needing a separate router branch — router always dispatches `parse_latex` for `arxiv_tar`/`arxiv` types
- `app/parsers/` package established as the location for all parser HTTP client modules

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None — all tests passed on first run.

## Next Phase Readiness

- Phase 03 parser layer is complete: parse_latex (03-01), parse_jats (03-02), parse_pdf_mineru (03-03), parse_pdf_grobid + router (03-04)
- Phase 04 Normalizer + Storage can now call `dispatch_pending_batch()` to trigger the full 10k parse pipeline
- GROBID citations stored in `paper.content["grobid_citations"]` — Phase 04 normalizer should extract these into `paper_citations` table

---
*Phase: 03-parser-layer*
*Completed: 2026-04-15*
