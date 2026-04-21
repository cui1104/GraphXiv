"""LLM-as-judge scorer for Phase 8 evaluation (EVAL-03).

Reads a Wave 1 run directory produced by ``eval/run_eval.py`` — specifically the
two paired ``rows.jsonl`` files under ``{run_dir}/with_tools/`` and
``{run_dir}/title_only/`` (D-27 / D-31) — calls ``gpt-4o-mini`` (D-11) once per
question with BOTH answers presented in a randomized, per-question-seeded order
(position-bias mitigation per 08-RESEARCH Pattern 1 / 08-CONTEXT D-16) and
appends one verdict row per (question_id, condition) pair to
``{run_dir}/scores.jsonl``.

Every row also records ``deterministic_citation_coverage`` — a non-LLM count of
how many ``gold_cited_arxiv_ids`` were actually hit by the agent's ``tool_calls``
(D-19, 08-RESEARCH Pattern 5). This is the trust metric for the judge's own
``citation_coverage`` rating.

NOTE ON PLAN DRIFT (D-27, D-32):
  - Condition labels are ``with_tools`` / ``title_only`` (Wave 1 naming),
    not the plan-original ``baseline`` / ``citation_aware``.
  - Scores are written to ``{run_dir}/scores.jsonl`` (next to the paired
    ``rows.jsonl`` files), not to a flat ``eval/results/scores.jsonl``.
  - ``gold_answer_keywords`` is never sent to the judge (Anti-Pattern 7).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SCORES_SCHEMA_VERSION = 1
DEFAULT_RUN_DIR = Path(__file__).parent / "results" / "run_20260421_201456"
DEFAULT_QUESTIONS_PATH = Path(__file__).parent / "questions.json"
DEFAULT_RUBRIC_PATH = Path(__file__).parent / "rubric.md"
JUDGE_MODEL = "gpt-4o-mini"  # D-11 / D-28
JUDGE_TEMPERATURE = 0.0       # D-16
JUDGE_SEED = 42               # D-16
JUDGE_MAX_TOKENS = 1024
CONDITIONS = ("with_tools", "title_only")  # D-27

logger = logging.getLogger("score")
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


# ---------- Judge JSON schema (D-16, 08-RESEARCH Pattern 1) ----------

def _dimension_properties() -> dict:
    return {
        "answer_correctness": {"type": "integer", "minimum": 1, "maximum": 5},
        "faithfulness": {"type": "integer", "minimum": 1, "maximum": 5},
        "citation_coverage": {"type": "integer", "minimum": 1, "maximum": 5},
        "completeness": {"type": "integer", "minimum": 1, "maximum": 5},
        "notes": {"type": "string"},
    }


JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "answer_a": {
            "type": "object",
            "properties": _dimension_properties(),
            "required": ["answer_correctness", "faithfulness", "citation_coverage", "completeness", "notes"],
            "additionalProperties": False,
        },
        "answer_b": {
            "type": "object",
            "properties": _dimension_properties(),
            "required": ["answer_correctness", "faithfulness", "citation_coverage", "completeness", "notes"],
            "additionalProperties": False,
        },
    },
    "required": ["answer_a", "answer_b"],
    "additionalProperties": False,
}


# ---------- Deterministic citation_coverage (D-19, Pattern 5) ----------

def deterministic_citation_coverage(gold_arxiv_ids: list[str], tool_calls: list[dict]) -> float:
    """Fraction of ``gold_arxiv_ids`` that appear anywhere in ``tool_calls``.

    Checked surfaces per tool_call:
      - ``arxiv_id_hit`` (normalized by run_eval's wrapper, D-30)
      - Top-level ``arguments`` dict keys ``arxiv_id`` / ``paper_id`` / ``id``

    Returns a float in ``[0, 1]``. Returns ``0.0`` when ``gold_arxiv_ids`` is
    empty (the caller owns the N/A policy; keeping it at 0 avoids NaN in stats).
    """
    if not gold_arxiv_ids:
        return 0.0
    hits: set[str] = set()
    for tc in tool_calls or []:
        hit = tc.get("arxiv_id_hit")
        if hit:
            hits.add(str(hit))
        args = tc.get("arguments") or {}
        if isinstance(args, dict):
            for key in ("arxiv_id", "paper_id", "id"):
                val = args.get(key)
                if val:
                    hits.add(str(val))
    matched = sum(1 for g in gold_arxiv_ids if str(g) in hits)
    return matched / len(gold_arxiv_ids)


# ---------- Judge prompt construction ----------

def _read_rubric(rubric_path: Path = DEFAULT_RUBRIC_PATH) -> str:
    return Path(rubric_path).read_text(encoding="utf-8")


def _tool_call_summary(tool_calls: list[dict]) -> list[dict]:
    """Compact per-call summary for the judge (names + arxiv_ids hit)."""
    out: list[dict] = []
    for tc in tool_calls or []:
        out.append({
            "name": tc.get("name"),
            "arxiv_id_hit": tc.get("arxiv_id_hit"),
        })
    return out


def _build_judge_prompt(
    question: dict,
    run_a: dict,
    run_b: dict,
    rubric_text: str,
) -> list[dict]:
    """Build the (system, user) messages. NEVER includes ``gold_answer_keywords``
    (Anti-Pattern 7). NEVER reveals which answer came from which condition."""
    system_msg = (
        "You are a careful grader of research-paper Q&A answers. You will be shown a "
        "question, the gold set of arxiv IDs that should be cited, and TWO candidate "
        "answers (A and B) with their associated tool-call summaries. Score EACH "
        "answer independently on the four 1-5 dimensions defined in the rubric below.\n\n"
        "Return STRICT JSON matching the schema. Do not add commentary outside JSON. "
        "Do NOT anchor on whether an answer is labelled A or B — order is randomized "
        "per question.\n\n"
        "Rubric:\n" + rubric_text
    )
    user_payload = {
        "question_text": question["question_text"],
        "question_type": question.get("question_type"),
        "gold_cited_arxiv_ids": question.get("gold_cited_arxiv_ids", []),
        "answer_a": {
            "answer_text": run_a.get("answer_text") or "",
            "tool_calls_summary": _tool_call_summary(run_a.get("tool_calls") or []),
        },
        "answer_b": {
            "answer_text": run_b.get("answer_text") or "",
            "tool_calls_summary": _tool_call_summary(run_b.get("tool_calls") or []),
        },
    }
    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, indent=2)},
    ]


def parse_judge_verdict(raw: str) -> dict:
    """Parse the judge's JSON string; raise ValueError on any shape violation."""
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError(f"judge verdict not an object: {type(obj).__name__}")
    for key in ("answer_a", "answer_b"):
        if key not in obj or not isinstance(obj[key], dict):
            raise ValueError(f"judge verdict missing dict field {key!r}")
        sub = obj[key]
        for dim in ("answer_correctness", "faithfulness", "citation_coverage", "completeness"):
            val = sub.get(dim)
            if not isinstance(val, int) or not (1 <= val <= 5):
                raise ValueError(f"judge verdict {key}.{dim}={val!r} not int in [1,5]")
    return obj


# ---------- IO helpers ----------

def _load_rows(path: Path) -> dict[str, dict]:
    """Load a rows.jsonl into {question_id: row} (successful rows only)."""
    out: dict[str, dict] = {}
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
            out[row["question_id"]] = row
    return out


def _load_done_questions(scores_path: Path) -> set[str]:
    """Return question_ids that already have error-free score rows for BOTH conditions."""
    if not Path(scores_path).exists():
        return set()
    by_q: dict[str, set[str]] = defaultdict(set)
    with open(scores_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("error"):
                continue
            by_q[row["question_id"]].add(row.get("condition", ""))
    return {q for q, conds in by_q.items() if set(CONDITIONS).issubset(conds)}


def _append_row(scores_path: Path, row: dict) -> None:
    Path(scores_path).parent.mkdir(parents=True, exist_ok=True)
    with open(scores_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        f.flush()


# ---------- Per-question scoring ----------

def _presentation_order(question_id: str) -> list[str]:
    """Deterministic-per-question ordering of conditions (position-bias mitigation).

    ``hash(qid) % 2 == 0`` → with_tools first; else title_only first.
    """
    h = int(hashlib.sha256(question_id.encode("utf-8")).hexdigest(), 16)
    return ["with_tools", "title_only"] if h % 2 == 0 else ["title_only", "with_tools"]


def score_question(
    question: dict,
    run_with_tools: dict,
    run_title_only: dict,
    client,
    rubric_text: str,
) -> list[dict]:
    """Judge a single question pair and return TWO score rows (one per condition)."""
    order = _presentation_order(question["question_id"])
    runs_by_cond = {"with_tools": run_with_tools, "title_only": run_title_only}
    run_a = runs_by_cond[order[0]]
    run_b = runs_by_cond[order[1]]

    messages = _build_judge_prompt(question, run_a, run_b, rubric_text)
    resp = client.chat.completions.create(
        model=JUDGE_MODEL,
        temperature=JUDGE_TEMPERATURE,
        seed=JUDGE_SEED,
        max_tokens=JUDGE_MAX_TOKENS,
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "judge_verdict", "schema": JUDGE_SCHEMA, "strict": True},
        },
        messages=messages,
    )
    content = resp.choices[0].message.content
    verdict = parse_judge_verdict(content)
    judge_fingerprint = getattr(resp, "system_fingerprint", None)
    usage = getattr(resp, "usage", None)
    judge_tokens = {
        "prompt": getattr(usage, "prompt_tokens", None) if usage else None,
        "completion": getattr(usage, "completion_tokens", None) if usage else None,
        "total": getattr(usage, "total_tokens", None) if usage else None,
    }

    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    out: list[dict] = []
    for slot, cond in zip(("answer_a", "answer_b"), order):
        v = verdict[slot]
        run_row = runs_by_cond[cond]
        det_cov = deterministic_citation_coverage(
            question.get("gold_cited_arxiv_ids") or [],
            run_row.get("tool_calls") or [],
        )
        out.append({
            "scores_schema_version": SCORES_SCHEMA_VERSION,
            "question_id": question["question_id"],
            "question_type": question.get("question_type"),
            "condition": cond,
            "timestamp": now,
            "judge_model": JUDGE_MODEL,
            "judge_seed": JUDGE_SEED,
            "judge_temperature": JUDGE_TEMPERATURE,
            "judge_system_fingerprint": judge_fingerprint,
            "judge_tokens": judge_tokens,
            "presentation_order": order,
            "presentation_slot": slot,
            "answer_correctness": v["answer_correctness"],
            "faithfulness": v["faithfulness"],
            "citation_coverage": v["citation_coverage"],
            "completeness": v["completeness"],
            "judge_notes": v.get("notes", ""),
            "deterministic_citation_coverage": det_cov,
            "n_gold_cited": len(question.get("gold_cited_arxiv_ids") or []),
            "n_tool_calls": len(run_row.get("tool_calls") or []),
            "error": None,
        })
    return out


# ---------- Main loop ----------

def score_run(
    run_dir: Path = DEFAULT_RUN_DIR,
    questions_path: Path = DEFAULT_QUESTIONS_PATH,
    rubric_path: Path = DEFAULT_RUBRIC_PATH,
    *,
    client_factory: Optional[Callable[[], object]] = None,
    limit: Optional[int] = None,
    dry_run: bool = False,
    retry_errors: bool = False,
) -> dict:
    """Score every (question_id) pair in ``run_dir``. Resumable: skips question_ids
    with both-condition error-free rows already in scores.jsonl unless retry_errors=True.
    """
    run_dir = Path(run_dir)
    scores_path = run_dir / "scores.jsonl"
    rows_with = _load_rows(run_dir / "with_tools" / "rows.jsonl")
    rows_title = _load_rows(run_dir / "title_only" / "rows.jsonl")

    with open(questions_path, "r", encoding="utf-8") as f:
        questions_doc = json.load(f)
    questions_by_id = {q["question_id"]: q for q in questions_doc["questions"]}

    done = set() if retry_errors else _load_done_questions(scores_path)

    pending: list[str] = []
    for qid in questions_by_id:
        if qid in done:
            continue
        if qid in rows_with and qid in rows_title:
            pending.append(qid)

    if limit is not None:
        pending = pending[:limit]

    logger.info("score_run: %d pending, %d already done, run_dir=%s",
                len(pending), len(done), run_dir)
    if dry_run:
        return {"pending": len(pending), "done": len(done), "scores_path": str(scores_path)}

    if client_factory is None:
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY not set")
        from openai import OpenAI  # lazy import
        client_factory = lambda: OpenAI()
    client = client_factory()
    rubric_text = _read_rubric(rubric_path)

    written = 0
    errors = 0
    for qid in pending:
        q = questions_by_id[qid]
        try:
            rows = score_question(
                q,
                rows_with[qid],
                rows_title[qid],
                client,
                rubric_text,
            )
            for r in rows:
                _append_row(scores_path, r)
                written += 1
            logger.info("scored %s ok (+%d rows)", qid, len(rows))
        except Exception as exc:  # noqa: BLE001 — resumability: log + continue
            err_row = {
                "scores_schema_version": SCORES_SCHEMA_VERSION,
                "question_id": qid,
                "condition": None,
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                "error": f"{type(exc).__name__}: {exc}",
            }
            _append_row(scores_path, err_row)
            errors += 1
            logger.warning("score %s errored: %s", qid, err_row["error"])

    return {
        "written": written,
        "errors": errors,
        "pending": len(pending),
        "done": len(done),
        "scores_path": str(scores_path),
    }


# ---------- CLI ----------

def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 8 LLM-as-judge scorer (EVAL-03).")
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR,
                        help="Path to a Wave 1 run directory containing with_tools/ and title_only/ subdirs.")
    parser.add_argument("--questions-path", type=Path, default=DEFAULT_QUESTIONS_PATH)
    parser.add_argument("--rubric-path", type=Path, default=DEFAULT_RUBRIC_PATH)
    parser.add_argument("--limit", type=int, default=None,
                        help="Score at most this many questions (debug / smoke-test).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print pending / done counts and exit.")
    parser.add_argument("--retry-errors", action="store_true",
                        help="Ignore the resume state and re-score every question.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    summary = score_run(
        run_dir=args.run_dir,
        questions_path=args.questions_path,
        rubric_path=args.rubric_path,
        limit=args.limit,
        dry_run=args.dry_run,
        retry_errors=args.retry_errors,
    )
    print(f"[score] {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
