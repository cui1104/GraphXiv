---
phase: "07"
plan: "01"
subsystem: benchmark
tags: [benchmark, metrics, sample-selection, docling, scaffold]
dependency_graph:
  requires: []
  provides:
    - benchmark/metrics.py (heading match, coherence, table completeness, two-column detection)
    - benchmark/select_sample.py (stratified 150-paper sample selector)
    - benchmark/sample.json (produced on live DB run in 07-02)
    - requirements-benchmark.txt (docling + anthropic + analysis deps)
    - Dockerfile updated with benchmark pip install
    - tests/test_benchmark.py (18 unit tests, 16 passing, 2 skip until 07-02)
  affects:
    - 07-02 (consumes sample.json + metrics.py for benchmark run)
    - 07-03 (consumes analyze_results.py + benchmark.csv)
tech_stack:
  added:
    - docling>=2.90.0 (table extraction benchmarking)
    - anthropic>=0.40.0 (Claude Opus GT extraction in 07-02)
    - pandas>=2.0.0 (results analysis)
    - matplotlib>=3.8.0 (visualization)
    - notebook>=7.0.0 (Jupyter reporting)
  patterns:
    - Lazy ML imports (docling, pymupdf inside function bodies — never at module top)
    - sys.path.insert(0, project_root) for benchmark scripts
    - DATA_DIR env var for asset path resolution (Docker-compatible)
    - random.Random(seed=42) for reproducible stratified sampling
key_files:
  created:
    - benchmark/__init__.py
    - benchmark/metrics.py
    - benchmark/select_sample.py
    - benchmark/create_gt.py (stub)
    - benchmark/run_benchmark.py (stub)
    - benchmark/analyze_results.py (stub)
    - benchmark/gt/.gitkeep
    - benchmark/results/.gitkeep
    - benchmark/notebook/.gitkeep
    - requirements-benchmark.txt
    - tests/test_benchmark.py
  modified:
    - Dockerfile (added COPY requirements-benchmark.txt + RUN pip install)
decisions:
  - "Dry-run check moved before DB connection in select_sample.py — avoids psycopg2 OperationalError when Postgres not running locally"
  - "test_heading_match_80pct_token_overlap corrected: Results and Discussion (3 tokens) vs Results Discussion (2 tokens) = 2/3 = 0.67 < 0.8 threshold — test updated to use 4-token pair with 1.0 overlap; test_heading_match_below_threshold added"
  - "is_two_column uses lazy import pymupdf inside function body per project Pitfall 1 convention"
  - "D-05: column classification uses both parse_quality=degraded AND PyMuPDF heuristic — PyMuPDF alone also sufficient (parser may have recovered)"
metrics:
  duration: "4 minutes"
  completed: "2026-04-17"
  tasks_completed: 3
  files_changed: 12
---

# Phase 7 Plan 1: Benchmark Wave 0 Scaffold Summary

Wave 0 scaffold for Phase 7 benchmark: benchmark/ directory with metrics library, stratified sample selector, stub scripts, requirements-benchmark.txt, Dockerfile update, and 18-test unit suite.

## Scaffold Files Created

| File | Purpose |
|------|---------|
| benchmark/__init__.py | Package marker |
| benchmark/metrics.py | Pure metric library (heading match, coherence, table completeness, two-column) |
| benchmark/select_sample.py | Stratified 150-paper sample selection (writes sample.json on live DB) |
| benchmark/create_gt.py | Stub — Claude Opus GT extraction (implemented in 07-02) |
| benchmark/run_benchmark.py | Stub — 4-condition benchmark runner (implemented in 07-02) |
| benchmark/analyze_results.py | Stub — CSV analysis and visualization (implemented in 07-03) |
| benchmark/gt/.gitkeep | Git-tracks gt/ subdirectory |
| benchmark/results/.gitkeep | Git-tracks results/ subdirectory |
| benchmark/notebook/.gitkeep | Git-tracks notebook/ subdirectory |
| requirements-benchmark.txt | docling>=2.90.0, anthropic>=0.40.0, pandas>=2.0.0, matplotlib>=3.8.0, notebook>=7.0.0 |
| tests/test_benchmark.py | 18 unit tests (16 passing now, 2 skip until 07-02 generates artifacts) |

## Metric Library Public API (benchmark/metrics.py)

| Function | Purpose | Test Coverage |
|----------|---------|--------------|
| `normalize_heading(h)` | Lowercase + strip punctuation → set of tokens | test_normalize_heading_strips_punctuation |
| `heading_matched(parser, gt_list, threshold=0.8)` | Token overlap >= 0.8 against any GT heading | 5 tests |
| `compute_heading_match_rate(parser_headings, gt_headings)` | Fraction of GT headings matched | 2 tests |
| `section_is_coherent(text)` | D-11 dual signal: sentence length + non-ASCII ratio | (internal) |
| `coherent_section_pct(sections)` | Fraction of coherent sections | 4 tests |
| `_table_completeness_score(has_caption, has_headers, has_data_rows)` | D-19: 1.0/0.5/0.0 | 3 tests |
| `table_completeness_docling(table_item, doc)` | Score Docling TableItem (needs doc kwarg) | n/a (requires docling) |
| `table_completeness_grobid(tei_xml_bytes)` | Score GROBID TEI XML tables via lxml | n/a |
| `table_completeness_mineru(content_list)` | Score MinerU content_list tables | n/a |
| `is_two_column(pdf_path, sample_pages=3)` | PyMuPDF block x-coord heuristic (Pattern 6) | n/a (requires PDF) |

All functions: no top-level ML imports; lazy `import pymupdf`, `import docling`, `from lxml import etree` inside function bodies per project Pitfall 1 convention.

`_sentence_length_degraded` imported directly from `app.tasks.parse_helpers` (not re-implemented).

## Dockerfile + requirements-benchmark.txt Changes

Inserted between existing `RUN pip install --no-cache-dir ".[dev]"` and tiktoken pre-cache:
```dockerfile
# Benchmark dependencies (CPU-only docling for Phase 7 benchmark)
COPY requirements-benchmark.txt .
RUN pip install --no-cache-dir -r requirements-benchmark.txt
```

## Dry-Run Smoke Tests

All four scripts respond to `--dry-run` with exit code 0:
- `python benchmark/select_sample.py --dry-run` — prints candidate pool size + target (no DB connection)
- `python benchmark/create_gt.py --dry-run --limit 1` — stub exit 0
- `python benchmark/run_benchmark.py --dry-run` — stub exit 0
- `python benchmark/analyze_results.py --dry-run` — stub exit 0

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed select_sample.py --dry-run failing with psycopg2.OperationalError**
- **Found during:** Task 3 verification
- **Issue:** DB session was created and query executed before checking `args.dry_run`, causing a connection error when Postgres is not running locally
- **Fix:** Moved `if args.dry_run: print(...); return 0` block before `SessionLocal()` creation — eliminates DB dependency for dry-run path
- **Files modified:** benchmark/select_sample.py
- **Commit:** 0485031

**2. [Rule 1 - Bug] Fixed test_heading_match_80pct_token_overlap with incorrect expected result**
- **Found during:** Task 2 implementation (noted in plan action spec)
- **Issue:** "Results and Discussion" (3 tokens) vs "Results Discussion" (2 tokens) gives 2/3 = 0.67 overlap, which is BELOW 0.8 threshold — test would fail
- **Fix:** Updated test to use "Results and Discussion of Experiments" (5 tokens) vs "Results, and Discussion of Experiments" (5 tokens) — 5/5 = 1.0 overlap; added test_heading_match_below_threshold to explicitly test the 0.67 < 0.8 case as False
- **Files modified:** tests/test_benchmark.py
- **Commit:** 98289e5

## Known Stubs

| File | Stub | Reason |
|------|------|--------|
| benchmark/create_gt.py | Raises NotImplementedError | Implemented in 07-02 (requires ANTHROPIC_API_KEY + sample.json) |
| benchmark/run_benchmark.py | Raises NotImplementedError | Implemented in 07-02 (requires sample.json + GT data) |
| benchmark/analyze_results.py | Raises NotImplementedError | Implemented in 07-03 (requires benchmark.csv from 07-02) |
| benchmark/sample.json | Not yet generated | Generated at start of 07-02 using live DB + select_sample.py |

These stubs are intentional Wave 0 placeholders. Plans 07-02 and 07-03 fill them in.

## Self-Check: PASSED

Files exist:
- benchmark/metrics.py: FOUND
- benchmark/select_sample.py: FOUND
- requirements-benchmark.txt: FOUND
- tests/test_benchmark.py: FOUND
- Dockerfile (updated): FOUND

Commits:
- c85612a: feat(07-01): create benchmark scaffold, requirements, Dockerfile updates, and test suite
- 98289e5: feat(07-01): implement benchmark/metrics.py with heading match, coherence, table completeness, two-column detection
- 0485031: feat(07-01): implement benchmark/select_sample.py — stratified 150-paper selection writing sample.json
