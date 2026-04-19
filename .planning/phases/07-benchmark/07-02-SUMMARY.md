---
phase: "07"
plan: "02"
subsystem: benchmark
tags: [benchmark, gemini-vision, four-condition, mineru, grobid, docling, router]
dependency_graph:
  requires:
    - phase: "07-01"
      provides: [benchmark/metrics.py, benchmark/select_sample.py, tests/test_benchmark.py]
  provides:
    - benchmark/sample.json (150 single-column papers, stratified by subject)
    - benchmark/gt/{paper_id}.json (150 GT files from Gemini 2.5 Flash vision)
    - benchmark/results/benchmark.csv (600 rows, 4 conditions × 150 papers, 0 errors)
    - benchmark/create_gt.py (Gemini-based GT extractor with caching)
    - benchmark/run_benchmark.py (4-condition runner with --resume)
  affects:
    - 07-02.5 (will overwrite CSV + GT with v2 recall-aware metrics)
    - 07-03 (consumes final CSV for FINDINGS.md)
tech_stack:
  added:
    - google-generativeai (Gemini 2.5 Flash vision — replaced anthropic for GT)
  patterns:
    - GT idempotency via per-paper JSON cache
    - CSV streaming + --resume for (paper,condition) pairs
    - DATA_DIR env-var PDF path remapping for container/host portability
    - Per-paper crash isolation (error row, script continues)
key_files:
  created:
    - benchmark/create_gt.py
    - benchmark/run_benchmark.py
    - benchmark/sample.json
    - benchmark/gt/*.json (150 files)
    - benchmark/results/benchmark.csv
  modified:
    - benchmark/metrics.py (minor Pyright fixes)
    - tests/test_benchmark.py (schema column update for sec_per_doc)
key_decisions:
  - "Pivoted GT annotator from Claude Opus to Gemini 2.5 Flash (commits 24121b4, 416355b) — 2.0-flash was unavailable for new accounts; cost reduction vs Opus; paid via Google API"
  - "Dropped two-column minimum constraint (commit 5f82c67) — corpus after fetcher filtering yielded no two-column papers; benchmark runs on single-column corpus only. Two-column failure characterization in 07-03 will note corpus limitation."
  - "Added sec_per_doc column to CSV (schema drift from D-17) for cross-parser section-density signal. 07-02.5 schema v2 folds this into body_token_count + hierarchy metrics."
  - "Executed on RunPod RTX 4090 (SSH root@103.196.86.133:13999, /workspace/project) — MinerU and Docling need GPU for tractable runtime"
requirements_completed:
  - BENCH-01
  - BENCH-02
duration: "~5h (overnight run; code implementation ~2h)"
completed: "2026-04-17"
---

# Phase 7 Plan 02: Benchmark Data Collection Summary

**Four-condition benchmark CSV on 150 single-column papers via Gemini 2.5 Flash GT + MinerU/GROBID/Docling/Router on RunPod RTX 4090 — 600 rows, zero errors, raw signal ready for v2 metric overhaul in 07-02.5.**

## Performance

- **Duration:** ~5h total (code implementation ~2h; overnight benchmark run ~3h on GPU)
- **Completed:** 2026-04-17
- **Tasks:** 3 (Task 1 create_gt, Task 2 run_benchmark, Task 3 human checkpoint)
- **Files modified:** 5 (create_gt.py, run_benchmark.py, sample.json, metrics.py, test_benchmark.py)

## Accomplishments

- `benchmark/sample.json` — 150 stratified single-column papers (cs.LG, cs.AI, cs.CV, cs.CL, stat.ML, pmc-dl, other) committed
- `benchmark/create_gt.py` — Gemini 2.5 Flash vision GT extractor with idempotent per-paper cache (`benchmark/gt/{paper_id}.json`)
- `benchmark/gt/*.json` — 150 GT files with `{headings: [str, ...]}` v1 schema (flat list)
- `benchmark/run_benchmark.py` — four-condition runner (mineru, grobid, docling, router) with `--resume`, `--condition`, `--limit`, `--dry-run` flags and per-paper crash isolation
- `benchmark/results/benchmark.csv` — 600 rows (150 papers × 4 conditions), 0 parser errors, 14-column schema with `sec_per_doc`
- RunPod RTX 4090 execution path validated (Docker + DATA_DIR remap + ssh workflow)

## v1 Baseline Numbers (pre-overhaul)

| Condition | n | Errors | heading_match_rate (mean) |
|-----------|---|--------|---------------------------|
| mineru    | 150 | 0 | 0.472 |
| grobid    | 150 | 0 | 0.662 |
| docling   | 150 | 0 | 0.483 |
| router    | 150 | 0 | 0.586 |

GROBID leads on precision (the only heading metric in v1) — this triggered plan 07-02.5 (precision-only biases toward under-extraction; see 07-02.5-PLAN.md).

## Task Commits

1. **Task 1: `create_gt.py` + `sample.json`** — `1f5d0f2` (feat)
2. **Pivot: Claude Opus → Gemini 2.0 Flash** — `24121b4` (feat)
3. **Pivot fix: Gemini 2.0 → 2.5 Flash** — `416355b` (fix)
4. **Sample relaxation: drop two-col minimum** — `5f82c67` (fix)
5. **Task 2: `run_benchmark.py` 4-condition runner** — `c503540` (feat)
6. **Task 3: Complete overnight benchmark run** — `331c3ac` (feat)

## Files Created/Modified

- `benchmark/create_gt.py` — Gemini 2.5 Flash vision GT (10-page cap, DPI 120, JSON-fence stripping)
- `benchmark/run_benchmark.py` — 4-condition runner with streaming CSV + resume
- `benchmark/sample.json` — 150 single-column papers
- `benchmark/gt/*.json` — 150 GT files (v1 schema: `{paper_id, model, headings: [str, ...]}`)
- `benchmark/results/benchmark.csv` — 600 rows, D-17 schema + `sec_per_doc` column
- `benchmark/metrics.py` — Pyright diagnostic fixes (type annotations only, behavior unchanged)
- `tests/test_benchmark.py` — schema assertion updated for 14-column header

## Decisions Made

1. **GT annotator pivot Claude Opus → Gemini 2.5 Flash**: original plan specified `claude-opus-4-6` (~$15–20), but 2.0-flash was unavailable on new Google accounts; switched to 2.5 Flash after testing shows comparable heading extraction quality at lower cost.
2. **Two-column corpus dropped**: arXiv-OAI + PMC fetchers after Phase 01-04 filters produced zero papers classified as two-column in the 150-paper sample. Relaxing the constraint (commit 5f82c67) avoids blocking the benchmark on corpus bias. 07-03 multi-column section will note the corpus limitation rather than fabricate results.
3. **Schema drift `sec_per_doc`**: added as orthogonal signal (section density per doc); 07-02.5 subsumes this into `body_token_count` + hierarchy metrics.
4. **Execute on RunPod, not local**: MinerU + Docling GPU inference is ~10× faster on RTX 4090; local runtime would exceed 24h for 600 rows.

## Deviations from Plan

### 1. GT model substitution (Rule: blocking — original model unavailable)
- **Found during:** Task 1 initial run — `claude-opus-4-6` 403 from Anthropic
- **Issue:** Anthropic account had no Opus access; quickly pivoted to Gemini 2.0 Flash then 2.5 Flash (2.0 also unavailable for new accounts per 416355b)
- **Fix:** `MODEL_ID = "gemini-2.5-flash"` in create_gt.py; updated prompt and response parsing for Gemini API surface
- **Committed in:** 24121b4, 416355b

### 2. Two-column minimum dropped
- **Found during:** Task 1 post-sample regeneration
- **Issue:** `select_sample.py` produced 0 two-column papers from current DB — corpus is entirely single-column after earlier filtering in phases 01-04
- **Fix:** Removed the `>=30 two-column` assertion; noted in 07-03 that multi-column analysis is corpus-limited
- **Committed in:** 5f82c67

### 3. `sec_per_doc` added to CSV schema
- **Issue:** Useful orthogonal density signal missing from D-17
- **Fix:** Added as 13th data column (before `error`); `test_csv_schema_columns` updated
- **Impact:** 07-02.5 v2 schema supersedes this; backward compat not a concern

**Total deviations:** 3 (1 model pivot, 1 scope relaxation, 1 schema extension)
**Impact on plan:** All unblocking or additive. BENCH-01 and BENCH-02 satisfied on the single-column corpus. Recall-aware re-analysis is plan 07-02.5.

## Issues Encountered

- **RunPod path remapping** — `sample.json` stores host-absolute paths; container runs needed `DATA_DIR=/data` env var + `_remap_pdf_path` helper in run_benchmark.py. Resolved without schema change.
- **Router condition semantics** — runs on `Paper.content` from DB (pre-parsed), NOT re-parsing PDFs. Confirmed this is the intended D-17 behavior (router = pipeline output) per 07-02 Pitfall 7.

## v1 → v2 Handoff for Plan 07-02.5

The raw v1 CSV will be **archived as `benchmark.v1.csv`** by 07-02.5 Task 6 before regeneration. Key signals 07-02.5 will overhaul:

- **Metric bias**: `heading_match_rate` is precision-only → GROBID wins by under-extracting. v2 adds `heading_precision`, `heading_recall`, `heading_f1`.
- **Missing router differentiator**: v1 passes through child sections unchanged; router's dot-count hierarchy reconstruction never exercised. v2 adds `_apply_dot_count_hierarchy` + `hierarchy_f1` column.
- **Content richness**: v1 scores headings + coherence + tables only; skips figures/formulas/references where MinerU + Docling excel. v2 adds `body_token_count`, `figure_count_{parser,gt}`, `formula_count_{parser,gt}`, `reference_count_{parser,gt}`.
- **GT schema v2**: `headings: [str, ...]` → `headings: [{text, sec_num}, ...]` plus `figure_count`, `formula_count`, `reference_count` top-level fields. Re-extraction cost ~$15 via Gemini 2.5 Flash.

## Next Phase Readiness

- Plan 07-02.5 has all prerequisites (CSV on disk, GT cache warm, runner idempotent)
- RunPod instance `root@103.196.86.133:13999` still provisioned for v2 re-run (~4.5h)
- Plan 07-03 waits for v2 CSV; v1 CSV will be preserved as `benchmark.v1.csv` for diff analysis in FINDINGS.md

---
*Phase: 07-benchmark*
*Completed: 2026-04-17*
