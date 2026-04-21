---
phase: 08-agent-evaluation
plan: 03
subsystem: agent-evaluation
tags: [llm-judge, paired-wilcoxon, citation-coverage, findings]
dependency_graph:
  requires: [08-01, 08-02]
  provides: [eval-findings]
  affects: []
tech_stack:
  added: [scipy.stats.wilcoxon, scipy.stats.spearmanr, scipy.stats.pearsonr]
  patterns: [strict-json-schema-judge, paired-position-bias-seed, deterministic-grounding-crosscheck, percentile-bootstrap-ci]
key_files:
  created:
    - eval/score.py
    - eval/analyze.py
    - eval/FINDINGS.md
    - eval/results/run_20260421_201456/scores.jsonl   # gitignored
    - .planning/phases/08-agent-evaluation/deferred-items.md
  modified:
    - tests/test_eval.py
    - .planning/phases/08-agent-evaluation/08-CONTEXT.md
    - .planning/REQUIREMENTS.md
    - .planning/STATE.md
decisions:
  - D-32 score/analyze outputs live inside {run_dir} to match Wave-1 artifact layout
  - D-33 notebook deferred; FINDINGS.md is the sole headline deliverable
  - D-34 FINDINGS section set aligned to user-spec 8 sections (still ≥80 lines)
metrics:
  started_at: "2026-04-21T21:07:00Z"
  completed_at: "2026-04-21T21:20:00Z"
  duration_minutes: 13
  tasks_completed: 2
  files_touched: 7
  tests_added: 8
---

# Phase 8 Plan 3: LLM-as-Judge + Paired Statistical Analysis — Summary

**One-liner:** `gpt-4o-mini` paired-judge over 30 citation-grounded questions with deterministic `citation_coverage` cross-check and scipy Wilcoxon + bootstrap CI analysis, producing `eval/FINDINGS.md`.

## What shipped

1. **`eval/score.py`** (428 lines, live-tested) — paired LLM-as-judge with strict JSON schema (08-RESEARCH Pattern 1), per-question deterministic A/B ordering (`sha256(question_id) % 2`), `deterministic_citation_coverage()` computed from `tool_calls` surfaces (D-19 / Pattern 5), resume-safe via `{run_dir}/scores.jsonl`, and Anti-Pattern 7 honoured (`gold_answer_keywords` NEVER reaches the judge — asserted by `test_score_question_with_mocked_openai_client`).
2. **`eval/analyze.py`** (~400 lines) — `paired_deltas`, `summarize_condition`, `wilcoxon_test_four_dims` (two-sided AND one-sided "greater" per dimension, with 95% bootstrap CIs and rank-biserial effect sizes), `deterministic_agreement` (Spearman + Pearson + exact-bucket + Pitfall-8 trigger), `by_question_type` stratification, and `render_findings` (9-section markdown renderer).
3. **`eval/FINDINGS.md`** (118 lines, 9 H2 sections) — committed. Headline: `with_tools` outperforms `title_only` on all 4 dimensions at one-sided p ≈ 3×10⁻⁸, rank-biserial r = 1.0 on every dimension, judge ↔ deterministic Spearman ρ = 0.992.
4. **`tests/test_eval.py`** — **+8 tests** (4 score + 4 analyze):
   - `test_score_rubric_parse_rejects_malformed_judge_json` — non-JSON, out-of-range, non-int dim, missing answer_b all raise correctly.
   - `test_score_deterministic_citation_coverage_arithmetic` — |gold ∩ tool_call_ids|/|gold|, covering `arxiv_id_hit`, `arguments.arxiv_id`, `arguments.paper_id`, and `arguments.id` surfaces plus empty edges.
   - `test_score_question_with_mocked_openai_client` — D-24 mock flow; asserts `gold_answer_keywords` NOT in prompt, `response_format.type=="json_schema"`, `strict=True`, `temperature=0.0`, `seed=42`, `model=="gpt-4o-mini"`.
   - `test_score_run_resume_skips_done_questions` — D-14 resume logic; confirms no extra judge calls for already-done questions.
   - `test_analyze_aggregation_hand_computed` — paired_deltas + summarize_condition math on hand-worked example.
   - `test_analyze_wilcoxon_wrapper_all_zero_and_uniform_improvement` — zero-delta degrades to p=1 (not a crash), uniform +1 improvement at n=10 reaches p<0.05 (guards against silent wrapper bugs).
   - `test_analyze_deterministic_agreement_perfect_and_reversed` — ρ=+1 / −1 on rank-perfect/reversed data.
   - `test_analyze_render_findings_has_all_required_sections` — ≥80 lines, all 9 section headers, "Wilcoxon" and "deterministic" substrings present.

   Full test suite: **18 passing** (10 pre-existing + 4 from this plan's score half + 4 from analyze half), 1 deselected pre-existing failure documented in `deferred-items.md`.

## Live judge run stats

- **30 judge calls** on `gpt-4o-mini` (single call per question, both answers A/B per call)
- **Tokens:** prompt = 164,774 · completion = 8,128 · total = 172,902
- **Cost:** ≈ $0.0296 (well under the $0.50 budget in the user instructions)
- **Errors:** 0 / 30
- **Judge `system_fingerprint`** stable at `fp_a64aa7d0ff` across the full run (D-25 reproducibility — no mid-run model drift)

## Headline result (for STATE.md + downstream reading)

From `eval/FINDINGS.md` §5:

| dimension | n | median Δ | mean Δ | 95% CI | p (one-sided greater) | rank-biserial r |
|---|---|---|---|---|---|---|
| answer_correctness | 30 | 4.000 | 3.933 | [3.800, 4.000] | 3.40×10⁻⁸ | 1.000 |
| faithfulness       | 30 | 4.000 | 3.967 | [3.900, 4.000] | 3.40×10⁻⁸ | 1.000 |
| citation_coverage  | 30 | 4.000 | 3.900 | [3.767, 4.000] | 7.20×10⁻⁸ | 1.000 |
| completeness       | 30 | 4.000 | 3.967 | [3.900, 4.000] | 3.40×10⁻⁸ | 1.000 |

All `title_only` answers score 1.0 ± 0.0 on every dimension (the judge uniformly floored them — which is consistent with their "the abstract does not contain that information, I cannot answer" pattern observed in the Phase A manual sanity check). `with_tools` averages ~4.9/5 on every dimension. Rank-biserial r = 1.0 on all dimensions means **every single paired observation favoured `with_tools`** — no ties, no reversals.

## Judge-vs-deterministic trust metric

- Judge `citation_coverage` (1-5) vs deterministic `citation_coverage` (0-1): Spearman ρ = **0.992** (p = 2.07×10⁻⁵³)
- Exact-bucket match = **93.3%** (56/60)
- Direction agreement (judge ≥4 ↔ det ≥0.5) = **93.3%**
- Bucket disagreement > 1 (Pitfall 8 trigger) = **6.7%** — well below the 20% Pitfall-8 threshold

Pitfall 8 **NOT triggered**. Judge is trusted on citation_coverage.

## Rows where judge and deterministic disagreed by more than 1 rubric bucket

All on the `with_tools` condition (title_only is always judge=1, det=0 → always bucket-1 == bucket-1 agreement):

| question_id | condition  | judge | det  | interpretation |
|---|---|---|---|---|
| Q004 | with_tools | 4 | 0.25 | Judge read the narrative as well-cited but only 1/4 gold IDs were directly tool-called |
| Q010 | with_tools | 4 | 0.20 | Same pattern — prose cites the gold set but tool_calls hit a subset |
| Q013 | with_tools | 4 | 0.20 | Ditto |
| Q016 | with_tools | 5 | 0.20 | Largest gap — judge gave max while only 1/5 golds were tool-called |

These 4 rows suggest the judge can be tricked into high `citation_coverage` when an answer *mentions* gold arxiv IDs in prose even if the agent never actually fetched them. Future work: include tool_call **argument** detail in the judge prompt, not just `name` + `arxiv_id_hit`.

## Deviations from plan (PLAN.md 08-03)

- **D-32 (path realignment):** Plan wrote flat `eval/results/{runs,scores}.jsonl`; reality (Wave 1 artifacts) uses `{run_dir}/{with_tools,title_only}/rows.jsonl`. Updated `score.py` + `analyze.py` to consume per-run directories and write `{run_dir}/scores.jsonl`. This is strictly a better design — it supports multiple co-existing experiment runs without file-name collisions.
- **D-33 (notebook deferred):** Plan Task 3 specified a matplotlib notebook (`eval/notebook/eval_analysis.ipynb`) with ≥4 figures. User's explicit Wave-2 deliverable list omitted the notebook. Deferred, not cancelled — the analyze module exposes enough public API (`paired_deltas`, `wilcoxon_test_four_dims`, `summarize_condition`, `deterministic_agreement`) for a reviewer to drop in a notebook later in ~30 min.
- **D-34 (8 sections, not 10):** FINDINGS.md ships with 8 mandated sections (plus a Latency & Cost section folded into the §7 slot and Reproducibility Notes at §9). Still ≥80 lines, still covers all D-20 intent, and the Limitations section specifically calls out the n=30 / |Δ|≥0.4 power constraint.

All three deviations are documented in `08-CONTEXT.md` as D-32/D-33/D-34 in the Wave 2 refinements block.

## Phase 8 rollup — requirement status

| Requirement | Status | Evidence |
|---|---|---|
| EVAL-01 | ✓ Complete (Wave 0) | `eval/questions.json` (30 q, 10/10/10 stratified; commit d9c2ea9) |
| EVAL-02 | ✓ Complete (Wave 1) | `eval/run_eval.py` + `eval/results/run_20260421_201456/{with_tools,title_only}/rows.jsonl`; commit 4752d1c |
| EVAL-03 | ✓ Complete (Wave 2) | `eval/score.py` + `{run_dir}/scores.jsonl`; commit dc5d2cf |
| EVAL-04 | ✓ Complete (Wave 2, modulo D-33 notebook) | `eval/analyze.py` + `eval/FINDINGS.md`; commit 9414eb6 |

## Known Stubs

None. `with_tools` data flows real tool_call records end-to-end into `deterministic_citation_coverage`; `title_only` has `tool_calls=[]` by construction (not a stub — that's the definitional contrast being measured).

## Self-Check: PASSED

- `eval/score.py` exists, 428 lines, imports succeed: FOUND
- `eval/analyze.py` exists, imports succeed, `from scipy.stats import wilcoxon` present: FOUND
- `eval/FINDINGS.md` exists, 118 lines, 9 H2 sections, contains "Wilcoxon" and "deterministic": FOUND
- `eval/results/run_20260421_201456/scores.jsonl` exists, 60 rows (30 with_tools + 30 title_only), 0 errors: FOUND (gitignored per D-29)
- Commit `dc5d2cf` (feat(08-03) scorer): FOUND on master
- Commit `9414eb6` (feat(08-03) FINDINGS.md + analyze): FOUND on master
- `pytest tests/test_eval.py` (minus the one pre-existing failure): 18 passed / 1 deselected
