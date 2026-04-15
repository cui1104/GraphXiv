---
phase: 03-parser-layer
verified: 2026-04-15T19:30:00Z
status: passed
score: 6/6 must-haves verified
re_verification: false
---

# Phase 3: Parser Layer Verification Report

**Phase Goal:** Implement the parser layer — all four parser tasks (parse_latex, parse_jats, parse_pdf_mineru, parse_pdf_grobid), the shared helper module, the smart router, and batch dispatcher.
**Verified:** 2026-04-15T19:30:00Z
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | TEX2JSON path: .tar.gz unpacked, main .tex detected, doc2json called, backslash quality check applied, parse_source=latex | VERIFIED | `parse_latex` in `app/tasks/parse.py` L20-192: D-01/D-02 heuristics, `process_tex_stream` import, `_backslash_ratio_degraded` check, `paper.parse_source = "latex"` |
| 2 | JATS2JSON path: DOCTYPE stripped, process_jats_stream called, parse_source=jats | VERIFIED | `parse_jats` in `app/tasks/parse.py` L203-279: `_strip_jats_doctype(raw)` L237, `process_jats_stream` import L209, `paper.parse_source = "jats"` L257 |
| 3 | MinerU path: pymupdf text-layer check, scanned PDFs skipped, sentence-length degradation check, parse_source=pdf_mineru | VERIFIED | `parse_pdf_mineru` in `app/tasks/parse.py` L290-397: `_has_text_layer` L318, `scanned_skip` L319, `PymuDocDataset` L327, `_sentence_length_degraded` L365, `paper.parse_source = "pdf_mineru"` L370 |
| 4 | GROBID path: /api/processReferences called via httpx, TEI XML parsed to citation dicts, failure returns [] (non-blocking), parse_source=pdf_grobid on D-03 cascade | VERIFIED | `app/parsers/grobid.py`: `client.post(f"{GROBID_URL}/api/processReferences", ...)` L34-35, `_parse_tei_references` L48-92, `except Exception -> return []` L43-45; D-03 cascade: `paper.parse_source = "pdf_grobid"` L454 |
| 5 | Smart router selects TEX2JSON > JATS2JSON > MinerU priority; dispatches correct Celery chain per source_type; parse_source recorded correctly | VERIFIED | `app/tasks/router.py`: priority_order list L82, `_build_parse_chain` L18-57 maps source types to chains, all chains use `.si()` immutable signatures |
| 6 | Batch dispatcher groups all pending papers and dispatches celery.group; D-03 table-count routing inside parse_latex | VERIFIED | `dispatch_pending_batch` L109-158 queries `PaperSource.parse_status == "pending"`, builds chains, calls `group(chains).apply_async()` L152; D-03 branch in `parse_latex` L94-133 |

**Score:** 6/6 truths verified

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `app/tasks/parse_helpers.py` | Shared helper functions for all parse tasks | VERIFIED | All 5 exported helpers present: `_backslash_ratio_degraded`, `_strip_jats_doctype`, `_has_text_layer`, `_sentence_length_degraded`, `_count_pdf_tables` — 123 lines, all substantive with real logic |
| `app/tasks/parse.py` | All four Celery parse tasks | VERIFIED | 486 lines; `parse_latex`, `parse_jats`, `parse_pdf_mineru`, `parse_pdf_grobid` all present with full implementations |
| `app/parsers/grobid.py` | GROBID httpx client and TEI XML parser | VERIFIED | 93 lines; `extract_references` and `_call_grobid_references` logic present, `_parse_tei_references` parses title/authors/year/doi fields |
| `app/tasks/router.py` | Smart router and batch dispatcher | VERIFIED | 160 lines; `route_paper`, `dispatch_pending_batch`, `_build_parse_chain` all present and substantive |
| `app/parsers/__init__.py` | Package init for parsers module | VERIFIED | File exists |
| `Dockerfile` | System binaries tralics and latexpand; magic-pdf.json | VERIFIED | `apt-get install tralics texlive-extra-utils` L9-13; `magic-pdf.json` with cuda config L16 |
| `pyproject.toml` | magic-pdf[full], s2orc-doc2json, PyMuPDF dependencies | VERIFIED | All three present: `magic-pdf[full]>=1.3.12` L22, `s2orc-doc2json @ git+...` L20, `PyMuPDF>=1.27.0` L21 |
| `tests/test_parse.py` | Test coverage for all PARSE-* requirements | VERIFIED | Substantive unit tests for `test_backslash_ratio_check`, `test_strip_doctype`, `test_strip_doctype_with_internal_subset`, `test_sentence_length_check`, `test_grobid_references`, `test_router_dispatch` — integration tests correctly skipped with `pytest.skip` (not stubs with empty bodies) |
| `tests/fixtures/sample_arxiv.tar.gz` | Minimal LaTeX paper fixture | VERIFIED | 261-byte gzip; contains `main.tex` with `\documentclass{article}`, title, abstract, introduction body paragraph |
| `tests/fixtures/sample_pmc.xml` | PMC JATS XML fixture | VERIFIED | Contains `<!DOCTYPE article PUBLIC "-//NLM//DTD..."` DOCTYPE declaration (confirms DOCTYPE stripping is exercised) |
| `tests/fixtures/sample_scanned.pdf` | Scanned PDF fixture for text layer test | VERIFIED | File present; test_scanned_pdf_detection references it with pymupdf importskip guard |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `app/tasks/parse.py` | `doc2json.tex2json.process_tex` | `from doc2json.tex2json.process_tex import process_tex_stream` | WIRED | L136 of parse.py (lazy import inside function) |
| `app/tasks/parse.py` | `doc2json.jats2json.process_jats` | `from doc2json.jats2json.process_jats import process_jats_stream` | WIRED | L209 of parse.py (top-level import inside function) |
| `app/tasks/parse.py` | `app/tasks/parse_helpers` | `from app.tasks.parse_helpers import ...` | WIRED | L3-9 top-level import of all 5 helpers; all helpers used in respective tasks |
| `app/tasks/parse.py` | `magic_pdf.data.dataset` | `from magic_pdf.data.dataset import PymuDocDataset` | WIRED | L327 lazy import; `PymuDocDataset(pdf_bytes)` called L341 |
| `app/tasks/parse.py` | `app/models.py` | `PaperSource` query and status update | WIRED | `Paper` and `PaperSource` queried and updated in every task |
| `app/parsers/grobid.py` | `http://grobid:8070/api/processReferences` | `client.post(...processReferences...)` | WIRED | L34-38: `client.post(f"{GROBID_URL}/api/processReferences", files={"input": ...})` |
| `app/tasks/router.py` | `app/tasks/parse.py` | `chain(parse_latex.si(...), ...)` | WIRED | L35-54 `_build_parse_chain` imports and calls `.si()` on all four tasks |
| `app/tasks/router.py` | `app/models.py` | `PaperSource.parse_status == "pending"` | WIRED | L75 `route_paper`, L122 `dispatch_pending_batch` |
| `app/celery_app.py` | `app/tasks/router` | `include=[..., "app.tasks.router"]` | WIRED | L9 of celery_app.py; `app.tasks.router.*` routes to `fast` queue at L30 |

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| PARSE-01 | 03-01 | TEX2JSON fast path — arXiv .tar.gz unpacked; main .tex detected by `\documentclass` heuristic; post-parse `parse_quality=degraded` if >2% backslash tokens | SATISFIED | `parse_latex` L20-192: D-01 filename heuristic L66-79, D-02 documentclass heuristic L82-91, D-03 table routing L94-133, TEX2JSON call L136-141, backslash check L161-162, `paper.parse_source = "latex"` L165 |
| PARSE-02 | 03-02 | JATS2JSON fast path — JATS XML parsed; JATS schema version detected from `<!DOCTYPE>` and normalized before parsing | SATISFIED | `parse_jats` L203-279: `_strip_jats_doctype(raw)` L237 handles both NLM 2.x and JATS 1.x DOCTYPE; `process_jats_stream` called L240; `paper.parse_source = "jats"` L257 |
| PARSE-03 | 03-03 | MinerU PDF path — PDF pre-checked for text layer with pymupdf; scanned PDFs flagged separately; MinerU extracts structured JSON | SATISFIED | `parse_pdf_mineru` L290-397: `_has_text_layer` check L318, `scanned_skip` L319, MinerU pipeline L325-353, `content_list` stored L372, sentence-length degradation L365-366 |
| PARSE-04 | 03-04 | GROBID 0.8 called via `/api/processReferences`; enriches citations list; not used as primary parser | SATISFIED | `app/parsers/grobid.py`: httpx POST to `/api/processReferences` L34-38; TEI XML parsed to citation dicts L48-92; called in chains after primary parsers; only primary when D-03 cascade (`parse_source=pdf_grobid` only then) |
| PARSE-05 | 03-04 | Parser routing: TEX2JSON > JATS2JSON > MinerU > GROBID priority; `parse_source` recorded; multi-column degradation detected by avg sentence length >80 tokens | SATISFIED | `app/tasks/router.py` priority_order L82; `parse_source` set in each task (latex/jats/pdf_mineru/pdf_grobid); `_sentence_length_degraded(text, threshold=80)` in `parse_pdf_mineru` L365 |

All 5 requirements (PARSE-01 through PARSE-05) are SATISFIED.

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `app/parsers/grobid.py` | 41, 45 | `return []` on failure | INFO | By design — intentional non-blocking pattern per D-07; GROBID failure must not fail the parse chain |
| `tests/test_parse.py` | 103-106 | `pytest.skip(...)` in `test_count_pdf_tables` | INFO | Acknowledged skip for a D-03 helper test; the D-03 routing logic itself is tested by `test_router_dispatch`; not a blocker |
| `tests/test_parse.py` | 113-126 | `pytest.skip(...)` in integration tests | INFO | Correctly skipped integration tests that require installed binaries (tralics, GPU); not stubs — helper unit tests are fully implemented |

No blockers or warnings found. All `return []` instances in grobid.py are intentional error-handling paths, not stubs. All `pytest.skip` calls are for externally-dependent integration tests, not placeholder implementations.

---

## Human Verification Required

### 1. End-to-end TEX2JSON parse with real arXiv archive

**Test:** Run `parse_latex` against a real multi-file arXiv .tar.gz with `\documentclass` in a non-root .tex file
**Expected:** D-02 heuristic (largest .tex) correctly identifies main file; `process_tex_stream` produces non-empty `body_text`
**Why human:** The fixture `sample_arxiv.tar.gz` has a single `main.tex` — D-02 multi-file detection requires a real multi-file archive and an installed `tralics`/`latexpand` environment

### 2. JATS DOCTYPE stripping for NLM 2.x vs JATS 1.x variants

**Test:** Run `parse_jats` against both NLM 2.x and JATS 1.x formatted XML files
**Expected:** Both parse successfully without lxml DTD fetch hangs; `process_jats_stream` returns a non-empty dict
**Why human:** Requires s2orc-doc2json installed; network/container environment needed to verify no DTD hang occurs

### 3. MinerU GPU path with real born-digital PDF

**Test:** Run `parse_pdf_mineru` on a two-column IEEE/ACM PDF with `magic-pdf[full]` installed on GPU
**Expected:** `content_list` contains text blocks; multi-column paper triggers `parse_quality=degraded` via `_sentence_length_degraded`
**Why human:** Requires GPU worker and real `magic-pdf` installation; `pytest.mark.gpu` tests are appropriately skipped

### 4. GROBID live integration

**Test:** Bring up Docker Compose (including grobid service), run `parse_pdf_grobid` on a paper with a PDF asset
**Expected:** Citations returned with title/authors/year/doi; service responds at `http://grobid:8070/api/processReferences`
**Why human:** Requires Docker Compose environment with GROBID container running

---

## Gaps Summary

No gaps found. All must-haves are verified against the actual codebase.

The phase fully achieves its goal:
- All four Celery parse tasks are implemented with substantive logic (not stubs)
- `parse_helpers.py` exports all 5 required helper functions with real implementations
- `app/parsers/grobid.py` implements the GROBID client with TEI XML parsing
- `app/tasks/router.py` implements priority-ordered routing and batch fan-out
- All key wiring links are confirmed (imports, DB updates, celery chains, GROBID HTTP call)
- All 5 PARSE-* requirements are satisfied by the implementation
- Fixtures are real (not empty): sample_arxiv.tar.gz contains a valid .tex with `\documentclass`
- The Dockerfile installs `tralics` and `texlive-extra-utils` and writes `magic-pdf.json`
- `pyproject.toml` declares `magic-pdf[full]`, `s2orc-doc2json`, and `PyMuPDF` dependencies

---

_Verified: 2026-04-15T19:30:00Z_
_Verifier: Claude (gsd-verifier)_
