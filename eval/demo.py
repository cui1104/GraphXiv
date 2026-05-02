"""Side-by-side demo: baseline (title_only) vs citation-aware (with_tools).

Run a question through both conditions and pretty-print the contrast:

  python eval/demo.py --question-id Q001                  # replay cached
  python eval/demo.py --question-id Q015 --live           # run fresh via API
  python eval/demo.py --seed-arxiv-id 2602.07152 \
      --question "How does this paper's method extend prior work?" --live

Replay mode reads the Wave-1 rows under eval/results/run_*/ (no API cost,
instant). Live mode hits the running docker-compose api + OpenAI; set
OPENAI_API_KEY for that path.

This is a demo / inspection tool, not part of the eval pipeline. It does
NOT produce committable artifacts -- output is print-only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
import time
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "sdk"))

DEFAULT_RUN_DIR = _REPO_ROOT / "eval" / "results" / "run_20260421_201456"
DEFAULT_QUESTIONS = _REPO_ROOT / "eval" / "questions.json"
DEFAULT_BASE_URL = "http://localhost:8000"

# ---------- terminal helpers ----------

try:
    _TERM_W = max(60, min(140, os.get_terminal_size().columns))
except OSError:
    _TERM_W = 100


def _rule(char: str = "─", label: Optional[str] = None) -> str:
    if label:
        mid = f" {label} "
        pad = _TERM_W - len(mid)
        left = pad // 2
        right = pad - left
        return char * left + mid + char * right
    return char * _TERM_W


def _wrap(text: str, indent: str = "  ") -> str:
    out = []
    for para in text.splitlines() or [""]:
        if not para.strip():
            out.append("")
            continue
        out.extend(textwrap.wrap(para, width=_TERM_W - len(indent)) or [""])
    return "\n".join(indent + line for line in out)


# ---------- loaders ----------

def load_question(question_id: str) -> dict:
    with open(DEFAULT_QUESTIONS) as f:
        qs = json.load(f)["questions"]
    for q in qs:
        if q["question_id"] == question_id:
            return q
    raise SystemExit(
        f"no question {question_id} in {DEFAULT_QUESTIONS}. "
        f"Available: {', '.join(q['question_id'] for q in qs)}"
    )


def load_cached_rows(question_id: str, run_dir: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for cond in ("with_tools", "title_only"):
        p = run_dir / cond / "rows.jsonl"
        if not p.exists():
            continue
        with open(p) as f:
            for line in f:
                row = json.loads(line)
                if row.get("question_id") == question_id:
                    out[cond] = row
                    break
    return out


def load_cached_scores(question_id: str, run_dir: Path) -> dict[str, dict]:
    p = run_dir / "scores.jsonl"
    if not p.exists():
        return {}
    out: dict[str, dict] = {}
    with open(p) as f:
        for line in f:
            row = json.loads(line)
            if row.get("question_id") == question_id:
                out[row["condition"]] = row
    return out


# ---------- deterministic citation coverage (mirrors eval/score.py D-19) ----------

def deterministic_coverage(
    gold_cited_arxiv_ids: list[str],
    tool_calls: list[dict],
    answer_text: Optional[str],
) -> tuple[int, int, list[str]]:
    """Return (hits, total, hit_ids).

    A gold arxiv_id is counted as hit if it appears as a substring in any
    tool_call argument OR in the answer_text. Matches the deterministic
    cross-check used by eval/score.py.
    """
    hits: list[str] = []
    # Flatten haystack
    haystack_parts: list[str] = []
    if answer_text:
        haystack_parts.append(answer_text)
    for tc in tool_calls or []:
        args = tc.get("arguments")
        if isinstance(args, dict):
            haystack_parts.append(json.dumps(args))
        elif isinstance(args, str):
            haystack_parts.append(args)
        hit = tc.get("arxiv_id_hit")
        if hit:
            haystack_parts.append(hit)
    haystack = " ".join(haystack_parts).lower()
    for aid in gold_cited_arxiv_ids or []:
        if aid.lower() in haystack:
            hits.append(aid)
    return (len(hits), len(gold_cited_arxiv_ids or []), hits)


# ---------- live runners ----------

def run_live(question: dict, api_key: str, base_url: str) -> dict[str, dict]:
    """Execute both conditions fresh against the running services."""
    from eval import run_eval  # reuse the production runner

    print(_rule("━", "LIVE RUN"))
    out: dict[str, dict] = {}

    # title_only first (fast -- ~1.5s)
    t0 = time.time()
    print("\n[1/2] title_only (baseline, no tools)...", flush=True)
    title_out = run_eval.run_title_only(
        question,
        api_key=api_key,
        base_url=base_url,
    )
    print(f"      done in {time.time() - t0:.1f}s", flush=True)
    out["title_only"] = {
        "answer_text": title_out.answer_text,
        "tool_calls": [],
        "latency_s": title_out.latency_s,
        "tokens_used": title_out.usage,
        "error": title_out.error,
    }

    # with_tools (the star of the show -- ~15-30s)
    t0 = time.time()
    print("\n[2/2] with_tools (citation-aware agent)...", flush=True)
    tools_out = run_eval.run_with_tools(
        question,
        api_key=api_key,
        base_url=base_url,
    )
    print(f"      done in {time.time() - t0:.1f}s ({len(tools_out.tool_calls)} tool calls)", flush=True)
    out["with_tools"] = {
        "answer_text": tools_out.answer_text,
        "tool_calls": tools_out.tool_calls,
        "latency_s": tools_out.latency_s,
        "tokens_used": tools_out.usage,
        "error": tools_out.error,
    }
    return out


# ---------- seed info ----------

def fetch_seed_info(arxiv_id: str, base_url: str) -> dict:
    try:
        from deepxiv_sdk.reader import Reader
        reader = Reader(base_url=base_url)
        head = reader.head(arxiv_id) or {}
    except Exception as exc:
        return {"error": str(exc)}
    return {
        "title": head.get("title") or "",
        "abstract": (head.get("abstract") or "")[:400],
        "year": head.get("year"),
    }


# ---------- pretty-printers ----------

def print_header(q: dict, seed_info: dict, mode: str) -> None:
    print(_rule("═"))
    print(_rule(" ", f"DEEPXIV DEMO · {mode.upper()} "))
    print(_rule("═"))
    print()
    print(f"  question_id:   {q.get('question_id', '<free-form>')}")
    print(f"  question_type: {q.get('question_type', '<free-form>')}")
    print(f"  seed paper:    {q['seed_arxiv_id']}")
    title = seed_info.get("title")
    if title:
        print(f"                 \"{title[:100]}\"")
    gold = q.get("gold_cited_arxiv_ids") or []
    if gold:
        print(f"  gold cites:    {', '.join(gold)}   ({len(gold)} in-corpus)")
    print()
    print(_rule("─", "QUESTION"))
    print(_wrap(q["question_text"]))
    print()


def print_answer_block(cond_label: str, row: dict, gold: list[str], score_row: Optional[dict] = None) -> None:
    error = row.get("error")
    text = (row.get("answer_text") or "").strip()
    tool_calls = row.get("tool_calls") or []
    usage = row.get("tokens_used") or row.get("usage") or {}
    hits, total, hit_ids = deterministic_coverage(gold, tool_calls, text)
    # A cleaner signal: how many gold cites appear as an arxiv_id ARGUMENT to a
    # tool call (this only fires for the citation-aware agent; baseline can't
    # "cite via tool" since it has no tools).
    tool_hit_ids = [
        aid for aid in (gold or [])
        if any(
            (isinstance(tc.get("arguments"), dict) and aid in json.dumps(tc["arguments"]))
            or tc.get("arxiv_id_hit") == aid
            for tc in tool_calls
        )
    ]

    print(_rule("━", cond_label))

    # header metrics
    meta_parts = [
        f"latency={row.get('latency_s', 0):.2f}s",
        f"tokens={usage.get('total_tokens', 0)}",
        f"tool_calls={len(tool_calls)}",
    ]
    if tool_calls:
        # Agent condition: cites actually fetched through tools
        meta_parts.append(
            f"cites_fetched={len(tool_hit_ids)}/{total}"
            + (f" [{', '.join(tool_hit_ids)}]" if tool_hit_ids else "")
        )
    else:
        # Baseline condition: mentions in answer (noisy; the IDs are also in the question)
        meta_parts.append(
            f"cites_mentioned={hits}/{total}"
            + (f" [{', '.join(hit_ids)}]" if hit_ids else "")
        )
    if score_row:
        ac = score_row.get("answer_correctness")
        fa = score_row.get("faithfulness")
        cc = score_row.get("citation_coverage")
        co = score_row.get("completeness")
        if all(v is not None for v in (ac, fa, cc, co)):
            meta_parts.append(
                f"judge=[ac={ac} fa={fa} cc={cc} co={co}] (1-5 scale)"
            )
    print("  " + " | ".join(meta_parts))
    print()

    if tool_calls:
        print("  Tool trace:")
        for i, tc in enumerate(tool_calls, 1):
            args = tc.get("arguments", {})
            if isinstance(args, dict):
                # show the most useful arg
                arg_preview = ""
                for k in ("arxiv_id", "paper_id", "query", "id"):
                    if k in args:
                        arg_preview = f"{k}={args[k]!r}"
                        break
                if not arg_preview and args:
                    k = next(iter(args))
                    v = str(args[k])[:40]
                    arg_preview = f"{k}={v!r}"
            else:
                arg_preview = str(args)[:60]
            print(f"    {i:2d}. {tc['name']:<30s} {arg_preview}")
        print()

    if error:
        print("  [ERROR]")
        print(_wrap(error))
        print()
    elif text:
        print("  Answer:")
        print(_wrap(text))
        print()
    else:
        print("  [empty answer]")
        print()


def print_diff_summary(rows: dict[str, dict], gold: list[str]) -> None:
    print(_rule("━", "SIDE-BY-SIDE SUMMARY"))
    tt = rows.get("title_only", {})
    wt = rows.get("with_tools", {})
    _tt_any_hits, total, _ = deterministic_coverage(
        gold, tt.get("tool_calls") or [], tt.get("answer_text")
    )
    _wt_any_hits, _, _ = deterministic_coverage(
        gold, wt.get("tool_calls") or [], wt.get("answer_text")
    )
    # "cites fetched via tools" is the honest signal
    tt_tool_hits = len([
        aid for aid in (gold or [])
        if any(
            (isinstance(tc.get("arguments"), dict) and aid in json.dumps(tc["arguments"]))
            or tc.get("arxiv_id_hit") == aid
            for tc in (tt.get("tool_calls") or [])
        )
    ])
    wt_tool_hits = len([
        aid for aid in (gold or [])
        if any(
            (isinstance(tc.get("arguments"), dict) and aid in json.dumps(tc["arguments"]))
            or tc.get("arxiv_id_hit") == aid
            for tc in (wt.get("tool_calls") or [])
        )
    ])
    tt_len = len((tt.get("answer_text") or "").split())
    wt_len = len((wt.get("answer_text") or "").split())
    tt_tok = (tt.get("tokens_used") or tt.get("usage") or {}).get("total_tokens", 0)
    wt_tok = (wt.get("tokens_used") or wt.get("usage") or {}).get("total_tokens", 0)
    tt_lat = tt.get("latency_s", 0)
    wt_lat = wt.get("latency_s", 0)

    print()
    print(f"  {'metric':<22s} {'title_only':>14s}   {'with_tools':>14s}   {'Δ':>10s}")
    print(f"  {'-'*22} {'-'*14}   {'-'*14}   {'-'*10}")
    print(f"  {'answer words':<22s} {tt_len:>14d}   {wt_len:>14d}   {wt_len - tt_len:>+10d}")
    print(f"  {'cites fetched':<22s} {tt_tool_hits:>10d}/{total:<3d}   {wt_tool_hits:>10d}/{total:<3d}   {wt_tool_hits - tt_tool_hits:>+10d}")
    print(f"  {'tool calls':<22s} {0:>14d}   {len(wt.get('tool_calls') or []):>14d}   {'—':>10s}")
    print(f"  {'tokens (total)':<22s} {tt_tok:>14d}   {wt_tok:>14d}   {wt_tok - tt_tok:>+10d}")
    print(f"  {'latency (s)':<22s} {tt_lat:>14.2f}   {wt_lat:>14.2f}   {wt_lat - tt_lat:>+10.2f}")
    print()


# ---------- main ----------

def main() -> int:
    p = argparse.ArgumentParser(description="Side-by-side demo of deepxiv baseline vs citation-aware agent")
    p.add_argument("--question-id", "-q", help="Pick a question from eval/questions.json (e.g. Q001)")
    p.add_argument("--seed-arxiv-id", help="Free-form mode: the seed arxiv_id to query")
    p.add_argument("--question", help="Free-form mode: the question text")
    p.add_argument("--live", action="store_true", help="Execute fresh against live API (costs OPENAI_API_KEY)")
    p.add_argument("--replay", action="store_true", help="Force replay from cached Wave-1 rows (default)")
    p.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR), help=f"Wave-1 run dir (default: {DEFAULT_RUN_DIR.name})")
    p.add_argument("--base-url", default=DEFAULT_BASE_URL)
    args = p.parse_args()

    # Mode resolution
    free_form = bool(args.seed_arxiv_id and args.question)
    if free_form and not args.live:
        print("free-form mode requires --live (no cache for new questions)", file=sys.stderr)
        return 2
    if not free_form and not args.question_id:
        print("must provide either --question-id Q001 or (--seed-arxiv-id X --question '...' --live)",
              file=sys.stderr)
        return 2

    # Build the question dict
    if free_form:
        question = {
            "question_id": "<ad-hoc>",
            "question_type": "ad-hoc",
            "seed_arxiv_id": args.seed_arxiv_id,
            "gold_cited_arxiv_ids": [],
            "question_text": args.question,
        }
    else:
        question = load_question(args.question_id)

    # Seed paper info (cheap, always fetched)
    seed_info = fetch_seed_info(question["seed_arxiv_id"], args.base_url)

    # Pick mode
    use_live = args.live or free_form
    mode = "live" if use_live else "replay"

    print_header(question, seed_info, mode)

    # Get rows
    if use_live:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            print("OPENAI_API_KEY not set; required for --live", file=sys.stderr)
            return 2
        rows = run_live(question, api_key, args.base_url)
        score_rows: dict[str, dict] = {}
    else:
        rows = load_cached_rows(question["question_id"], Path(args.run_dir))
        if not rows:
            print(f"no cached rows for {question['question_id']} in {args.run_dir}",
                  file=sys.stderr)
            return 3
        score_rows = load_cached_scores(question["question_id"], Path(args.run_dir))

    gold = question.get("gold_cited_arxiv_ids") or []

    # Print each condition
    for cond in ("title_only", "with_tools"):
        if cond in rows:
            label = "BASELINE · title_only (no tools)" if cond == "title_only" else "CITATION-AWARE · with_tools"
            print_answer_block(label, rows[cond], gold, score_rows.get(cond))

    print_diff_summary(rows, gold)
    return 0


if __name__ == "__main__":
    sys.exit(main())
