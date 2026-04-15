---
phase: 03-parser-layer
plan: 01
subsystem: parsing
tags: [s2orc-doc2json, tralics, latexpand, pymupdf, celery, tex2json, latex, fixtures]

# Dependency graph
requires:
  - phase: 02-ingestion
    provides: PaperSource with asset_path and source_type; Paper with arxiv_id
provides:
  - app/tasks/parse_helpers.py with 5 shared helpers consumed by plans 03-02, 03-03, 03-04
  - parse_latex Celery task with D-01/D-02/D-03/D-04 routing logic
  - Wave 0 test infrastructure: 10 test stubs + 3 fixtures in tests/fixtures/
  - Dockerfile system deps: tralics, texlive-extra-utils, git
  - pyproject.toml: s2orc-doc2json pinned SHA, PyMuPDF>=1.27.0
affects: [03-02-jats-parser, 03-03-mineru, 03-04-router, 04-normalizer-storage]

# Tech tracking
tech-stack:
  added:
    - s2orc-doc2json @ git+https://github.com/allenai/s2orc-doc2json@71c022ed4bed3ffc71d22c2ac5cdbc133ad04e3c
    - PyMuPDF>=1.27.0
    - tralics (system package via apt-get)
    - texlive-extra-utils / latexpand (system package via apt-get)
  patterns:
    - Lazy import of doc2json inside task function body (avoids import error at module load time)
    - Shared helpers module (parse_helpers.py) consumed by multiple task modules
    - D-01/D-02 tex file detection: arXiv ID filename stem match first, then largest-with-documentclass
    - D-03 table-count routing: pymupdf find_tables() heuristic, <=3 -> GROBID, >3 -> MinerU
    - D-04 cascade: TEX2JSON failure -> MinerU if PDF exists, else failed
    - Wave 0 stub pattern: integration tests raise pytest.skip, unit tests have real assertions

key-files:
  created:
    - app/tasks/parse_helpers.py
    - tests/test_parse.py
    - tests/fixtures/sample_arxiv.tar.gz
    - tests/fixtures/sample_pmc.xml
    - tests/fixtures/sample_scanned.pdf
  modified:
    - app/tasks/parse.py
    - Dockerfile
    - pyproject.toml

key-decisions:
  - "parse_helpers.py is a shared module -- all parse tasks import from it, not inline"
  - "D-01 arXiv ID stem match strips version suffix (2401.12345v2 -> 2401.12345) before comparing"
  - "D-03 pymupdf find_tables() threshold: <=3 -> pdf_grobid, >3 -> pdf_mineru (per RESEARCH.md)"
  - "process_tex_stream import is lazy (inside task body) to avoid ImportError at worker startup"
  - "PyMuPDF added now (not 03-03) because D-03 PDF table heuristic is needed by parse_latex"

patterns-established:
  - "Pattern: Shared parse helpers in app/tasks/parse_helpers.py, not inline in each task"
  - "Pattern: Wave 0 stub tests -- integration tests skip, unit helper tests have real assertions"
  - "Pattern: Lazy import of heavy parser libs inside task function body"

requirements-completed: [PARSE-01]

# Metrics
duration: 3min
completed: 2026-04-15
---

# Phase 3 Plan 1: TEX2JSON Parser + Wave 0 Test Infrastructure Summary

**parse_latex Celery task with arXiv ID filename detection (D-01), documentclass fallback (D-02), PDF table-count routing (D-03), TEX2JSON failure cascade (D-04), and shared parse_helpers.py module consumed by all Phase 3 plans**

## Performance

- **Duration:** 3 min
- **Started:** 2026-04-15T19:21:57Z
- **Completed:** 2026-04-15T19:24:54Z
- **Tasks:** 3 (Task 0, Task 1, Task 2)
- **Files modified:** 7

## Accomplishments
- Created app/tasks/parse_helpers.py with 5 shared helpers (_backslash_ratio_degraded, _strip_jats_doctype, _has_text_layer, _sentence_length_degraded, _count_pdf_tables)
- Implemented parse_latex with full D-01 through D-04 routing logic and quality check
- Updated Dockerfile with tralics, texlive-extra-utils, git system deps before pip install
- Added s2orc-doc2json pinned to SHA 71c022ed and PyMuPDF>=1.27.0 to pyproject.toml
- Created Wave 0 test scaffold: 10 test stubs in test_parse.py + 3 fixture files

## Task Commits

Each task was committed atomically:

1. **Task 0: Wave 0 test infrastructure** - `968af0d` (feat)
2. **Task 1: Dockerfile + pyproject.toml** - `39e8f6b` (chore)
3. **Task 2: parse_helpers.py + parse_latex** - `8389b13` (feat)

**Plan metadata:** (docs commit below)

## Files Created/Modified
- `app/tasks/parse_helpers.py` - 5 shared helpers for all Phase 3 parse tasks
- `app/tasks/parse.py` - parse_latex fully implemented; jats/mineru/grobid stubs unchanged
- `Dockerfile` - System deps tralics + texlive-extra-utils + git installed before pip
- `pyproject.toml` - s2orc-doc2json SHA-pinned + PyMuPDF>=1.27.0 + gpu pytest marker
- `tests/test_parse.py` - 10 test stubs (3 unit tests real, 6 integration skipped, 1 GPU skipped)
- `tests/fixtures/sample_arxiv.tar.gz` - Minimal LaTeX paper archive (main.tex with documentclass)
- `tests/fixtures/sample_pmc.xml` - JATS XML with NLM DTD
- `tests/fixtures/sample_scanned.pdf` - Image-only PDF with no text layer

## Decisions Made
- parse_helpers.py is a shared module consumed by all Phase 3 tasks, not inline helpers
- D-01 arXiv ID stem matching strips version suffix before filename comparison
- PyMuPDF added in 03-01 (not 03-03) because D-03 needs _count_pdf_tables in parse_latex
- process_tex_stream lazily imported inside task body to prevent ImportError at worker startup
- Wave 0 unit tests (backslash check, DOCTYPE strip, sentence length) have real assertions now

## Deviations from Plan

### Auto-included Items

**1. [Rule 2 - Missing Critical] parse_helpers.py created in Task 0 alongside test stubs**
- **Found during:** Task 0 (Wave 0 test infrastructure)
- **Issue:** Tests import from app.tasks.parse_helpers; module needed to exist for pytest collection to succeed
- **Fix:** Created parse_helpers.py with full implementation during Task 0 (before Task 2 TDD step)
- **Files modified:** app/tasks/parse_helpers.py
- **Verification:** pytest --co succeeds, all 9 non-GPU tests collect without ImportError
- **Committed in:** 968af0d (Task 0 commit)

---

**Total deviations:** 1 (parse_helpers.py created early in Task 0 rather than Task 2, same result)
**Impact on plan:** No scope creep. Module created earlier than planned to unblock test collection.

## Issues Encountered
None -- all tasks executed as planned without blocking issues.

## Known Stubs
- `tests/test_parse.py`: test_parse_latex_returns_s2orc, test_parse_jats_returns_s2orc, test_grobid_references, test_router_dispatch raise pytest.skip (integration tests, require installed parsers)
- `tests/test_parse.py`: test_scanned_pdf_detection, test_count_pdf_tables raise pytest.skip (require specific PDF fixtures with known content)
- `app/tasks/parse.py`: parse_jats, parse_pdf_mineru, parse_pdf_grobid return stub dicts (implemented in 03-02, 03-03, 03-04)

These stubs are intentional Wave 0 scaffolding. Integration tests will be activated as subsequent plans implement the parsers.

## Next Phase Readiness
- parse_helpers.py ready for import by 03-02 (parse_jats) and 03-03 (parse_pdf_mineru)
- tests/fixtures/ ready for activation in subsequent plans
- parse_latex task is fully implemented and routable via fast queue
- Plans 03-02, 03-03, 03-04 can proceed in any order

---
*Phase: 03-parser-layer*
*Completed: 2026-04-15*
