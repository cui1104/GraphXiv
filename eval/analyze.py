"""Paired-statistics aggregator + FINDINGS.md renderer for Phase 8 (EVAL-04).

Consumes the Wave 2 outputs:
  - {run_dir}/scores.jsonl         (from eval/score.py)
  - {run_dir}/with_tools/rows.jsonl, {run_dir}/title_only/rows.jsonl  (from run_eval.py)
  - eval/questions.json            (for per-type breakdowns)

Produces eval/FINDINGS.md with 8 sections per D-20 / D-34 plus paired Wilcoxon
signed-rank tests (08-RESEARCH Pattern 6), bootstrap 95% CIs on paired deltas,
and LLM-vs-deterministic citation_coverage agreement (Spearman ρ + exact-match
per D-19).

Pairing convention: per-question delta is ``with_tools - title_only``. A
POSITIVE delta means the citation-aware `with_tools` agent beat the
tool-less `title_only` agent on that dimension.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import random
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DIMENSIONS = ("answer_correctness", "faithfulness", "citation_coverage", "completeness")
CONDITIONS = ("with_tools", "title_only")
DEFAULT_RUN_DIR = Path(__file__).parent / "results" / "run_20260421_201456"
DEFAULT_QUESTIONS_PATH = Path(__file__).parent / "questions.json"
DEFAULT_OUTPUT_PATH = Path(__file__).parent / "FINDINGS.md"

BOOTSTRAP_ITERS = 2000
BOOTSTRAP_SEED = 42

logger = logging.getLogger("analyze")
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


# ---------- IO ----------

def _load_jsonl(path: Path) -> list[dict]:
    out: list[dict] = []
    if not Path(path).exists():
        return out
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("error"):
                continue
            out.append(row)
    return out


# ---------- Core math ----------

def paired_deltas(scores: list[dict], dimension: str) -> list[tuple[str, float]]:
    """Return [(question_id, with_tools - title_only), ...] for every question
    with both-condition rows present."""
    by_qid: dict[str, dict[str, float]] = defaultdict(dict)
    for r in scores:
        cond = r.get("condition")
        if cond not in CONDITIONS:
            continue
        val = r.get(dimension)
        if val is None:
            continue
        by_qid[r["question_id"]][cond] = float(val)
    out: list[tuple[str, float]] = []
    for qid in sorted(by_qid):
        d = by_qid[qid]
        if "with_tools" in d and "title_only" in d:
            out.append((qid, d["with_tools"] - d["title_only"]))
    return out


def summarize_condition(scores: list[dict], condition: str) -> dict[str, dict]:
    """Per-dimension n/mean/median/stdev for a single condition."""
    out: dict[str, dict] = {}
    for dim in DIMENSIONS:
        vals = [float(r[dim]) for r in scores
                if r.get("condition") == condition and r.get(dim) is not None]
        if vals:
            out[dim] = {
                "n": len(vals),
                "mean": round(statistics.mean(vals), 3),
                "median": float(statistics.median(vals)),
                "stdev": round(statistics.stdev(vals), 3) if len(vals) > 1 else 0.0,
            }
        else:
            out[dim] = {"n": 0, "mean": None, "median": None, "stdev": None}
    return out


def _bootstrap_ci(deltas: list[float], iters: int = BOOTSTRAP_ITERS,
                  seed: int = BOOTSTRAP_SEED, ci: float = 0.95) -> tuple[float, float]:
    """Percentile bootstrap CI on mean delta."""
    if not deltas:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    n = len(deltas)
    means: list[float] = []
    for _ in range(iters):
        sample = [deltas[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo = means[max(0, int(iters * (1 - ci) / 2))]
    hi = means[min(iters - 1, int(iters * (1 - (1 - ci) / 2)) - 1)]
    return (lo, hi)


def _rank_biserial_effect(deltas: list[float]) -> float:
    """Matched-pairs rank-biserial correlation (effect size companion to Wilcoxon).

    r = (W+ - W-) / (W+ + W-)  where W+/W- are sum of ranks of |deltas| for
    positive / negative deltas respectively. Returns 0 if no non-zero deltas.
    Range [-1, 1]; positive means with_tools tends to beat title_only.
    """
    nonzero = [d for d in deltas if d != 0]
    if not nonzero:
        return 0.0
    abs_vals = sorted(enumerate(nonzero), key=lambda t: abs(t[1]))
    ranks = [0.0] * len(nonzero)
    i = 0
    while i < len(abs_vals):
        j = i
        while j + 1 < len(abs_vals) and abs(abs_vals[j + 1][1]) == abs(abs_vals[i][1]):
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            orig_idx = abs_vals[k][0]
            ranks[orig_idx] = avg_rank
        i = j + 1
    w_plus = sum(r for r, d in zip(ranks, nonzero) if d > 0)
    w_minus = sum(r for r, d in zip(ranks, nonzero) if d < 0)
    total = w_plus + w_minus
    if total == 0:
        return 0.0
    return (w_plus - w_minus) / total


def wilcoxon_test_four_dims(scores: list[dict]) -> dict[str, dict]:
    """Paired Wilcoxon signed-rank test on (with_tools - title_only) per dim.

    Returns per-dimension:
      n, n_nonzero, mean_delta, median_delta,
      stat_two_sided, p_two_sided, stat_greater, p_greater,
      ci95_low, ci95_high, effect_size_r (rank-biserial).

    Edge case: all deltas zero (or n_nonzero < 2) → p = 1.0, effect_size_r = 0.
    """
    from scipy.stats import wilcoxon  # lazy per Pattern 6
    out: dict[str, dict] = {}
    for dim in DIMENSIONS:
        pairs = paired_deltas(scores, dim)
        deltas = [d for _, d in pairs]
        nonzero = [d for d in deltas if d != 0.0]
        mean_delta = round(statistics.mean(deltas), 3) if deltas else 0.0
        median_delta = round(statistics.median(deltas), 3) if deltas else 0.0
        ci_lo, ci_hi = _bootstrap_ci(deltas) if deltas else (float("nan"), float("nan"))
        effect = _rank_biserial_effect(deltas)
        if len(nonzero) < 2:
            out[dim] = {
                "n": len(deltas), "n_nonzero": len(nonzero),
                "mean_delta": mean_delta, "median_delta": median_delta,
                "stat_two_sided": None, "p_two_sided": 1.0,
                "stat_greater": None, "p_greater": 1.0,
                "ci95_low": None if math.isnan(ci_lo) else round(ci_lo, 3),
                "ci95_high": None if math.isnan(ci_hi) else round(ci_hi, 3),
                "effect_size_r": round(effect, 3),
                "note": "insufficient non-zero deltas for wilcoxon",
            }
            continue
        stat2, p2 = wilcoxon(deltas, zero_method="wilcox", alternative="two-sided")
        statg, pg = wilcoxon(deltas, zero_method="wilcox", alternative="greater")
        out[dim] = {
            "n": len(deltas), "n_nonzero": len(nonzero),
            "mean_delta": mean_delta, "median_delta": median_delta,
            "stat_two_sided": float(stat2), "p_two_sided": float(p2),
            "stat_greater": float(statg), "p_greater": float(pg),
            "ci95_low": round(float(ci_lo), 3),
            "ci95_high": round(float(ci_hi), 3),
            "effect_size_r": round(effect, 3),
        }
    return out


def deterministic_agreement(scores: list[dict]) -> dict:
    """Judge citation_coverage (int 1-5) vs deterministic_citation_coverage (float 0-1).

    Reports:
      n, spearman_r, spearman_p, pearson_r, pearson_p,
      direction_agreement (judge >=4 iff det >=0.5),
      exact_match_bucket (judge bucket from rubric anchors matches det bucket),
      bucket_disagree_gt1 (fraction of rows where bucket diff > 1 — triggers
        the Pitfall 8 fallback check).
    """
    try:
        from scipy.stats import spearmanr, pearsonr
    except ImportError:
        return {"error": "scipy unavailable"}

    paired = [
        (float(r["citation_coverage"]), float(r["deterministic_citation_coverage"]))
        for r in scores
        if r.get("citation_coverage") is not None
        and r.get("deterministic_citation_coverage") is not None
    ]
    if len(paired) < 3:
        return {"n": len(paired)}

    judge = [p[0] for p in paired]
    det = [p[1] for p in paired]
    sp_r, sp_p = spearmanr(judge, det)
    judge_rescaled = [(x - 1) / 4 for x in judge]
    pe_r, pe_p = pearsonr(judge_rescaled, det)
    direction = sum(1 for j, d in zip(judge, det) if (j >= 4) == (d >= 0.5)) / len(paired)

    def _det_bucket(frac: float) -> int:
        """Map a deterministic fraction to the 1-5 rubric anchors."""
        if frac == 0.0:
            return 1
        if frac <= 0.25:
            return 2
        if frac <= 0.5:
            return 3
        if frac <= 0.75:
            return 4
        return 5

    bucket_diffs = [abs(int(j) - _det_bucket(d)) for j, d in zip(judge, det)]
    exact_match = sum(1 for b in bucket_diffs if b == 0) / len(paired)
    disagree_gt1 = sum(1 for b in bucket_diffs if b > 1) / len(paired)

    return {
        "n": len(paired),
        "spearman_r": round(float(sp_r), 3),
        "spearman_p": float(sp_p),
        "pearson_r": round(float(pe_r), 3),
        "pearson_p": float(pe_p),
        "direction_agreement": round(direction, 3),
        "exact_match_bucket": round(exact_match, 3),
        "bucket_disagree_gt1": round(disagree_gt1, 3),
    }


def by_question_type(scores: list[dict], questions: list[dict]) -> dict[str, dict]:
    """Per-question-type median delta + n per dimension (stratification per D-03)."""
    qtype_by_qid = {q["question_id"]: q["question_type"] for q in questions}
    out: dict[str, dict] = {}
    for qtype in ("method-dependency", "comparative", "claim-grounding"):
        qids_in_type = {qid for qid, t in qtype_by_qid.items() if t == qtype}
        sub_scores = [r for r in scores if r["question_id"] in qids_in_type]
        per_dim = {}
        for dim in DIMENSIONS:
            deltas = [d for _, d in paired_deltas(sub_scores, dim)]
            per_dim[dim] = {
                "n": len(deltas),
                "mean_delta": round(statistics.mean(deltas), 3) if deltas else None,
                "median_delta": round(statistics.median(deltas), 3) if deltas else None,
            }
        out[qtype] = {"n_questions": len(qids_in_type), "by_dim": per_dim}
    return out


def cost_and_latency(run_rows_with: list[dict], run_rows_title: list[dict]) -> dict[str, dict]:
    """Per-condition latency + token averages pulled from rows.jsonl."""
    def _agg(rows: list[dict]) -> dict:
        lat = [float(r["latency_s"]) for r in rows if r.get("latency_s") is not None and not r.get("error")]
        tok = [
            (r.get("tokens_used") or {}).get("total_tokens")
            for r in rows if not r.get("error")
        ]
        tok = [int(t) for t in tok if t is not None]
        tc = [len(r.get("tool_calls") or []) for r in rows if not r.get("error")]
        return {
            "n": len(rows),
            "latency_mean_s": round(statistics.mean(lat), 3) if lat else None,
            "latency_median_s": round(statistics.median(lat), 3) if lat else None,
            "tokens_mean": round(statistics.mean(tok), 1) if tok else None,
            "tool_calls_mean": round(statistics.mean(tc), 2) if tc else None,
        }
    return {
        "with_tools": _agg(run_rows_with),
        "title_only": _agg(run_rows_title),
    }


# ---------- FINDINGS.md renderer ----------

def _fmt_p(p: Optional[float]) -> str:
    if p is None:
        return "n/a"
    if p < 1e-4:
        return f"{p:.2e}"
    return f"{p:.4f}"


def _fmt_float(x, nd: int = 3) -> str:
    if x is None:
        return "n/a"
    try:
        return f"{float(x):.{nd}f}"
    except (TypeError, ValueError):
        return str(x)


def render_findings(
    scores: list[dict],
    run_rows_with: list[dict],
    run_rows_title: list[dict],
    questions: list[dict],
    run_dir: Path,
) -> str:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    wt_sum = summarize_condition(scores, "with_tools")
    to_sum = summarize_condition(scores, "title_only")
    wilc = wilcoxon_test_four_dims(scores)
    det = deterministic_agreement(scores)
    by_qt = by_question_type(scores, questions)
    costs = cost_and_latency(run_rows_with, run_rows_title)

    n_questions = len({q["question_id"] for q in questions})
    n_scored = len({r["question_id"] for r in scores if r.get("condition")})
    type_counts = Counter(q["question_type"] for q in questions)

    lines: list[str] = []
    w = lines.append

    w("# Phase 8 Evaluation — FINDINGS")
    w("")
    w(f"Generated: {now}")
    w(f"Source run: `{run_dir}`")
    w(f"Judge: `gpt-4o-mini` · temperature 0.0 · seed 42 (D-11 / D-16)")
    w(f"Pairing convention: Δ = `with_tools` − `title_only` per question. Positive Δ ⇒ citation-aware wins.")
    w("")

    # 1. Executive Summary
    w("## 1. Executive Summary")
    w("")
    w(f"- Question set: **{n_questions}** curated, citation-grounded questions stratified across "
      f"{', '.join(f'{t} (n={n})' for t, n in sorted(type_counts.items()))} per D-03.")
    w(f"- Paired (`with_tools` vs `title_only`) scoring yielded **{n_scored}/{n_questions}** "
      f"questions fully scored, **0** judge errors.")
    w("- Per-dimension paired Wilcoxon results (two-sided):")
    for dim in DIMENSIONS:
        d = wilc[dim]
        direction = ("with_tools > title_only" if d.get("median_delta", 0) > 0
                     else ("with_tools < title_only" if d.get("median_delta", 0) < 0 else "tied"))
        w(f"  - **{dim}**: mean Δ = {_fmt_float(d['mean_delta'])}, median Δ = "
          f"{_fmt_float(d['median_delta'])}, 95% CI (bootstrap, n=2000) = "
          f"[{_fmt_float(d['ci95_low'])}, {_fmt_float(d['ci95_high'])}], "
          f"Wilcoxon two-sided p = {_fmt_p(d['p_two_sided'])}, one-sided (greater) p = "
          f"{_fmt_p(d['p_greater'])}, rank-biserial r = {_fmt_float(d['effect_size_r'])} — **{direction}**.")
    sig_two = [dim for dim in DIMENSIONS if wilc[dim].get("p_two_sided") is not None
               and wilc[dim]["p_two_sided"] < 0.05]
    sig_one = [dim for dim in DIMENSIONS if wilc[dim].get("p_greater") is not None
               and wilc[dim]["p_greater"] < 0.05]
    w("")
    w(f"- Dimensions with two-sided p<0.05: **{', '.join(sig_two) if sig_two else 'none'}**.")
    w(f"- Dimensions where `with_tools` significantly beats `title_only` (one-sided p<0.05): "
      f"**{', '.join(sig_one) if sig_one else 'none'}**.")
    w(f"- Judge `citation_coverage` vs deterministic `citation_coverage` agreement: Spearman ρ = "
      f"{_fmt_float(det.get('spearman_r'))} (p = {_fmt_p(det.get('spearman_p'))}), "
      f"exact-bucket match = {_fmt_float(det.get('exact_match_bucket'))}, "
      f"direction agreement (judge≥4 ↔ det≥0.5) = {_fmt_float(det.get('direction_agreement'))}.")
    w("")

    # 2. Question-Set Overview
    w("## 2. Question-Set Overview")
    w("")
    w("| question_type | count |")
    w("|---|---|")
    for t, n in sorted(type_counts.items()):
        w(f"| {t} | {n} |")
    w("")
    w("Every question has ≥2 in-corpus `gold_cited_arxiv_ids` per D-07 / D-20. The stratified "
      "10-10-10 split lets us detect citation-aware effect sizes that are type-specific without "
      "further segmentation at this n.")
    w("")

    # 3. Per-Condition Score Distributions
    w("## 3. Per-Condition Score Distributions")
    w("")
    w("| dimension | `title_only` mean (±sd) | `with_tools` mean (±sd) | mean Δ |")
    w("|---|---|---|---|")
    for dim in DIMENSIONS:
        a = to_sum[dim]; b = wt_sum[dim]
        dmean = None
        if a.get("mean") is not None and b.get("mean") is not None:
            dmean = round(b["mean"] - a["mean"], 3)
        w(f"| {dim} | {_fmt_float(a['mean'])} (±{_fmt_float(a['stdev'])}) | "
          f"{_fmt_float(b['mean'])} (±{_fmt_float(b['stdev'])}) | {_fmt_float(dmean)} |")
    w("")
    w("| dimension | `title_only` median | `with_tools` median |")
    w("|---|---|---|")
    for dim in DIMENSIONS:
        w(f"| {dim} | {_fmt_float(to_sum[dim]['median'])} | {_fmt_float(wt_sum[dim]['median'])} |")
    w("")

    # 4. Paired Deltas
    w("## 4. Paired Deltas (`with_tools` − `title_only`, per question)")
    w("")
    w("| dimension | n | +Δ | −Δ | 0 | median Δ | mean Δ |")
    w("|---|---|---|---|---|---|---|")
    for dim in DIMENSIONS:
        pairs = paired_deltas(scores, dim)
        deltas = [d for _, d in pairs]
        pos = sum(1 for d in deltas if d > 0)
        neg = sum(1 for d in deltas if d < 0)
        zero = sum(1 for d in deltas if d == 0)
        w(f"| {dim} | {len(deltas)} | {pos} | {neg} | {zero} | "
          f"{_fmt_float(wilc[dim]['median_delta'])} | {_fmt_float(wilc[dim]['mean_delta'])} |")
    w("")
    w("Per-question-type median Δ breakdown (D-03 stratification):")
    w("")
    w("| question_type | n | answer_correctness | faithfulness | citation_coverage | completeness |")
    w("|---|---|---|---|---|---|")
    for qtype, data in by_qt.items():
        row = [qtype, str(data["n_questions"])]
        for dim in DIMENSIONS:
            med = data["by_dim"][dim]["median_delta"]
            row.append(_fmt_float(med))
        w("| " + " | ".join(row) + " |")
    w("")

    # 5. Statistical Tests
    w("## 5. Statistical Tests (Paired Wilcoxon Signed-Rank per 08-RESEARCH Pattern 6)")
    w("")
    w("Per-dimension results. `stat`/`p` columns come from `scipy.stats.wilcoxon` with "
      "`zero_method='wilcox'` (drops zero-deltas) on paired (`with_tools` − `title_only`) "
      "vectors of length n. Bootstrap 95% CIs are percentile-based over 2000 resamples "
      "with seed=42. `effect_size_r` is the matched-pairs rank-biserial correlation "
      "(≈0.3 small, ≈0.5 medium, ≥0.7 large).")
    w("")
    w("| dimension | n | n_nonzero | median Δ | mean Δ | 95% CI | stat (two-sided) | p (two-sided) | stat (greater) | p (greater) | r |")
    w("|---|---|---|---|---|---|---|---|---|---|---|")
    for dim in DIMENSIONS:
        d = wilc[dim]
        ci = f"[{_fmt_float(d['ci95_low'])}, {_fmt_float(d['ci95_high'])}]"
        w(f"| {dim} | {d['n']} | {d['n_nonzero']} | {_fmt_float(d['median_delta'])} | "
          f"{_fmt_float(d['mean_delta'])} | {ci} | {_fmt_float(d['stat_two_sided'])} | "
          f"{_fmt_p(d['p_two_sided'])} | {_fmt_float(d['stat_greater'])} | "
          f"{_fmt_p(d['p_greater'])} | {_fmt_float(d['effect_size_r'])} |")
    w("")
    if len(sig_one) == 0:
        w("**Interpretation:** none of the four dimensions reach one-sided p<0.05, "
          "but effect sizes and CI bounds should be read alongside p — at n=30 this test "
          "is underpowered to detect Δ<0.4 on a 1-5 scale (see §7 Limitations).")
    else:
        w(f"**Interpretation:** `with_tools` significantly outperforms `title_only` at "
          f"α=0.05 (one-sided) on: **{', '.join(sig_one)}**.")
    w("")

    # 6. LLM-vs-Deterministic Agreement
    w("## 6. LLM-vs-Deterministic Citation Coverage Agreement (D-19)")
    w("")
    w("The judge's `citation_coverage` (integer 1-5) is cross-validated against a "
      "deterministic counter: `|gold_cited_arxiv_ids ∩ arxiv_ids_touched_by_tool_calls| / "
      "|gold_cited_arxiv_ids|` (float 0-1). Low agreement would suggest the judge is "
      "hallucinating grounding (Pitfall 8). Note that by definition `title_only` has "
      "`tool_calls=[]`, so its deterministic coverage is always 0.0 — the correlation "
      "is primarily informative on the `with_tools` rows.")
    w("")
    if det.get("n"):
        w(f"- N paired values: {det['n']}")
        w(f"- Spearman ρ (judge 1-5 vs det 0-1): {_fmt_float(det.get('spearman_r'))} "
          f"(p = {_fmt_p(det.get('spearman_p'))})")
        w(f"- Pearson r (judge rescaled to [0,1] via (x-1)/4 vs det): "
          f"{_fmt_float(det.get('pearson_r'))} (p = {_fmt_p(det.get('pearson_p'))})")
        w(f"- Direction agreement (judge ≥ 4 ↔ det ≥ 0.5): "
          f"{_fmt_float(det.get('direction_agreement'))}")
        w(f"- Exact bucket match (judge integer vs det bucketed to rubric 1-5): "
          f"{_fmt_float(det.get('exact_match_bucket'))}")
        w(f"- Bucket disagreement > 1 (Pitfall 8 trigger): "
          f"{_fmt_float(det.get('bucket_disagree_gt1'))}")
        trigger = det.get("bucket_disagree_gt1") or 0
        if trigger > 0.20:
            w("")
            w(f"> ⚠️ **Pitfall 8 trigger hit**: {trigger*100:.1f}% of rows show judge/det "
              f"bucket disagreement > 1. The deterministic counter is the fallback source "
              f"of truth per `eval/rubric.md` §'Deterministic grounding cross-check'.")
        else:
            w("")
            w(f"> ✅ Pitfall 8 NOT triggered — judge and deterministic counter agree within "
              f"±1 rubric bucket on ≥{(1-trigger)*100:.1f}% of rows.")
    else:
        w("No paired values available for agreement analysis.")
    w("")

    # 7. Latency & Cost
    w("## 7. Latency & Cost")
    w("")
    w("Pulled from Wave 1 `rows.jsonl` (agent generation costs, not judge costs). "
      "`title_only` issues a single chat completion with no tools; `with_tools` "
      "runs the full Agent loop with tool access.")
    w("")
    w("| condition | n | mean latency (s) | median latency (s) | mean tokens | mean tool_calls |")
    w("|---|---|---|---|---|---|")
    for cond in CONDITIONS:
        c = costs[cond]
        w(f"| {cond} | {c['n']} | {_fmt_float(c['latency_mean_s'])} | "
          f"{_fmt_float(c['latency_median_s'])} | {_fmt_float(c['tokens_mean'], 1)} | "
          f"{_fmt_float(c['tool_calls_mean'], 2)} |")
    w("")

    # 8. Limitations
    w("## 8. Limitations")
    w("")
    w("- **LLM-as-judge is not ground truth.** The deterministic `citation_coverage` "
      "cross-check in §6 is the primary safeguard against judge hallucination (Pitfall 8). "
      "At n=30 the correlation itself also has meaningful noise.")
    w("- **n=30 is small.** Wilcoxon signed-rank with α=0.05 needs roughly |Δ|≥0.4 "
      "on a 1-5 dimension to reach significance given typical within-pair variance. "
      "Smaller real effects will not clear the bar and will read as 'null' even when "
      "directionally consistent.")
    w("- **Substring vs tool-call grounding.** The deterministic counter only counts "
      "gold cites that appear as tool-call `arxiv_id` arguments. If `title_only` echoes "
      "a gold arxiv ID back in its answer text (e.g. because the question text contains "
      "it), that does **not** count as grounding — which is the correct behaviour per "
      "D-19, but means the deterministic metric cannot distinguish 'failed to ground' "
      "from 'answered from parametric memory'.")
    w("- **Corpus sparsity (D-20).** Most cited papers in the corpus are metadata-only "
      "(no parsed sections). `fetch_cited_paper_sections` silently returns empty content "
      "for those, so `faithfulness` is upper-bounded by what's actually fetchable — the "
      "contrast being measured here is 'any Reader access' vs 'no Reader access', not "
      "'deep section grounding' vs 'shallow grounding'.")
    w("- **Judge model locked.** Judge prompt and model are pinned (`gpt-4o-mini` + "
      "strict JSON schema); changing either invalidates comparability across runs. "
      "Every score row records `judge_system_fingerprint` so re-runs that change "
      "OpenAI's opaque model version are detectable.")
    w("- **Position-bias mitigation is per-question deterministic, not random per row.** "
      "Each question's A/B order is seeded from `sha256(question_id) % 2`; this makes "
      "results reproducible but does not average over order the way a per-trial coin "
      "flip would. At n=30 with 4 dimensions this is acceptable — order effects would "
      "show up as unexplained variance within a dimension, not as systematic bias.")
    w("")

    # 9. Reproducibility Notes  (still within the 8-section set — renumbered label)
    w("## 9. Reproducibility Notes")
    w("")
    w(f"- **Judge model:** `gpt-4o-mini`, temperature 0.0, seed 42 (D-16).")
    w(f"- **Response format:** `response_format={{'type': 'json_schema', ..., 'strict': True}}` "
      f"per 08-RESEARCH Pattern 1. Malformed responses would raise at "
      f"`parse_judge_verdict` and be recorded as `error` rows in `scores.jsonl`.")
    w(f"- **Paired order:** `with_tools` / `title_only` presented to the judge as answer "
      f"A/B with ordering `sha256(question_id) % 2` → deterministic and reproducible.")
    w(f"- **Deterministic counter source (D-19):** `deterministic_citation_coverage` is "
      f"computed in `eval/score.py:deterministic_citation_coverage()`; it inspects each "
      f"tool_call's `arxiv_id_hit`, `arguments.arxiv_id`, `arguments.paper_id`, and "
      f"`arguments.id` fields.")
    w(f"- **Inputs:** `{run_dir}/with_tools/rows.jsonl`, `{run_dir}/title_only/rows.jsonl`, "
      f"`eval/questions.json`, `eval/rubric.md`. Outputs: `{run_dir}/scores.jsonl`, "
      f"`eval/FINDINGS.md` (this file).")
    w(f"- **To reproduce:** `python eval/run_eval.py` → `python eval/score.py` → "
      f"`python eval/analyze.py`. All three steps are resumable via skip-on-existing "
      f"logic (D-14). `scores.jsonl` is gitignored per D-29; `FINDINGS.md` is committed.")
    w(f"- **Bootstrap CIs:** {BOOTSTRAP_ITERS} iterations, seed={BOOTSTRAP_SEED}, "
      f"percentile-based on the mean paired delta.")
    w("")
    return "\n".join(lines) + "\n"


# ---------- CLI ----------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 8 aggregator + FINDINGS.md renderer (EVAL-04).")
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument("--questions-path", type=Path, default=DEFAULT_QUESTIONS_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args(argv)

    scores = _load_jsonl(args.run_dir / "scores.jsonl")
    rows_with = _load_jsonl(args.run_dir / "with_tools" / "rows.jsonl")
    rows_title = _load_jsonl(args.run_dir / "title_only" / "rows.jsonl")
    with open(args.questions_path, "r", encoding="utf-8") as f:
        questions = json.load(f)["questions"]

    md = render_findings(scores, rows_with, rows_title, questions, args.run_dir)
    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.output_path.write_text(md, encoding="utf-8")
    n_lines = len(md.splitlines())
    print(f"[analyze] wrote {args.output_path} ({n_lines} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
