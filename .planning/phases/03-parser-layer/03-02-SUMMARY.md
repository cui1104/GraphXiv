---
phase: 03-parser-layer
plan: 02
subsystem: parser
tags: [celery, jats2json, s2orc-doc2json, lxml, pmc, xml]

requires:
  - phase: 03-01
    provides: parse_helpers.py with _strip_jats_doctype, _backslash_ratio_degraded, parse.py with parse_latex

provides:
  - parse_jats Celery task with full JATS2JSON implementation via process_jats_stream
  - DOCTYPE stripping (Pitfall 6) using _strip_jats_doctype from parse_helpers
  - D-04 cascade logic: JATS2JSON failure cascades to PDF parser if asset exists
  - test_strip_doctype_with_internal_subset unit test for DOTALL regex coverage

affects: [03-03, 03-04, 04-normalizer-storage]

tech-stack:
  added: []
  patterns:
    - "Lazy import of process_jats_stream inside task body prevents ImportError at worker startup"
    - "DOCTYPE stripped via shared helper _strip_jats_doctype before passing bytes to lxml-based parser"
    - "D-04 cascade: failed JATS parse cascades to cascade_to_pdf status; next router task dispatches PDF parser"

key-files:
  created: []
  modified:
    - app/tasks/parse.py
    - tests/test_parse.py

key-decisions:
  - "Lazy import of process_jats_stream (from doc2json.jats2json.process_jats) inside parse_jats function body prevents ImportError at worker startup when s2orc-doc2json is unavailable"
  - "DOCTYPE stripping applied from parse_helpers._strip_jats_doctype (not redefined locally) -- shared helper established in 03-01"
  - "D-04 cascade: queries for pmc_pdf/arxiv_pdf/pdf source types when JATS2JSON returns empty result"

patterns-established:
  - "Pattern: all Phase 3 tasks follow same session/try/finally/retry structure as parse_latex"
  - "Pattern: parse_status cascades (cascade_to_pdf) decouple parser routing from direct task dispatch"

requirements-completed: [PARSE-02]

duration: 5min
completed: 2026-04-15
---

# Phase 3 Plan 02: parse_jats Task Summary

**parse_jats Celery task implemented using s2orc-doc2json JATS2JSON (process_jats_stream) with mandatory DOCTYPE stripping via shared helper to prevent lxml DTD fetch hangs**

## Performance

- **Duration:** 5 min
- **Started:** 2026-04-15T00:00:00Z
- **Completed:** 2026-04-15T00:05:00Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments

- Replaced parse_jats stub with full implementation calling process_jats_stream from s2orc-doc2json
- DOCTYPE stripping via _strip_jats_doctype from parse_helpers prevents lxml external DTD fetch hangs (Pitfall 6)
- D-04 cascade logic implemented: JATS2JSON empty result cascades to PDF if asset exists (cascade_to_pdf status)
- DB correctly updated: paper.parse_source="jats", paper.parse_quality="ok", ps.parse_status="success"
- Temp directory cleaned up in finally block via shutil.rmtree
- Added test_strip_doctype_with_internal_subset verifying DOTALL regex handles NLM internal subset [...] DocTypes

## Task Commits

1. **Task 1: Implement parse_jats Celery task with DOCTYPE stripping and JATS2JSON** - `1992fba` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `app/tasks/parse.py` - parse_jats stub replaced with full JATS2JSON implementation; parse_latex and PDF stubs unchanged
- `tests/test_parse.py` - Added test_strip_doctype_with_internal_subset for DOTALL internal subset coverage

## Decisions Made

- Lazy import of process_jats_stream inside task body (not at module top) to prevent ImportError at worker startup when library unavailable -- consistent with parse_latex pattern established in 03-01
- _strip_jats_doctype imported from app.tasks.parse_helpers (already in import block from 03-01), not redefined locally
- D-04 cascade queries pmc_pdf, arxiv_pdf, and pdf source_types to maximize fallback coverage

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- parse_jats task is complete and ready for Phase 3 integration (03-03 MinerU, 03-04 router)
- Router (03-04) can dispatch parse_jats for PMC papers with pmc_jats or pmc source_type assets
- cascade_to_pdf status will trigger PDF parser dispatch in the routing task

---
*Phase: 03-parser-layer*
*Completed: 2026-04-15*
