# Phase 7: Benchmark - Context

**Gathered:** 2026-04-16
**Status:** Ready for planning

<domain>
## Phase Boundary

Empirical comparison of MinerU, GROBID, Docling, and the pipeline router on 150 DL papers from the stored corpus. Deliverables: a CSV with per-condition metrics and a findings report (FINDINGS.md + Jupyter notebook with charts) recommending a MinerU fallback parser.

Scope is evaluation only — no changes to the pipeline itself.

</domain>

<decisions>
## Implementation Decisions

### Execution environment
- **D-01:** 150 papers → runs entirely on local Mac (CPU). No VM or GPU required at this scale.
- **D-02:** Benchmark lives in a self-contained `benchmark/` directory at project root.
- **D-03:** Implemented as Python scripts (not a Celery task, not a notebook-only workflow):
  - `benchmark/select_sample.py` — stratified paper selection from DB
  - `benchmark/create_gt.py` — ground truth extraction via Claude Opus vision API
  - `benchmark/run_benchmark.py` — runs all four conditions on the 150 papers
  - `benchmark/analyze_results.py` — computes metrics and produces the comparison table
  - `benchmark/results/benchmark.csv` — raw per-paper per-condition output
  - `benchmark/FINDINGS.md` — formal write-up with comparison table and recommendation
  - `benchmark/notebook/analysis.ipynb` — charts and visualizations

### Sample selection
- **D-04:** Sample is stratified to match corpus proportions:
  - Source proportion: arXiv vs PMC ratio as it exists in the DB
  - Subject distribution within ML/DL: cs.LG / cs.AI / cs.CV / cs.CL / stat.ML proportional to DB counts
  - Focus: ML/DL domain only (papers from those five arXiv categories + PMC DL subset)
- **D-05:** Two-column paper identification uses both signals combined: (1) existing `parse_quality` degradation flags in the DB, then (2) PyMuPDF column-layout heuristic on the actual PDF asset. Parse_quality flags are the first filter; PyMuPDF confirms.
- **D-06:** Papers are pulled from the DB (already-parsed papers preferred to ensure router output exists for comparison). Raw assets supplement if DB count is insufficient for stratification targets.
- **D-07:** Exactly 150 papers; at least 30 must be two-column IEEE/ACM-format papers. Selection script enforces this constraint and aborts with a clear error if the corpus cannot satisfy it.

### Ground truth methodology
- **D-08:** Ground truth for section headings uses **Claude Opus vision API** (claude-opus-4-6) for ALL 150 papers. This is consistent across paper types (LaTeX-sourced and PDF-only alike), avoids circular evaluation, and treats GT creation as a separate upstream step.
- **D-09:** Ground truth script (`create_gt.py`) renders each PDF page as an image (via PyMuPDF), sends to Claude Opus with a prompt to extract section headings in order, and stores results as JSON: `{paper_id: [heading1, heading2, ...]}`
- **D-10:** Heading match criterion: **fuzzy match with token overlap ≥ 80%**. Normalize both GT and parser output (lowercase, strip punctuation) before comparing. A heading is "matched" if any GT heading has ≥ 80% token overlap with the parser output heading.
- **D-11:** Coherent body text detection uses **both signals combined**:
  - Sentence-length heuristic: reuse `_sentence_length_degraded()` from `app/tasks/parse_helpers.py` (avg sentence > 80 tokens = degraded)
  - Non-ASCII/symbol ratio: >5% non-ASCII or punctuation-heavy tokens = garbled
  - A section is coherent if BOTH signals are within threshold. Coherence % = fraction of sections where both pass.

### Docling setup
- **D-12:** Docling added to the **existing Docker image** (CPU-only mode). Add `docling` to `pyproject.toml` extras or a new `requirements-benchmark.txt` imported in the Dockerfile. No separate Docker service needed.
- **D-13:** Docling runs via its Python API (`DocumentConverter`) inside the benchmark scripts, not as an HTTP service.

### GROBID standalone condition
- **D-14:** GROBID standalone condition uses the **existing GROBID Docker service** (already running).
- **D-15:** For the GROBID standalone condition, call `/api/processFulltextDocument` (not `/api/processReferences` which is what the pipeline currently uses). This requires adding a new `extract_fulltext_document()` function to `app/parsers/grobid.py` that calls the full-text endpoint and parses TEI XML into section headings + body text.
- **D-16:** GROBID section extraction from TEI XML: parse `<div>` elements with `<head>` children from the `<body>` element in the TEI response.

### Metrics and CSV schema
- **D-17:** CSV columns: `paper_id`, `arxiv_id`, `source_type` (arxiv/pmc), `column_layout` (single/two), `subject` (cs.LG etc.), `condition` (mineru/grobid/docling/router), `heading_count_gt`, `heading_count_parser`, `heading_match_rate`, `coherent_section_pct`, `table_presence` (0/1), `table_structural_completeness` (0.0–1.0), `error` (null or error string).
- **D-18:** One row per (paper, condition) combination → 150 × 4 = 600 rows total.
- **D-19:** Table structural completeness score: 1.0 if table has caption + headers + ≥1 data row; 0.5 if caption only; 0.0 if absent or empty.

### Report
- **D-20:** `benchmark/FINDINGS.md` — Markdown, committed to repo. Sections: methodology, sample composition, four-column comparison table (MinerU | GROBID | Docling | Router), multi-column failure characterization, parser recommendation for MinerU fallback.
- **D-21:** `benchmark/notebook/analysis.ipynb` — matplotlib charts (bar charts for heading match rate and coherence, scatter for table quality, box plots for per-condition distributions). Generated from the same CSV.

### Claude's Discretion
- Exact PyPI version of Docling to install
- Dockerfile placement of docling dependency
- Exact Opus prompt used for GT extraction (can iterate)
- Retry/timeout handling for Claude Opus API calls in create_gt.py
- How to handle papers where a parser crashes (record as error row, continue)

</decisions>

<specifics>
## Specific Ideas

- The 150-paper sample must be **reproducible** — selection script outputs a `benchmark/sample.json` with the exact paper IDs selected, so the benchmark can be re-run on the same set.
- GT creation is expensive (150 API calls to Opus). `create_gt.py` should be idempotent and cache results to `benchmark/gt/` so it can be interrupted and resumed.
- The GROBID fulltext endpoint is slower than processReferences. Plan for ~10–30s per paper for GROBID standalone condition.
- MinerU standalone re-runs the `magic-pdf` call on each paper's PDF (not using the DB cached output), so MinerU standalone is evaluated on raw output, not pipeline output.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Parsing infrastructure
- `app/tasks/parse_helpers.py` — `_sentence_length_degraded()`, `_count_pdf_tables()`, `_has_text_layer()` — reuse for coherence detection and PDF analysis
- `app/parsers/grobid.py` — existing GROBID HTTP client (`extract_references()`); new `extract_fulltext_document()` goes here
- `app/tasks/parse.py` — `parse_pdf_mineru()` implementation; MinerU standalone condition mirrors this logic
- `app/tasks/router.py` — router logic; router condition calls the existing pipeline endpoint or replicates routing logic

### Data access
- `app/models.py` — `Paper`, `PaperSource`, `CrawlState` models; needed to query DB for sample selection
- `app/db.py` — `SessionLocal` for DB access in benchmark scripts

### Requirements
- `.planning/REQUIREMENTS.md` §Benchmark — BENCH-01, BENCH-02, BENCH-03 exact acceptance criteria
- `.planning/ROADMAP.md` §Phase 7 — success criteria with specific numeric targets

### No external specs — requirements fully captured in decisions above and REQUIREMENTS.md

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `app/tasks/parse_helpers.py::_sentence_length_degraded()`: reuse directly for coherence detection (D-11)
- `app/tasks/parse_helpers.py::_has_text_layer()`: use to check PDF has extractable text before running parsers
- `app/tasks/parse_helpers.py::_count_pdf_tables()`: use for table presence heuristic
- `app/parsers/grobid.py::extract_references()`: pattern to follow when adding `extract_fulltext_document()`
- `app/db.py::SessionLocal`: use for benchmark scripts that query the DB

### Established Patterns
- All imports of heavy ML packages (magic-pdf, etc.) are lazy (inside function bodies) — follow same pattern in benchmark scripts to avoid import failures at CLI entry point
- Papers stored with `parse_quality` flags in `Paper.parse_quality` JSONB column — query this for two-column detection
- `PaperSource.source_type` distinguishes `arxiv_tar`, `arxiv`, `pmc`, `arxiv_pdf` etc.

### Integration Points
- Benchmark queries DB using same `SessionLocal` pattern as the app
- GROBID service accessible at `GROBID_URL` env var (same as pipeline)
- MinerU standalone uses `magic-pdf` Python API directly (same as `parse_pdf_mineru` task)

</code_context>

<deferred>
## Deferred Ideas

- Running the benchmark on the full 10,000-paper corpus — requires GPU VM, deferred to post-v1
- Nougat parser as a fifth condition — explicitly out of scope per REQUIREMENTS.md
- Automated benchmark re-runs as CI checks — v2

</deferred>

---

*Phase: 07-benchmark*
*Context gathered: 2026-04-16*
