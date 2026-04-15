---
phase: 04-normalizer-storage
plan: 02
subsystem: api
tags: [celery, tiktoken, postgresql, jsonb, sha256, s2orc, mineru, grobid, sqlalchemy]

# Dependency graph
requires:
  - phase: 04-01
    provides: "GROBID extract_fulltext, _parse_tei_fulltext_sections, parse_pdf_grobid primary mode, test stubs, tiktoken dependency, UNIQUE migration on paper_citations"
  - phase: 03-parser-layer
    provides: "parse_latex/parse_jats/parse_pdf_mineru/parse_pdf_grobid tasks; S2ORC/MinerU/GROBID output formats stored in paper.content JSONB"
provides:
  - "normalize_paper Celery task dispatching to S2ORC/MinerU/GROBID normalization branches"
  - "_normalize_s2orc: groups body_text paragraphs into sections, flattens authors, merges GROBID citations"
  - "_normalize_mineru: reconstructs sections from content_list title/text hierarchy with no-title fallback"
  - "_normalize_grobid_fulltext: passes grobid_sections directly, converts grobid_citations"
  - "_compute_token_count/_add_token_count: per-section + total tiktoken cl100k_base counting"
  - "_compute_tldr/_add_tldr: first 2-3 abstract sentences, always present (str or None)"
  - "_compute_dedup_fingerprint/_add_dedup_fingerprint: SHA-256 of normalized_title|last_name|year"
  - "_upsert_paper: pg INSERT ON CONFLICT DO UPDATE for paper row"
  - "_upsert_citations: upsert to paper_citations with id_map resolution"
  - "_check_dedup_and_link: cross-source dedup via JSONB fingerprint query + id_map insert"
  - "router.py: normalize_paper.si() appended to all three parser chains"
affects: [05-rest-api, 06-sdk-fork]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Reads actual_parse_source from DB (not router argument) to handle D-03 cascade staleness (Pitfall 1)"
    - "Pure helper functions (_compute_*) separate from in-place enrichment (_add_*) for testability"
    - "Lazy import of tiktoken inside function bodies prevents startup-time failure on worker"
    - "pg INSERT ON CONFLICT DO UPDATE for idempotent upserts"
    - "Skip citations without target_arxiv_id AND target_doi (no conflict key available)"

key-files:
  created: []
  modified:
    - app/tasks/normalize.py
    - app/tasks/router.py

key-decisions:
  - "_normalize_s2orc signature takes (raw, parse_quality=None) not (raw, paper) — matches existing test stubs from 04-01 which test without a paper object"
  - "Pure _compute_* helpers alongside in-place _add_* wrappers to satisfy both test interface and task interface"
  - "tiktoken installed locally with --break-system-packages for test environment; already in pyproject.toml from 04-01"

patterns-established:
  - "Pattern: Normalization branches read parse_source from paper.parse_source (DB), not from router argument"
  - "Pattern: All parser chains end with normalize_paper.si(paper_id, hint) as final step"

requirements-completed: [NORM-01, NORM-02, NORM-03, NORM-04, NORM-05, NORM-06]

# Metrics
duration: 15min
completed: 2026-04-15
---

# Phase 4 Plan 02: normalize_paper Implementation Summary

**Celery normalize_paper task with S2ORC/MinerU/GROBID normalization branches, tiktoken token counting, SHA-256 dedup fingerprinting, pg upsert, and citation edge insertion — wired as final step in all three parser chains**

## Performance

- **Duration:** 15 min
- **Started:** 2026-04-15T21:20:00Z
- **Completed:** 2026-04-15T21:35:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Complete normalize_paper Celery task with three normalization branches (S2ORC, MinerU, GROBID)
- Token counting per-section and total via tiktoken cl100k_base
- tldr always present (first 2-3 abstract sentences or None, never missing key)
- SHA-256 dedup fingerprint with cross-source matching via id_map
- PostgreSQL upsert with ON CONFLICT DO UPDATE for idempotent normalization
- Citation upsert with id_map resolution for target_paper_id
- normalize_paper.si() appended to all three router chains (arxiv, pmc, pdf)
- All 10 unit tests pass

## Task Commits

Each task was committed atomically:

1. **Task 1: Complete normalize_paper implementation** - `7491952` (feat)
2. **Task 2: Wire normalize_paper into router chains** - `52c5438` (feat)

**Plan metadata:** (docs commit below)

## Files Created/Modified
- `app/tasks/normalize.py` - Complete normalize_paper implementation (stub replaced, 735 lines added)
- `app/tasks/router.py` - Three chains updated with normalize_paper.si() as final step

## Decisions Made
- `_normalize_s2orc` takes `(raw: dict, parse_quality: str | None = None)` not `(raw, paper)` — the existing test stubs from 04-01 call it without a paper object, and parse_quality is all that's needed from the paper for normalization
- Pure `_compute_*` helpers (testable, no side effects) plus in-place `_add_*` wrappers (used by task) for clean separation between unit testing and task execution
- tiktoken lazy-imported inside functions to prevent ImportError at worker startup on fast workers (consistent with Phase 3 pattern)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Function signatures adapted to match existing test stubs**
- **Found during:** Task 1 (implementing normalize.py)
- **Issue:** Plan spec said `_normalize_s2orc(raw, paper)` but existing test stubs from 04-01 call `_normalize_s2orc(MINIMAL_S2ORC)` with no paper argument, and `_compute_token_count(text)` / `_compute_tldr(abstract)` / `_compute_dedup_fingerprint(title, first_author_last, year)` as separate pure helpers
- **Fix:** Implemented `_normalize_s2orc(raw, parse_quality=None)` matching test interface; added pure `_compute_*` helpers as primary functions; `_add_*` wrappers delegate to them
- **Files modified:** app/tasks/normalize.py
- **Verification:** All 10 tests pass
- **Committed in:** 7491952 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 signature adaptation to match pre-written tests)
**Impact on plan:** No scope change; functionally equivalent — normalize_paper task behavior identical.

## Issues Encountered
- tiktoken not installed in local test environment (already in pyproject.toml from 04-01 for Docker). Installed locally with `pip3 install tiktoken --break-system-packages` to run tests.

## User Setup Required
None — no external service configuration required. normalize_paper runs inside Docker worker with tiktoken pre-cached.

## Known Stubs
None — all normalization branches are fully implemented. normalize_paper returns {"status": "ok"} for successfully normalized papers.

## Next Phase Readiness
- Phase 5 (REST API) can now read `paper.content` JSONB directly — contains sections, citations, tldr, token_count, dedup_fingerprint, src_url
- `paper.token_count`, `paper.tldr` columns populated for all parsed papers
- Citation graph edges populated in `paper_citations` table
- All three parser chains complete end-to-end: ingest → parse → normalize

---
*Phase: 04-normalizer-storage*
*Completed: 2026-04-15*
