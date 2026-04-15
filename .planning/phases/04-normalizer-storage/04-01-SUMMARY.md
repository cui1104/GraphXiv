---
phase: 04-normalizer-storage
plan: 01
subsystem: testing, database, infra, parsing
tags: [tiktoken, grobid, tei-xml, alembic, pytest, celery]

# Dependency graph
requires:
  - phase: 03-parser-layer
    provides: "GROBID extract_references, parse_pdf_grobid task with D-03 cascade logic"
provides:
  - "12 test stubs for NORM-01 through NORM-06 in tests/test_normalize.py"
  - "UNIQUE constraint migration on paper_citations(source_paper_id, target_arxiv_id)"
  - "tiktoken>=0.7.0 dependency added; cl100k_base pre-cached in Docker"
  - "GROBID extract_fulltext() for processFulltextDocument with TEI XML section parsing"
  - "parse_pdf_grobid primary mode: calls extract_fulltext, stores grobid_sections + grobid_citations"
affects:
  - "04-02 (normalizer implementation uses _parse_tei_fulltext_sections, tests from this plan)"
  - "05-rest-api (paper_citations upsert uses new UNIQUE constraint)"

# Tech tracking
tech-stack:
  added:
    - "tiktoken>=0.7.0 (token counting with cl100k_base encoding)"
  patterns:
    - "GROBID dual-mode: extract_references (secondary) vs extract_fulltext (primary) -- same non-blocking D-07 pattern"
    - "Primary vs secondary mode detection via ps.parse_status == cascade_to_pdf_grobid"
    - "TEI XML section parsing: lxml etree, body//div, head, p itertext"

key-files:
  created:
    - "tests/test_normalize.py (12 test stubs, NORM-01 through NORM-06)"
    - "alembic/versions/0003_paper_citations_unique.py (UNIQUE constraint migration)"
  modified:
    - "app/parsers/grobid.py (added extract_fulltext, _parse_tei_fulltext_sections)"
    - "app/tasks/parse.py (parse_pdf_grobid primary vs secondary mode branching)"
    - "pyproject.toml (added tiktoken>=0.7.0)"
    - "Dockerfile (tiktoken cl100k_base pre-cache layer)"

key-decisions:
  - "tiktoken>=0.7.0 (not pinned to 0.12.0) for broad compatibility"
  - "extract_fulltext timeout=60 (vs 30 for extract_references) because fulltext processing is heavier"
  - "test stubs import from app.tasks.normalize using direct imports; fail with ImportError until Plan 04-02 implements the normalize functions -- this is expected and correct"

patterns-established:
  - "GROBID section dict shape: {heading, sec_num, text, paragraphs, token_count} -- NORM-05 contract"
  - "Non-blocking GROBID: extract_fulltext returns ([], []) on any exception -- D-07"
  - "primary mode sets ps.parse_status=success/failed based on sections; secondary mode always returns success"

requirements-completed: [NORM-01, NORM-05, NORM-06]

# Metrics
duration: 15min
completed: 2026-04-15
---

# Phase 4 Plan 01: Normalizer Infrastructure Summary

**GROBID extract_fulltext with TEI XML section parsing, parse_pdf_grobid primary/secondary mode branching, 12 test stubs for NORM-01 to NORM-06, UNIQUE migration on paper_citations, tiktoken pre-cached in Docker**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-04-15T21:00:00Z
- **Completed:** 2026-04-15T21:15:00Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- 12 test stubs created covering all NORM requirements; 10/12 fail with ImportError (normalizer not yet implemented), 2 integration stubs skip, 2 pure GROBID parser tests pass
- GROBID fulltext extraction: `extract_fulltext()` POSTs to `/api/processFulltextDocument`, parses TEI XML body into section dicts with NORM-05 shape via `_parse_tei_fulltext_sections()`
- `parse_pdf_grobid` now detects primary mode (`cascade_to_pdf_grobid`) and calls `extract_fulltext` for sections + citations; secondary mode preserves existing `extract_references` behavior
- Alembic migration `0003_paper_citations_unique.py` adds `ON CONFLICT (source_paper_id, target_arxiv_id)` support for Plan 04-02 upsert
- tiktoken added to pyproject.toml and pre-cached in Dockerfile to prevent first-run network download

## Task Commits

Each task was committed atomically:

1. **Task 1: Test scaffold + Alembic migration + tiktoken dependency** - `6cda027` (feat)
2. **Task 2: GROBID extract_fulltext + parse_pdf_grobid primary mode** - `bb01224` (feat)

**Plan metadata:** (docs commit below)

## Files Created/Modified
- `tests/test_normalize.py` - 12 test stubs for NORM-01 through NORM-06
- `alembic/versions/0003_paper_citations_unique.py` - UNIQUE constraint on paper_citations(source_paper_id, target_arxiv_id)
- `app/parsers/grobid.py` - Added extract_fulltext() and _parse_tei_fulltext_sections()
- `app/tasks/parse.py` - parse_pdf_grobid primary/secondary mode branching
- `pyproject.toml` - Added tiktoken>=0.7.0 dependency
- `Dockerfile` - Added tiktoken cl100k_base pre-cache layer

## Decisions Made
- tiktoken pinned to `>=0.7.0` not `>=0.12.0` for broader compatibility; cl100k_base encoding is stable across versions
- `extract_fulltext` uses `timeout=60` (double the 30s reference-only timeout) because processFulltextDocument processes entire document
- Test stubs do direct imports from `app.tasks.normalize` helpers — fail with ImportError until Plan 04-02 implements them; this is the expected state per the plan

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Known Stubs
- `app/tasks/normalize.py` still contains the Phase 3 stub (`normalize_paper` returns `{"status": "stub"}`). The helper functions `_normalize_s2orc`, `_normalize_mineru`, `_compute_token_count`, `_compute_tldr`, `_compute_dedup_fingerprint` do not exist yet — they are implemented in Plan 04-02. This is intentional; Plan 04-01 only provides the infrastructure (tests, migration, tiktoken, GROBID fulltext).

## Next Phase Readiness
- Plan 04-02 can immediately build on this: test stubs are runnable, GROBID fulltext parser is ready, migration is ready to apply
- tiktoken is in dependencies and pre-cached — token counting can be implemented without Docker network issues

---
*Phase: 04-normalizer-storage*
*Completed: 2026-04-15*
