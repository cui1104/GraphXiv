"""graphxiv - ask natural-language questions about papers in our corpus.

This is the user-facing CLI for the project. It mirrors the feel of the
open-source ``deepxiv`` CLI (``deepxiv agent query "..."``) but is powered by
our local parser + router + citation-aware agent, so you can directly compare
the baseline (title-only) answer against the citation-aware answer.

Entry point: the ``graphxiv`` shell wrapper at the repo root.

Most common usage::

    graphxiv ask 2602.19770 "How does this paper extend its cited works?"

    # arXiv ID embedded in the sentence is auto-detected:
    graphxiv ask "What evidence does 2602.07152 cite about backdoor attacks?"

    # Replay a pre-scored eval question (no API call, no cost):
    graphxiv demo Q001

    # Browse what you can ask about:
    graphxiv questions
    graphxiv papers
    graphxiv search "confusion matrix interpretability"
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import textwrap
import time
import urllib.error
import urllib.request
import warnings
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "sdk"))

DEFAULT_RUN_DIR = _REPO_ROOT / "eval" / "results" / "run_20260421_201456"
DEFAULT_QUESTIONS = _REPO_ROOT / "eval" / "questions.json"
DEFAULT_BASE_URL = "http://localhost:8000"

warnings.filterwarnings(
    "ignore",
    message=r"Core Pydantic V1 functionality isn't compatible with Python 3\.14 or greater\.",
    category=UserWarning,
    module=r"langchain_core\._api\.deprecation",
)

# arXiv IDs look like 2602.19770 (4 digits, dot, 4-5 digits). We also allow
# the legacy ``hep-th/9711200``-style but our corpus is modern-id only.
_ARXIV_RE = re.compile(r"\b(\d{4}\.\d{4,5})\b")


# ---------- terminal helpers -------------------------------------------------

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
    out: list[str] = []
    for para in text.splitlines() or [""]:
        if not para.strip():
            out.append("")
            continue
        out.extend(textwrap.wrap(para, width=_TERM_W - len(indent)) or [""])
    return "\n".join(indent + line for line in out)


# ---------- natural-language parsing ----------------------------------------

def extract_arxiv_id(text: str) -> Optional[str]:
    """Return the first arXiv ID found in ``text`` (or None)."""
    if not text:
        return None
    m = _ARXIV_RE.search(text)
    return m.group(1) if m else None


def resolve_ask_args(positional: list[str], paper_flag: Optional[str]) -> tuple[str, str]:
    """Turn whatever the user typed into ``(arxiv_id, question)``.

    Supported shapes (in priority order)::

        graphxiv ask 2602.19770 "question text"
        graphxiv ask -p 2602.19770 "question text"
        graphxiv ask "question text with 2602.19770 inside"
        graphxiv ask "how does this paper work?" --paper 2602.19770
    """
    # Explicit flag always wins
    if paper_flag:
        if len(positional) != 1:
            raise SystemExit(
                "with --paper, pass exactly one question string, e.g.:\n"
                "    graphxiv ask --paper 2602.19770 \"your question\""
            )
        return paper_flag.strip(), positional[0].strip()

    if len(positional) == 2:
        first, second = positional
        aid = extract_arxiv_id(first)
        if aid and first.strip() == aid:
            return aid, second.strip()
        # Maybe user put the question first and the id second
        aid = extract_arxiv_id(second)
        if aid and second.strip() == aid:
            return aid, first.strip()
        raise SystemExit(
            "could not figure out which argument is the arXiv ID.\n"
            "Try: graphxiv ask 2602.19770 \"your question\""
        )

    if len(positional) == 1:
        text = positional[0]
        aid = extract_arxiv_id(text)
        if aid:
            return aid, text.strip()
        raise SystemExit(
            "no arXiv ID found in your question. Either mention it inline\n"
            "(e.g. \"...in paper 2602.19770...\") or pass it explicitly:\n"
            "    graphxiv ask 2602.19770 \"your question\"\n"
            "    graphxiv ask --paper 2602.19770 \"your question\"\n\n"
            "Not sure which paper to use? Try:\n"
            "    graphxiv papers            # list parsed corpus\n"
            "    graphxiv questions         # list curated eval questions\n"
            "    graphxiv search \"topic\"    # search the corpus"
        )

    raise SystemExit(
        "usage: graphxiv ask [ARXIV_ID] \"your question\"\n"
        "       graphxiv ask \"question that mentions 2602.19770\"\n"
        "       graphxiv ask --paper 2602.19770 \"your question\"\n"
    )


# ---------- loaders ----------------------------------------------------------

def load_all_questions() -> list[dict]:
    with open(DEFAULT_QUESTIONS) as f:
        return json.load(f)["questions"]


def load_question(question_id: str) -> dict:
    qs = load_all_questions()
    for q in qs:
        if q["question_id"].lower() == question_id.lower():
            return q
    raise SystemExit(
        f"no question {question_id} in {DEFAULT_QUESTIONS.name}.\n"
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


# ---------- deterministic citation coverage (mirrors eval/score.py D-19) ----

def deterministic_coverage(
    gold_cited_arxiv_ids: list[str],
    tool_calls: list[dict],
    answer_text: Optional[str],
) -> tuple[int, int, list[str]]:
    hits: list[str] = []
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


def tool_hit_ids(gold: list[str], tool_calls: list[dict]) -> list[str]:
    """Gold IDs that appear as arguments to at least one tool call (the honest
    "did the agent actually fetch this cite?" signal)."""
    out = []
    for aid in gold or []:
        for tc in tool_calls or []:
            args = tc.get("arguments")
            if isinstance(args, dict) and aid in json.dumps(args):
                out.append(aid)
                break
            if tc.get("arxiv_id_hit") == aid:
                out.append(aid)
                break
    return out


# ---------- live runner -----------------------------------------------------

def run_live(question: dict, api_key: str, base_url: str, mode: str) -> dict[str, dict]:
    """Execute one or both conditions fresh against the running services.

    ``mode`` is one of ``"both"``, ``"baseline"``, ``"agent"``.
    """
    from eval import run_eval  # reuse the production runner

    print(_rule("━", "LIVE RUN"))
    out: dict[str, dict] = {}

    if mode in ("both", "baseline"):
        t0 = time.time()
        print("\n[baseline] title_only (no tools) ...", flush=True)
        title_out = run_eval.run_title_only(question, api_key=api_key, base_url=base_url)
        print(f"           done in {time.time() - t0:.1f}s", flush=True)
        out["title_only"] = {
            "answer_text": title_out.answer_text,
            "tool_calls": [],
            "latency_s": title_out.latency_s,
            "tokens_used": title_out.usage,
            "error": title_out.error,
        }

    if mode in ("both", "agent"):
        t0 = time.time()
        print("\n[agent]    with_tools (citation-aware) ...", flush=True)
        tools_out = run_eval.run_with_tools(question, api_key=api_key, base_url=base_url)
        print(
            f"           done in {time.time() - t0:.1f}s "
            f"({len(tools_out.tool_calls)} tool calls)",
            flush=True,
        )
        out["with_tools"] = {
            "answer_text": tools_out.answer_text,
            "tool_calls": tools_out.tool_calls,
            "latency_s": tools_out.latency_s,
            "tokens_used": tools_out.usage,
            "error": tools_out.error,
        }
    return out


# ---------- seed info -------------------------------------------------------

def fetch_seed_info(arxiv_id: str, base_url: str) -> dict:
    try:
        from deepxiv_sdk.reader import Reader

        reader = Reader(base_url=base_url, timeout=2, max_retries=0)
        head = reader.head(arxiv_id) or {}
    except Exception as exc:
        return {"error": str(exc)}
    return {
        "title": head.get("title") or "",
        "abstract": (head.get("abstract") or "")[:400],
        "year": head.get("year"),
    }


# ---------- pretty-printers -------------------------------------------------

def print_header(q: dict, seed_info: dict, mode: str) -> None:
    print(_rule("═"))
    print(_rule(" ", f"GRAPHXIV · {mode.upper()} "))
    print(_rule("═"))
    print()
    print(f"  question_id:   {q.get('question_id', '<free-form>')}")
    print(f"  question_type: {q.get('question_type', '<free-form>')}")
    print(f"  seed paper:    {q['seed_arxiv_id']}")
    title = seed_info.get("title")
    if title:
        print(f"                 \"{title[:100]}\"")
    elif seed_info.get("error"):
        print(f"                 (head lookup failed: {seed_info['error'][:80]})")
    gold = q.get("gold_cited_arxiv_ids") or []
    if gold:
        print(f"  gold cites:    {', '.join(gold)}   ({len(gold)} in-corpus)")
    print()
    print(_rule("─", "QUESTION"))
    print(_wrap(q["question_text"]))
    print()


def print_answer_block(
    cond_label: str,
    row: dict,
    gold: list[str],
    score_row: Optional[dict] = None,
) -> None:
    error = row.get("error")
    text = (row.get("answer_text") or "").strip()
    tool_calls = row.get("tool_calls") or []
    usage = row.get("tokens_used") or row.get("usage") or {}
    hits, total, hit_ids = deterministic_coverage(gold, tool_calls, text)
    t_hits = tool_hit_ids(gold, tool_calls)

    print(_rule("━", cond_label))

    meta_parts = [
        f"latency={row.get('latency_s', 0):.2f}s",
        f"tokens={usage.get('total_tokens', 0)}",
        f"tool_calls={len(tool_calls)}",
    ]
    if total:
        if tool_calls:
            meta_parts.append(
                f"cites_fetched={len(t_hits)}/{total}"
                + (f" [{', '.join(t_hits)}]" if t_hits else "")
            )
        else:
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
            meta_parts.append(f"judge=[ac={ac} fa={fa} cc={cc} co={co}] (1-5)")
    print("  " + " | ".join(meta_parts))
    print()

    if tool_calls:
        print("  Tool trace:")
        for i, tc in enumerate(tool_calls, 1):
            args = tc.get("arguments", {})
            if isinstance(args, dict):
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
    if "title_only" not in rows or "with_tools" not in rows:
        return
    print(_rule("━", "SIDE-BY-SIDE SUMMARY"))
    tt = rows["title_only"]
    wt = rows["with_tools"]
    total = len(gold or [])
    tt_hits = len(tool_hit_ids(gold, tt.get("tool_calls") or []))
    wt_hits = len(tool_hit_ids(gold, wt.get("tool_calls") or []))
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
    if total:
        print(f"  {'cites fetched':<22s} {tt_hits:>10d}/{total:<3d}   {wt_hits:>10d}/{total:<3d}   {wt_hits - tt_hits:>+10d}")
    print(f"  {'tool calls':<22s} {0:>14d}   {len(wt.get('tool_calls') or []):>14d}   {'—':>10s}")
    print(f"  {'tokens (total)':<22s} {tt_tok:>14d}   {wt_tok:>14d}   {wt_tok - tt_tok:>+10d}")
    print(f"  {'latency (s)':<22s} {tt_lat:>14.2f}   {wt_lat:>14.2f}   {wt_lat - tt_lat:>+10.2f}")
    print()


# ---------- command: ask ----------------------------------------------------

def cmd_ask(args: argparse.Namespace) -> int:
    arxiv_id, question_text = resolve_ask_args(args.tokens, args.paper)
    agent_question_text = question_text
    if arxiv_id not in question_text:
        agent_question_text = f"For arXiv paper {arxiv_id}: {question_text}"

    question = {
        "question_id": "<ad-hoc>",
        "question_type": "ad-hoc",
        "seed_arxiv_id": arxiv_id,
        "gold_cited_arxiv_ids": [],
        "question_text": agent_question_text,
    }

    # condition selection
    if args.baseline and args.agent:
        mode = "both"  # redundant flags; treat as both
    elif args.baseline:
        mode = "baseline"
    elif args.agent:
        mode = "agent"
    else:
        mode = "both"

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print(
            "OPENAI_API_KEY is not set. `graphxiv ask` makes live LLM calls\n"
            "and needs an OpenAI key. Either:\n"
            "    export OPENAI_API_KEY=sk-...\n"
            "or replay a pre-scored question for free:\n"
            "    graphxiv demo Q001",
            file=sys.stderr,
        )
        return 2

    seed_info = fetch_seed_info(arxiv_id, args.base_url)
    print_header(question, seed_info, f"live · {mode}")

    rows = run_live(question, api_key, args.base_url, mode)
    gold: list[str] = []

    for cond in ("title_only", "with_tools"):
        if cond in rows:
            label = (
                "BASELINE · title_only (no tools)"
                if cond == "title_only"
                else "CITATION-AWARE · with_tools"
            )
            print_answer_block(label, rows[cond], gold)

    print_diff_summary(rows, gold)
    return 0


# ---------- command: demo ---------------------------------------------------

def cmd_demo(args: argparse.Namespace) -> int:
    qs = load_all_questions()
    if args.question_id:
        question = load_question(args.question_id)
    else:
        question = random.choice(qs)
        print(f"(no question id given - picked {question['question_id']} at random)\n")

    run_dir = Path(args.run_dir)
    seed_info = fetch_seed_info(question["seed_arxiv_id"], args.base_url)
    print_header(question, seed_info, "replay (cached)")

    rows = load_cached_rows(question["question_id"], run_dir)
    if not rows:
        print(
            f"no cached rows for {question['question_id']} in {run_dir}.\n"
            f"run `graphxiv ask {question['seed_arxiv_id']} \"{question['question_text']}\"`\n"
            f"to execute it live instead.",
            file=sys.stderr,
        )
        return 3
    scores = load_cached_scores(question["question_id"], run_dir)
    gold = question.get("gold_cited_arxiv_ids") or []

    for cond in ("title_only", "with_tools"):
        if cond in rows:
            label = (
                "BASELINE · title_only (no tools)"
                if cond == "title_only"
                else "CITATION-AWARE · with_tools"
            )
            print_answer_block(label, rows[cond], gold, scores.get(cond))
    print_diff_summary(rows, gold)
    return 0


# ---------- command: questions ---------------------------------------------

def cmd_questions(args: argparse.Namespace) -> int:
    qs = load_all_questions()
    if args.type:
        qs = [q for q in qs if q["question_type"] == args.type]
        if not qs:
            print(f"no questions of type '{args.type}'", file=sys.stderr)
            return 3

    print(_rule("═"))
    print(_rule(" ", f" GRAPHXIV · {len(qs)} EVAL QUESTIONS "))
    print(_rule("═"))
    print()
    for q in qs:
        qid = q["question_id"]
        qtype = q["question_type"]
        seed = q["seed_arxiv_id"]
        n_gold = len(q.get("gold_cited_arxiv_ids") or [])
        text = q["question_text"]
        text_one = text if len(text) <= _TERM_W - 10 else text[: _TERM_W - 13] + "..."
        print(f"  {qid}  [{qtype:<18s}] seed={seed}  ({n_gold} gold cites)")
        print(f"       {text_one}")
        print()
    print(f"Replay any of them: graphxiv demo {qs[0]['question_id']}")
    return 0


# ---------- command: papers -------------------------------------------------

def cmd_papers(args: argparse.Namespace) -> int:
    """List seed papers that appear in our eval set (a proxy for the
    user-facing "parsed corpus" - these are the ones we have complete data on).
    """
    qs = load_all_questions()
    seen: dict[str, int] = {}
    for q in qs:
        seen[q["seed_arxiv_id"]] = seen.get(q["seed_arxiv_id"], 0) + 1

    print(_rule("═"))
    print(_rule(" ", f" GRAPHXIV · {len(seen)} SEED PAPERS IN EVAL CORPUS "))
    print(_rule("═"))
    print()
    for aid, count in sorted(seen.items()):
        info = fetch_seed_info(aid, args.base_url) if args.titles else {}
        title = info.get("title") or ""
        if title:
            title = title if len(title) <= _TERM_W - 25 else title[: _TERM_W - 28] + "..."
            print(f"  {aid}   ({count} questions)   {title}")
        else:
            print(f"  {aid}   ({count} questions)")
    print()
    print("Ask about any of them:")
    print(f"    graphxiv ask {next(iter(seen))} \"your question\"")
    return 0


# ---------- command: search -------------------------------------------------

def cmd_search(args: argparse.Namespace) -> int:
    """Thin wrapper around the Reader search endpoint for finding seed
    papers in our corpus by natural-language topic query."""
    try:
        from deepxiv_sdk.reader import Reader

        reader = Reader(base_url=args.base_url, timeout=5, max_retries=0)
    except Exception as exc:
        print(f"could not init Reader against {args.base_url}: {exc}", file=sys.stderr)
        return 3

    try:
        res = reader.search(query=args.query, size=args.limit, search_mode=args.mode)
    except Exception as exc:
        print(f"search failed: {exc}", file=sys.stderr)
        return 3

    results = (res or {}).get("results", []) if isinstance(res, dict) else (res or [])
    print(_rule("═"))
    print(_rule(" ", f" GRAPHXIV · SEARCH: {args.query!r} "))
    print(_rule("═"))
    print()
    if not results:
        print("  (no results)")
        return 0
    for i, paper in enumerate(results[: args.limit], 1):
        aid = paper.get("arxiv_id") or paper.get("id") or "<?>"
        title = paper.get("title") or ""
        if len(title) > _TERM_W - 20:
            title = title[: _TERM_W - 23] + "..."
        print(f"  {i:2d}. {aid}   {title}")
    print()
    print("Ask about one:")
    print(f"    graphxiv ask {results[0].get('arxiv_id', '<id>')} \"your question\"")
    return 0


# ---------- command: doctor -------------------------------------------------

def _check_url(url: str, timeout: float = 2.0) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read(200).decode("utf-8", errors="replace")
            return response.status < 400, body
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}: {exc.reason}"
    except Exception as exc:
        return False, str(exc)


def cmd_doctor(args: argparse.Namespace) -> int:
    """Check whether the terminal environment can run GraphXiv."""
    print(_rule("═"))
    print(_rule(" ", " GRAPHXIV · DOCTOR "))
    print(_rule("═"))
    print()

    failures = 0

    try:
        from deepxiv_sdk.reader import Reader

        reader = Reader(base_url=args.base_url)
        print(f"  OK   SDK Reader import works without loading agent stack")
        print(f"       base_url={reader.base_url}")
    except Exception as exc:
        failures += 1
        print("  FAIL SDK Reader import failed")
        print(_wrap(str(exc), indent="       "))

    ok, detail = _check_url(args.base_url.rstrip("/") + "/health")
    if ok:
        print("  OK   Backend health endpoint is reachable")
        print(f"       {detail}")
    else:
        failures += 1
        print("  FAIL Backend is not reachable")
        print(f"       tried {args.base_url.rstrip()}/health")
        print(_wrap(detail, indent="       "))

    if os.environ.get("OPENAI_API_KEY"):
        print("  OK   OPENAI_API_KEY is set for live `graphxiv ask` runs")
    else:
        print("  WARN OPENAI_API_KEY is not set")
        print("       live `graphxiv ask` needs: export OPENAI_API_KEY=sk-...")

    if DEFAULT_RUN_DIR.exists():
        rows = [
            DEFAULT_RUN_DIR / "title_only" / "rows.jsonl",
            DEFAULT_RUN_DIR / "with_tools" / "rows.jsonl",
            DEFAULT_RUN_DIR / "scores.jsonl",
        ]
        if all(p.exists() for p in rows):
            print("  OK   Cached eval replay data is present")
            print(f"       {DEFAULT_RUN_DIR}")
        else:
            print("  WARN Cached eval run exists but is incomplete")
            print(f"       {DEFAULT_RUN_DIR}")
    else:
        print("  WARN Cached eval replay directory is missing")
        print(f"       {DEFAULT_RUN_DIR}")

    print()
    if failures:
        print("GraphXiv is partially configured. Fix FAIL items before live runs.")
        return 1
    print("GraphXiv is ready for terminal testing.")
    return 0


# ---------- main ------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="graphxiv",
        description=(
            "graphxiv - ask natural-language questions about papers, "
            "side-by-side baseline vs citation-aware agent."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """\
            Examples:
              graphxiv ask 2602.19770 "How does this paper extend its cited works?"
              graphxiv ask "What evidence does 2602.07152 cite about backdoors?"
              graphxiv ask --paper 2602.19770 "Which methods inspire this paper?"
              graphxiv ask 2602.19770 "..." --agent      # only citation-aware
              graphxiv ask 2602.19770 "..." --baseline   # only title-only baseline

              graphxiv demo Q001                          # replay scored question
              graphxiv demo                               # random one

              graphxiv questions                          # list curated questions
              graphxiv papers                             # list seed papers
              graphxiv search "confusion matrix interpretability"
              graphxiv doctor                             # check backend and API key
            """
        ),
    )
    p.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"API base URL (default: {DEFAULT_BASE_URL})",
    )
    sub = p.add_subparsers(dest="command", metavar="COMMAND")

    # ask
    pa = sub.add_parser(
        "ask",
        help="ask a natural-language question about a paper",
        description=(
            "Ask a free-form question. Output shows the baseline (title-only) "
            "and the citation-aware agent side-by-side, with tool trace, "
            "citation hits, and latency."
        ),
    )
    pa.add_argument(
        "tokens",
        nargs="*",
        help="either [ARXIV_ID QUESTION] or [QUESTION] (with ID inline)",
    )
    pa.add_argument("--paper", "-p", help="explicit arXiv ID for the seed paper")
    g = pa.add_mutually_exclusive_group()
    g.add_argument(
        "--baseline",
        action="store_true",
        help="only run the title-only baseline (skip the agent)",
    )
    g.add_argument(
        "--agent",
        action="store_true",
        help="only run the citation-aware agent (skip the baseline)",
    )
    pa.set_defaults(func=cmd_ask)

    # demo
    pd = sub.add_parser(
        "demo",
        help="replay a pre-scored eval question from cache (no API cost)",
    )
    pd.add_argument("question_id", nargs="?", help="e.g. Q001. Omit for random.")
    pd.add_argument(
        "--run-dir",
        default=str(DEFAULT_RUN_DIR),
        help=f"cached run dir (default: {DEFAULT_RUN_DIR.name})",
    )
    pd.set_defaults(func=cmd_demo)

    # questions
    pq = sub.add_parser("questions", help="list the curated eval questions")
    pq.add_argument(
        "--type",
        choices=["method-dependency", "claim-grounding", "comparative"],
        help="filter by question type",
    )
    pq.set_defaults(func=cmd_questions)

    # papers
    pp = sub.add_parser("papers", help="list seed papers in the eval corpus")
    pp.add_argument(
        "--titles",
        action="store_true",
        help="fetch titles (slower, one API hit per paper)",
    )
    pp.set_defaults(func=cmd_papers)

    # search
    ps = sub.add_parser("search", help="search the corpus for a seed paper")
    ps.add_argument("query", help="natural-language search query")
    ps.add_argument("--limit", "-n", type=int, default=10, help="max results (default 10)")
    ps.add_argument(
        "--mode",
        choices=["bm25", "vector", "hybrid"],
        default="bm25",
        help="search mode (default bm25; vector/hybrid may load embeddings)",
    )
    ps.set_defaults(func=cmd_search)

    # doctor
    pdct = sub.add_parser("doctor", help="check backend/API-key readiness")
    pdct.set_defaults(func=cmd_doctor)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
