# Phase 8 Evaluation — FINDINGS

Generated: 2026-04-21T21:15:34Z
Source run: `/Users/henrycui/Desktop/DATS5990_final/eval/results/run_20260421_201456`
Judge: `gpt-4o-mini` · temperature 0.0 · seed 42 (D-11 / D-16)
Pairing convention: Δ = `with_tools` − `title_only` per question. Positive Δ ⇒ citation-aware wins.

## 1. Executive Summary

- Question set: **30** curated, citation-grounded questions stratified across claim-grounding (n=10), comparative (n=10), method-dependency (n=10) per D-03.
- Paired (`with_tools` vs `title_only`) scoring yielded **30/30** questions fully scored, **0** judge errors.
- Per-dimension paired Wilcoxon results (two-sided):
  - **answer_correctness**: mean Δ = 3.933, median Δ = 4.000, 95% CI (bootstrap, n=2000) = [3.800, 4.000], Wilcoxon two-sided p = 6.80e-08, one-sided (greater) p = 3.40e-08, rank-biserial r = 1.000 — **with_tools > title_only**.
  - **faithfulness**: mean Δ = 3.967, median Δ = 4.000, 95% CI (bootstrap, n=2000) = [3.900, 4.000], Wilcoxon two-sided p = 6.80e-08, one-sided (greater) p = 3.40e-08, rank-biserial r = 1.000 — **with_tools > title_only**.
  - **citation_coverage**: mean Δ = 3.900, median Δ = 4.000, 95% CI (bootstrap, n=2000) = [3.767, 4.000], Wilcoxon two-sided p = 1.44e-07, one-sided (greater) p = 7.20e-08, rank-biserial r = 1.000 — **with_tools > title_only**.
  - **completeness**: mean Δ = 3.967, median Δ = 4.000, 95% CI (bootstrap, n=2000) = [3.900, 4.000], Wilcoxon two-sided p = 6.80e-08, one-sided (greater) p = 3.40e-08, rank-biserial r = 1.000 — **with_tools > title_only**.

- Dimensions with two-sided p<0.05: **answer_correctness, faithfulness, citation_coverage, completeness**.
- Dimensions where `with_tools` significantly beats `title_only` (one-sided p<0.05): **answer_correctness, faithfulness, citation_coverage, completeness**.
- Judge `citation_coverage` vs deterministic `citation_coverage` agreement: Spearman ρ = 0.992 (p = 2.07e-53), exact-bucket match = 0.933, direction agreement (judge≥4 ↔ det≥0.5) = 0.933.

## 2. Question-Set Overview

| question_type | count |
|---|---|
| claim-grounding | 10 |
| comparative | 10 |
| method-dependency | 10 |

Every question has ≥2 in-corpus `gold_cited_arxiv_ids` per D-07 / D-20. The stratified 10-10-10 split lets us detect citation-aware effect sizes that are type-specific without further segmentation at this n.

## 3. Per-Condition Score Distributions

| dimension | `title_only` mean (±sd) | `with_tools` mean (±sd) | mean Δ |
|---|---|---|---|
| answer_correctness | 1.000 (±0.000) | 4.933 (±0.365) | 3.933 |
| faithfulness | 1.000 (±0.000) | 4.967 (±0.183) | 3.967 |
| citation_coverage | 1.000 (±0.000) | 4.900 (±0.305) | 3.900 |
| completeness | 1.000 (±0.000) | 4.967 (±0.183) | 3.967 |

| dimension | `title_only` median | `with_tools` median |
|---|---|---|
| answer_correctness | 1.000 | 5.000 |
| faithfulness | 1.000 | 5.000 |
| citation_coverage | 1.000 | 5.000 |
| completeness | 1.000 | 5.000 |

## 4. Paired Deltas (`with_tools` − `title_only`, per question)

| dimension | n | +Δ | −Δ | 0 | median Δ | mean Δ |
|---|---|---|---|---|---|---|
| answer_correctness | 30 | 30 | 0 | 0 | 4.000 | 3.933 |
| faithfulness | 30 | 30 | 0 | 0 | 4.000 | 3.967 |
| citation_coverage | 30 | 30 | 0 | 0 | 4.000 | 3.900 |
| completeness | 30 | 30 | 0 | 0 | 4.000 | 3.967 |

Per-question-type median Δ breakdown (D-03 stratification):

| question_type | n | answer_correctness | faithfulness | citation_coverage | completeness |
|---|---|---|---|---|---|
| method-dependency | 10 | 4.000 | 4.000 | 4.000 | 4.000 |
| comparative | 10 | 4.000 | 4.000 | 4.000 | 4.000 |
| claim-grounding | 10 | 4.000 | 4.000 | 4.000 | 4.000 |

## 5. Statistical Tests (Paired Wilcoxon Signed-Rank per 08-RESEARCH Pattern 6)

Per-dimension results. `stat`/`p` columns come from `scipy.stats.wilcoxon` with `zero_method='wilcox'` (drops zero-deltas) on paired (`with_tools` − `title_only`) vectors of length n. Bootstrap 95% CIs are percentile-based over 2000 resamples with seed=42. `effect_size_r` is the matched-pairs rank-biserial correlation (≈0.3 small, ≈0.5 medium, ≥0.7 large).

| dimension | n | n_nonzero | median Δ | mean Δ | 95% CI | stat (two-sided) | p (two-sided) | stat (greater) | p (greater) | r |
|---|---|---|---|---|---|---|---|---|---|---|
| answer_correctness | 30 | 30 | 4.000 | 3.933 | [3.800, 4.000] | 0.000 | 6.80e-08 | 465.000 | 3.40e-08 | 1.000 |
| faithfulness | 30 | 30 | 4.000 | 3.967 | [3.900, 4.000] | 0.000 | 6.80e-08 | 465.000 | 3.40e-08 | 1.000 |
| citation_coverage | 30 | 30 | 4.000 | 3.900 | [3.767, 4.000] | 0.000 | 1.44e-07 | 465.000 | 7.20e-08 | 1.000 |
| completeness | 30 | 30 | 4.000 | 3.967 | [3.900, 4.000] | 0.000 | 6.80e-08 | 465.000 | 3.40e-08 | 1.000 |

**Interpretation:** `with_tools` significantly outperforms `title_only` at α=0.05 (one-sided) on: **answer_correctness, faithfulness, citation_coverage, completeness**.

## 6. LLM-vs-Deterministic Citation Coverage Agreement (D-19)

The judge's `citation_coverage` (integer 1-5) is cross-validated against a deterministic counter: `|gold_cited_arxiv_ids ∩ arxiv_ids_touched_by_tool_calls| / |gold_cited_arxiv_ids|` (float 0-1). Low agreement would suggest the judge is hallucinating grounding (Pitfall 8). Note that by definition `title_only` has `tool_calls=[]`, so its deterministic coverage is always 0.0 — the correlation is primarily informative on the `with_tools` rows.

- N paired values: 60
- Spearman ρ (judge 1-5 vs det 0-1): 0.992 (p = 2.07e-53)
- Pearson r (judge rescaled to [0,1] via (x-1)/4 vs det): 0.951 (p = 2.78e-31)
- Direction agreement (judge ≥ 4 ↔ det ≥ 0.5): 0.933
- Exact bucket match (judge integer vs det bucketed to rubric 1-5): 0.933
- Bucket disagreement > 1 (Pitfall 8 trigger): 0.067

> ✅ Pitfall 8 NOT triggered — judge and deterministic counter agree within ±1 rubric bucket on ≥93.3% of rows.

## 7. Latency & Cost

Pulled from Wave 1 `rows.jsonl` (agent generation costs, not judge costs). `title_only` issues a single chat completion with no tools; `with_tools` runs the full Agent loop with tool access.

| condition | n | mean latency (s) | median latency (s) | mean tokens | mean tool_calls |
|---|---|---|---|---|---|
| with_tools | 30 | 24.015 | 18.992 | 26717.8 | 9.20 |
| title_only | 30 | 1.602 | 1.486 | 460.1 | 0.00 |

## 8. Limitations

- **LLM-as-judge is not ground truth.** The deterministic `citation_coverage` cross-check in §6 is the primary safeguard against judge hallucination (Pitfall 8). At n=30 the correlation itself also has meaningful noise.
- **n=30 is small.** Wilcoxon signed-rank with α=0.05 needs roughly |Δ|≥0.4 on a 1-5 dimension to reach significance given typical within-pair variance. Smaller real effects will not clear the bar and will read as 'null' even when directionally consistent.
- **Substring vs tool-call grounding.** The deterministic counter only counts gold cites that appear as tool-call `arxiv_id` arguments. If `title_only` echoes a gold arxiv ID back in its answer text (e.g. because the question text contains it), that does **not** count as grounding — which is the correct behaviour per D-19, but means the deterministic metric cannot distinguish 'failed to ground' from 'answered from parametric memory'.
- **Corpus sparsity (D-20).** Most cited papers in the corpus are metadata-only (no parsed sections). `fetch_cited_paper_sections` silently returns empty content for those, so `faithfulness` is upper-bounded by what's actually fetchable — the contrast being measured here is 'any Reader access' vs 'no Reader access', not 'deep section grounding' vs 'shallow grounding'.
- **Judge model locked.** Judge prompt and model are pinned (`gpt-4o-mini` + strict JSON schema); changing either invalidates comparability across runs. Every score row records `judge_system_fingerprint` so re-runs that change OpenAI's opaque model version are detectable.
- **Position-bias mitigation is per-question deterministic, not random per row.** Each question's A/B order is seeded from `sha256(question_id) % 2`; this makes results reproducible but does not average over order the way a per-trial coin flip would. At n=30 with 4 dimensions this is acceptable — order effects would show up as unexplained variance within a dimension, not as systematic bias.

## 9. Reproducibility Notes

- **Judge model:** `gpt-4o-mini`, temperature 0.0, seed 42 (D-16).
- **Response format:** `response_format={'type': 'json_schema', ..., 'strict': True}` per 08-RESEARCH Pattern 1. Malformed responses would raise at `parse_judge_verdict` and be recorded as `error` rows in `scores.jsonl`.
- **Paired order:** `with_tools` / `title_only` presented to the judge as answer A/B with ordering `sha256(question_id) % 2` → deterministic and reproducible.
- **Deterministic counter source (D-19):** `deterministic_citation_coverage` is computed in `eval/score.py:deterministic_citation_coverage()`; it inspects each tool_call's `arxiv_id_hit`, `arguments.arxiv_id`, `arguments.paper_id`, and `arguments.id` fields.
- **Inputs:** `/Users/henrycui/Desktop/DATS5990_final/eval/results/run_20260421_201456/with_tools/rows.jsonl`, `/Users/henrycui/Desktop/DATS5990_final/eval/results/run_20260421_201456/title_only/rows.jsonl`, `eval/questions.json`, `eval/rubric.md`. Outputs: `/Users/henrycui/Desktop/DATS5990_final/eval/results/run_20260421_201456/scores.jsonl`, `eval/FINDINGS.md` (this file).
- **To reproduce:** `python eval/run_eval.py` → `python eval/score.py` → `python eval/analyze.py`. All three steps are resumable via skip-on-existing logic (D-14). `scores.jsonl` is gitignored per D-29; `FINDINGS.md` is committed.
- **Bootstrap CIs:** 2000 iterations, seed=42, percentile-based on the mean paired delta.

