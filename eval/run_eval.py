"""Phase 8 Wave 1 paired A/B runner (EVAL-02, D-27, D-28, D-30, D-31).

Executes every question from eval/questions.json under two conditions:

- ``with_tools``: deepxiv_sdk.agent.Agent(citation_depth=1) against the live
  Reader API (default http://localhost:8000) with the full tool list.
- ``title_only``: direct gpt-4o-mini chat completion with NO tools; the model
  receives only the seed paper's title + abstract (retrieved up-front via
  Reader.head) and must answer from that alone.

Outputs a timestamped run directory::

    eval/results/run_YYYYMMDD_HHMMSS/
        with_tools/rows.jsonl
        title_only/rows.jsonl
        manifest.json

`manifest.json` aggregates per-condition metrics (count, errors, avg latency,
avg tool calls, avg tokens) and the full run config (model, seed, question
count, started/finished timestamps).

Per-row schema (D-31, descendant of D-13)::

    { jsonl_schema_version, run_id, question_id, condition, model, seed,
      timestamp, prompt_hash, system_fingerprint, answer_text,
      tool_calls, tokens_used, latency_s, error }

The runner is **not** resumable in Wave 1: each invocation writes to a fresh
timestamped run directory. Re-running from scratch is cheap (~$0.50-$1.00 on
gpt-4o-mini) and avoids ambiguity when mixing partial runs with different
model fingerprints (D-25, Pitfall 1).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sdk"))

JSONL_SCHEMA_VERSION = 1
CONDITION_WITH_TOOLS = "with_tools"
CONDITION_TITLE_ONLY = "title_only"
CONDITIONS = (CONDITION_WITH_TOOLS, CONDITION_TITLE_ONLY)

DEFAULT_QUESTIONS_PATH = Path(__file__).parent / "questions.json"
DEFAULT_RESULTS_ROOT = Path(__file__).parent / "results"
DEFAULT_MODEL = "gpt-4o-mini"          # D-11 / D-28
DEFAULT_SEED = 42                      # D-11
DEFAULT_TEMPERATURE = 0.0              # D-11
DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_MAX_LLM_CALLS = 20             # D-12
DEFAULT_MAX_TOKENS = 4096              # D-12
TITLE_ONLY_MAX_TOKENS = 1024

TITLE_ONLY_SYSTEM_PROMPT = (
    "You are a research assistant. Answer the user's question using ONLY the "
    "paper title and abstract provided below. You have no other tools or "
    "access to any other paper, cited work, or section body. If answering "
    "requires information not present in the title or abstract, say so "
    "explicitly rather than speculating."
)

WITH_TOOLS_SYSTEM_PROMPT_TAG = "deepxiv_sdk.agent.prompts.get_system_prompt"
# actual system prompt comes from the SDK at runtime; we record the tag in
# the prompt_hash input so drift in the SDK prompt is detectable alongside
# question drift.

logger = logging.getLogger("run_eval")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _run_stamp() -> str:
    return datetime.now(timezone.utc).strftime("run_%Y%m%d_%H%M%S")


def _prompt_hash(system_tag: str, question_text: str) -> str:
    h = hashlib.sha256()
    h.update(system_tag.encode("utf-8"))
    h.update(b"\n---\n")
    h.update(question_text.encode("utf-8"))
    return h.hexdigest()[:16]


def append_row(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        f.flush()


def load_questions(path: Path) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        doc = json.load(f)
    return list(doc.get("questions", []))


# ---------------------------------------------------------------------------
# Per-condition runs
# ---------------------------------------------------------------------------

@dataclass
class RunOutcome:
    """Bundle returned from a per-(question,condition) run; becomes a JSONL row."""
    answer_text: Optional[str]
    tool_calls: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
    system_fingerprint: Optional[str] = None
    latency_s: float = 0.0
    error: Optional[str] = None


def _normalize_args(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"__raw__": raw}
    return {}


def _extract_arxiv_hit(args: dict) -> Optional[str]:
    if not isinstance(args, dict):
        return None
    for k in ("arxiv_id", "paper_id", "id"):
        v = args.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def run_with_tools(
    question: dict,
    *,
    api_key: str,
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_MODEL,
    seed: int = DEFAULT_SEED,
    temperature: float = DEFAULT_TEMPERATURE,
    max_llm_calls: int = DEFAULT_MAX_LLM_CALLS,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> RunOutcome:
    """Run one question through the SDK Agent with the full tool list.

    Non-invasively wraps ``agent.tool_executor.execute_tool_call`` and
    ``agent.client.chat.completions.create`` to capture tool calls, token
    usage, and system_fingerprint without modifying any SDK files
    (Anti-Pattern 2 / D-30).
    """
    from deepxiv_sdk.agent import Agent
    from deepxiv_sdk.reader import Reader

    tool_calls: list[dict] = []
    usage_acc = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    fingerprint: Optional[str] = None

    reader = Reader(base_url=base_url)
    agent = Agent(
        api_key=api_key,
        reader=reader,
        model=model,
        temperature=temperature,
        citation_depth=1,
        max_llm_calls=max_llm_calls,
        max_tokens=max_tokens,
        print_process=False,
    )

    # --- wrap tool execution to capture calls ---
    original_execute = agent.tool_executor.execute_tool_call

    def _wrapped_execute(function_name, function_args, state):
        args = _normalize_args(function_args)
        tool_calls.append({
            "name": function_name,
            "arguments": args,
            "arxiv_id_hit": _extract_arxiv_hit(args),
        })
        return original_execute(function_name, function_args, state)

    agent.tool_executor.execute_tool_call = _wrapped_execute  # type: ignore[assignment]

    # --- wrap chat.completions.create to inject seed + accumulate usage ---
    original_create = agent.client.chat.completions.create

    def _wrapped_create(**kwargs):
        kwargs.setdefault("seed", seed)
        resp = original_create(**kwargs)
        try:
            u = getattr(resp, "usage", None)
            if u is not None:
                usage_acc["prompt_tokens"] += int(getattr(u, "prompt_tokens", 0) or 0)
                usage_acc["completion_tokens"] += int(getattr(u, "completion_tokens", 0) or 0)
                usage_acc["total_tokens"] += int(getattr(u, "total_tokens", 0) or 0)
        except Exception:
            pass
        try:
            fp = getattr(resp, "system_fingerprint", None)
            if fp:
                nonlocal fingerprint
                fingerprint = fp
        except Exception:
            pass
        return resp

    agent.client.chat.completions.create = _wrapped_create  # type: ignore[assignment]

    t0 = time.time()
    try:
        answer = agent.query(question["question_text"], reset_papers=True)
        err = None
        # Agent.query catches exceptions internally and returns "Error: ..." strings.
        if isinstance(answer, str) and answer.startswith("Error:"):
            err = answer
            answer_text: Optional[str] = None
        else:
            answer_text = answer
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
        answer_text = None
        logger.warning("with_tools run for %s raised: %s", question.get("question_id"), err)
        logger.debug("%s", traceback.format_exc())
    latency_s = time.time() - t0

    return RunOutcome(
        answer_text=answer_text,
        tool_calls=tool_calls,
        usage=usage_acc,
        system_fingerprint=fingerprint,
        latency_s=latency_s,
        error=err,
    )


def fetch_seed_title_abstract(
    arxiv_id: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
) -> tuple[Optional[str], Optional[str]]:
    """Fetch (title, abstract) for the seed paper. Lazy import of Reader so
    unit tests can monkey-patch this function without touching the SDK."""
    from deepxiv_sdk.reader import Reader
    reader = Reader(base_url=base_url)
    try:
        head = reader.head(arxiv_id) or {}
    except Exception as exc:  # network failure, 404, etc.
        logger.warning("fetch_seed_title_abstract(%s) failed: %s", arxiv_id, exc)
        return (None, None)
    return (head.get("title"), head.get("abstract"))


def run_title_only(
    question: dict,
    *,
    api_key: str,
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_MODEL,
    seed: int = DEFAULT_SEED,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = TITLE_ONLY_MAX_TOKENS,
) -> RunOutcome:
    """Run one question with NO tools: direct chat completion using only the
    seed paper's title + abstract.
    """
    from openai import OpenAI

    title, abstract = fetch_seed_title_abstract(question["seed_arxiv_id"], base_url=base_url)
    user_prompt = (
        f"Paper arXiv ID: {question['seed_arxiv_id']}\n"
        f"Title: {title or '(title unavailable in corpus)'}\n"
        f"Abstract: {abstract or '(abstract unavailable in corpus)'}\n\n"
        f"Question: {question['question_text']}\n"
    )

    client = OpenAI(api_key=api_key)
    t0 = time.time()
    try:
        resp = client.chat.completions.create(
            model=model,
            temperature=temperature,
            seed=seed,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": TITLE_ONLY_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        err = None
    except Exception as exc:
        latency_s = time.time() - t0
        logger.warning("title_only run for %s raised: %s", question.get("question_id"), exc)
        return RunOutcome(answer_text=None, latency_s=latency_s, error=f"{type(exc).__name__}: {exc}")
    latency_s = time.time() - t0

    answer_text = resp.choices[0].message.content if resp.choices else None
    usage = {
        "prompt_tokens": int(getattr(resp.usage, "prompt_tokens", 0) or 0) if resp.usage else 0,
        "completion_tokens": int(getattr(resp.usage, "completion_tokens", 0) or 0) if resp.usage else 0,
        "total_tokens": int(getattr(resp.usage, "total_tokens", 0) or 0) if resp.usage else 0,
    }
    fp = getattr(resp, "system_fingerprint", None)
    return RunOutcome(
        answer_text=answer_text,
        tool_calls=[],
        usage=usage,
        system_fingerprint=fp,
        latency_s=latency_s,
        error=err,
    )


# ---------------------------------------------------------------------------
# Row construction
# ---------------------------------------------------------------------------

def build_row(
    question: dict,
    condition: str,
    outcome: RunOutcome,
    *,
    model: str,
    seed: int,
    system_tag: str,
) -> dict:
    return {
        "jsonl_schema_version": JSONL_SCHEMA_VERSION,
        "run_id": str(uuid.uuid4()),
        "question_id": question["question_id"],
        "condition": condition,
        "model": model,
        "seed": seed,
        "timestamp": _now_iso(),
        "prompt_hash": _prompt_hash(system_tag, question["question_text"]),
        "system_fingerprint": outcome.system_fingerprint,
        "answer_text": outcome.answer_text,
        "tool_calls": outcome.tool_calls,
        "tokens_used": outcome.usage,
        "latency_s": round(outcome.latency_s, 3),
        "error": outcome.error,
    }


# ---------------------------------------------------------------------------
# Manifest aggregation
# ---------------------------------------------------------------------------

def _cond_stats(rows: list[dict]) -> dict:
    if not rows:
        return {"count": 0}
    successes = [r for r in rows if not r.get("error")]
    errors = [r for r in rows if r.get("error")]
    n_ok = len(successes)
    latencies = [r.get("latency_s", 0.0) for r in rows]
    tool_counts = [len(r.get("tool_calls") or []) for r in successes]
    tokens_total = [int((r.get("tokens_used") or {}).get("total_tokens", 0)) for r in successes]
    completion = [int((r.get("tokens_used") or {}).get("completion_tokens", 0)) for r in successes]

    def _avg(xs: list[float]) -> Optional[float]:
        return round(sum(xs) / len(xs), 3) if xs else None

    return {
        "count": len(rows),
        "success": n_ok,
        "error": len(errors),
        "error_rate": round(len(errors) / len(rows), 3) if rows else None,
        "avg_latency_s": _avg([float(x) for x in latencies]),
        "avg_tool_calls": _avg([float(x) for x in tool_counts]) if tool_counts else 0.0,
        "avg_tokens_total": _avg([float(x) for x in tokens_total]) if tokens_total else None,
        "avg_tokens_completion": _avg([float(x) for x in completion]) if completion else None,
    }


def build_manifest(
    *,
    run_dir: Path,
    questions_path: Path,
    model: str,
    seed: int,
    base_url: str,
    limit: Optional[int],
    started_at: str,
    finished_at: str,
    rows_by_cond: dict[str, list[dict]],
) -> dict:
    return {
        "schema_version": JSONL_SCHEMA_VERSION,
        "run_dir": str(run_dir),
        "questions_path": str(questions_path),
        "model": model,
        "seed": seed,
        "temperature": DEFAULT_TEMPERATURE,
        "base_url": base_url,
        "conditions": list(CONDITIONS),
        "limit": limit,
        "started_at": started_at,
        "finished_at": finished_at,
        "n_questions": sum(len(rows) for rows in rows_by_cond.values()) // max(1, len(rows_by_cond)),
        "per_condition": {cond: _cond_stats(rows) for cond, rows in rows_by_cond.items()},
    }


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_all(
    *,
    questions_path: Path = DEFAULT_QUESTIONS_PATH,
    results_root: Path = DEFAULT_RESULTS_ROOT,
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_MODEL,
    seed: int = DEFAULT_SEED,
    temperature: float = DEFAULT_TEMPERATURE,
    max_llm_calls: int = DEFAULT_MAX_LLM_CALLS,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    limit: Optional[int] = None,
    dry_run: bool = False,
    conditions: Iterable[str] = CONDITIONS,
    api_key: Optional[str] = None,
    run_dir: Optional[Path] = None,
    progress: bool = True,
) -> dict:
    """Execute the paired A/B run; return the written manifest dict."""
    questions = load_questions(questions_path)
    if limit is not None:
        questions = questions[:limit]

    conditions = tuple(conditions)
    for c in conditions:
        if c not in CONDITIONS:
            raise ValueError(f"unknown condition: {c!r}; expected one of {CONDITIONS}")

    if run_dir is None:
        run_dir = results_root / _run_stamp()

    started_at = _now_iso()
    logger.info(
        "run_all: questions=%d conditions=%s run_dir=%s model=%s seed=%s dry_run=%s",
        len(questions), conditions, run_dir, model, seed, dry_run,
    )

    if dry_run:
        planned = len(questions) * len(conditions)
        summary = {
            "schema_version": JSONL_SCHEMA_VERSION,
            "run_dir": str(run_dir),
            "planned": planned,
            "questions": len(questions),
            "conditions": list(conditions),
            "dry_run": True,
        }
        print(f"[run_eval] dry-run: {summary}")
        return summary

    run_dir.mkdir(parents=True, exist_ok=True)

    if not api_key:
        api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set; required for both with_tools and title_only live runs. "
            "Set it via `export OPENAI_API_KEY=...` (D-11 / D-24)."
        )

    rows_by_cond: dict[str, list[dict]] = {c: [] for c in conditions}
    path_by_cond: dict[str, Path] = {c: run_dir / c / "rows.jsonl" for c in conditions}
    for p in path_by_cond.values():
        p.parent.mkdir(parents=True, exist_ok=True)

    total = len(questions) * len(conditions)
    idx = 0
    for q in questions:
        for cond in conditions:
            idx += 1
            t0 = time.time()
            if cond == CONDITION_WITH_TOOLS:
                outcome = run_with_tools(
                    q,
                    api_key=api_key,
                    base_url=base_url,
                    model=model,
                    seed=seed,
                    temperature=temperature,
                    max_llm_calls=max_llm_calls,
                    max_tokens=max_tokens,
                )
                system_tag = f"{WITH_TOOLS_SYSTEM_PROMPT_TAG}|citation_depth=1|model={model}"
            else:
                outcome = run_title_only(
                    q,
                    api_key=api_key,
                    base_url=base_url,
                    model=model,
                    seed=seed,
                    temperature=temperature,
                    max_tokens=TITLE_ONLY_MAX_TOKENS,
                )
                system_tag = f"title_only|{TITLE_ONLY_SYSTEM_PROMPT[:64]}|model={model}"

            row = build_row(q, cond, outcome, model=model, seed=seed, system_tag=system_tag)
            append_row(path_by_cond[cond], row)
            rows_by_cond[cond].append(row)
            if progress:
                elapsed = time.time() - t0
                logger.info(
                    "[%d/%d] qid=%s cond=%s err=%s latency=%.1fs tools=%d tokens=%s",
                    idx, total, q.get("question_id"), cond,
                    (row.get("error") or "None"),
                    elapsed,
                    len(row.get("tool_calls") or []),
                    (row.get("tokens_used") or {}).get("total_tokens"),
                )

    finished_at = _now_iso()
    manifest = build_manifest(
        run_dir=run_dir,
        questions_path=questions_path,
        model=model,
        seed=seed,
        base_url=base_url,
        limit=limit,
        started_at=started_at,
        finished_at=finished_at,
        rows_by_cond=rows_by_cond,
    )
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("wrote manifest: %s", manifest_path)
    return manifest


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 8 Wave 1 paired A/B agent runner.")
    parser.add_argument("--questions-path", type=Path, default=DEFAULT_QUESTIONS_PATH)
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--base-url", type=str, default=DEFAULT_BASE_URL)
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    parser.add_argument("--max-llm-calls", type=int, default=DEFAULT_MAX_LLM_CALLS)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--limit", type=int, default=None, help="Run only the first N questions (smoke test).")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--conditions", nargs="+", default=list(CONDITIONS),
                        choices=list(CONDITIONS))
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    manifest = run_all(
        questions_path=args.questions_path,
        results_root=args.results_root,
        base_url=args.base_url,
        model=args.model,
        seed=args.seed,
        temperature=args.temperature,
        max_llm_calls=args.max_llm_calls,
        max_tokens=args.max_tokens,
        limit=args.limit,
        dry_run=args.dry_run,
        conditions=tuple(args.conditions),
    )
    print(f"[run_eval] manifest: {json.dumps(manifest.get('per_condition', manifest), indent=2)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
