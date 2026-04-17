---
phase: 7
slug: benchmark
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-17
---

# Phase 7 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x (existing) + manual script smoke tests |
| **Config file** | `pyproject.toml` (existing pytest config) |
| **Quick run command** | `pytest tests/ -x -q --ignore=tests/test_api.py` |
| **Full suite command** | `pytest tests/ -q` |
| **Benchmark smoke test** | `cd benchmark && python select_sample.py --dry-run` |
| **Estimated runtime** | ~30 seconds (existing tests); benchmark run 6–12 hours |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/ -x -q`
- **After every plan wave:** Run full suite + benchmark script smoke test
- **Before `/gsd:verify-work`:** Full suite must be green; benchmark CSV must exist with 600 rows
- **Max feedback latency:** 60 seconds (tests only; benchmark run is asynchronous)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 7-01-01 | 07-01 | 1 | BENCH-01 | smoke | `python benchmark/select_sample.py --dry-run` | ❌ W0 | ⬜ pending |
| 7-01-02 | 07-01 | 1 | BENCH-01 | smoke | `python -c "from docling.document_converter import DocumentConverter; print('ok')"` | ❌ W0 | ⬜ pending |
| 7-01-03 | 07-01 | 1 | BENCH-01 | file | `test -f benchmark/sample.json && python -c "import json; d=json.load(open('benchmark/sample.json')); assert len(d)==150"` | ❌ W0 | ⬜ pending |
| 7-02-01 | 07-02 | 2 | BENCH-02 | smoke | `python benchmark/create_gt.py --dry-run --limit 1` | ❌ W0 | ⬜ pending |
| 7-02-02 | 07-02 | 2 | BENCH-02 | file | `test -f benchmark/results/benchmark.csv && python -c "import csv; rows=list(csv.DictReader(open('benchmark/results/benchmark.csv'))); assert len(rows)==600"` | ❌ W0 | ⬜ pending |
| 7-02-03 | 07-02 | 2 | BENCH-02 | column | `python -c "import csv; h=next(csv.DictReader(open('benchmark/results/benchmark.csv'))); [h[k] for k in ['paper_id','condition','heading_match_rate','coherent_section_pct','table_presence','table_structural_completeness']]"` | ❌ W0 | ⬜ pending |
| 7-03-01 | 07-03 | 3 | BENCH-03 | file | `test -f benchmark/FINDINGS.md && grep -q "MinerU" benchmark/FINDINGS.md && grep -q "GROBID" benchmark/FINDINGS.md && grep -q "Docling" benchmark/FINDINGS.md && grep -q "Router" benchmark/FINDINGS.md` | ❌ W0 | ⬜ pending |
| 7-03-02 | 07-03 | 3 | BENCH-03 | file | `test -f benchmark/notebook/analysis.ipynb` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `benchmark/` directory created
- [ ] `benchmark/select_sample.py` — stub with `--dry-run` flag
- [ ] `benchmark/create_gt.py` — stub with `--dry-run --limit N` flag
- [ ] `benchmark/run_benchmark.py` — stub
- [ ] `benchmark/analyze_results.py` — stub
- [ ] `benchmark/gt/` directory created
- [ ] `benchmark/results/` directory created
- [ ] `benchmark/notebook/` directory created
- [ ] `requirements-benchmark.txt` — docling>=2.90.0, anthropic>=0.40.0, pandas>=2.0.0, matplotlib>=3.8.0, notebook>=7.0.0
- [ ] Docling import smoke test passes

*Wave 0 creates the benchmark/ scaffold before any task modifies files.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Claude Opus GT extraction quality | BENCH-02 | Requires visual inspection of heading lists | Review 3–5 `benchmark/gt/{paper_id}.json` files; confirm headings match visible PDF structure |
| Benchmark runtime acceptable | BENCH-01 | 6–12 hour wall-clock run | Start `run_benchmark.py` before sleep; check completion and no crashes next morning |
| FINDINGS.md recommendation is reasoned | BENCH-03 | Qualitative judgment | Human reads recommendation section; confirms it cites data from comparison table |
| Two-column failure characterization | BENCH-03 | Requires domain knowledge | Verify the findings report discusses multi-column interleaving artifacts specifically for IEEE/ACM papers |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
