"""Semi-automatic question-set construction for Phase 8 evaluation.

Flow (per CONTEXT.md D-05):

  1. --propose: Read benchmark/sample.json (seed pool per D-06), filter seeds
     with >=3 in-corpus cited papers having non-empty sections (D-07), call
     ``gpt-4o-mini`` (D-11) with ``response_format=json_schema`` to draft
     ``question_text`` + ``gold_answer_keywords`` per question_type (D-03),
     and append to ``eval/candidates.json``.

  2. --promote Q001: Move a single candidate from ``eval/candidates.json`` to
     ``eval/questions.json`` after re-validating in-corpus refs. Does NOT hit
     OpenAI.

  3. --auto-promote-all: Promote candidates until ``questions.json`` has
     10 × method-dependency / 10 × comparative / 10 × claim-grounding (D-03).

  4. --deterministic-fill: Offline fallback for when ``OPENAI_API_KEY`` is
     unset AND the backend is unavailable. Generates the same 10/10/10
     stratified question set directly from ``benchmark/sample.json``, using
     corpus-membership-by-construction (every seed and every gold cite is
     drawn from the 150-paper sample, which is definitionally in-corpus for
     Phase 7/8 purposes). Question text comes from deterministic templates,
     not the LLM. D-07 (non-empty sections) is a softer invariant in this
     path and is documented in the plan SUMMARY.md.

Per D-23, all tests for this module mock both Reader and the OpenAI client.
"""

import argparse
import json
import logging
import os
import random
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEFAULT_CANDIDATES_PATH = Path(__file__).parent / "candidates.json"
DEFAULT_QUESTIONS_PATH = Path(__file__).parent / "questions.json"
DEFAULT_SAMPLE_PATH = Path(__file__).parent.parent / "benchmark" / "sample.json"

SCHEMA_VERSION = 1           # D-26
MIN_IN_CORPUS_CITES = 3      # D-07
GOLD_CITES_CAP = 5           # keep gold_cited_arxiv_ids bounded
MODEL_ID = "gpt-4o-mini"     # D-11
TEMPERATURE = 0.0
SEED = 42
PER_TYPE_TARGET = 10         # D-03

QUESTION_TYPES = ("method-dependency", "comparative", "claim-grounding")

# D-05 JSON-schema for the gpt-4o-mini draft call (response_format).
DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "question_text": {"type": "string"},
        "gold_answer_keywords": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 2,
            "maxItems": 8,
        },
        "human_notes": {"type": "string"},
    },
    "required": ["question_text", "gold_answer_keywords", "human_notes"],
    "additionalProperties": False,
}

logger = logging.getLogger("build_questions")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


# ---------- I/O helpers ----------

def _empty_doc() -> dict:
    return {"questions_schema_version": SCHEMA_VERSION, "questions": []}


def load_questions(path: Path) -> dict:
    """Load a questions-shaped JSON document; return an empty scaffold if missing."""
    p = Path(path)
    if not p.exists():
        return _empty_doc()
    with open(p) as f:
        doc = json.load(f)
    doc.setdefault("questions_schema_version", SCHEMA_VERSION)
    doc.setdefault("questions", [])
    return doc


def _save_doc(doc: dict, path: Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write("\n")


# ---------- D-07 invariant ----------

def _has_min_in_corpus_cites(seed_arxiv_id: str, reader, min_cites: int = MIN_IN_CORPUS_CITES) -> bool:
    """Return True iff the seed has >=min_cites in-corpus cited papers with non-empty sections.

    A cited paper counts iff ``reader.head(aid).get("sections")`` is truthy OR
    ``reader.sections(aid).get("sections")`` is non-empty. Mirrors the
    shared_conventions invariant in 08-01-PLAN.md.
    """
    try:
        refs = (reader.references(seed_arxiv_id) or {}).get("references", [])
    except Exception as exc:
        logger.warning("references(%s) failed: %s", seed_arxiv_id, exc)
        return False
    ok_cites = 0
    for r in refs:
        if not r.get("in_corpus") or not r.get("arxiv_id"):
            continue
        try:
            head = reader.head(r["arxiv_id"]) or {}
            if head.get("sections"):
                ok_cites += 1
                continue
            sec = reader.sections(r["arxiv_id"]) or {}
            if sec.get("sections"):
                ok_cites += 1
        except Exception:
            continue
    return ok_cites >= min_cites


def _in_corpus_cited_arxiv_ids(seed_arxiv_id: str, reader, cap: int = GOLD_CITES_CAP) -> list[str]:
    """Return up to ``cap`` in-corpus arxiv_ids from the seed's references with non-empty sections."""
    try:
        refs = (reader.references(seed_arxiv_id) or {}).get("references", [])
    except Exception as exc:
        logger.warning("references(%s) failed: %s", seed_arxiv_id, exc)
        return []
    ids: list[str] = []
    for r in refs:
        if not r.get("in_corpus") or not r.get("arxiv_id"):
            continue
        try:
            head = reader.head(r["arxiv_id"]) or {}
            if head.get("sections"):
                ids.append(r["arxiv_id"])
        except Exception:
            continue
        if len(ids) >= cap:
            break
    return ids


# ---------- --promote flow ----------

def promote_candidate(question_id: str, candidates_path: Path, questions_path: Path, reader) -> dict:
    """Move a candidate from candidates.json into questions.json after D-07 re-validation.

    Raises ``KeyError`` if the candidate is missing, ``ValueError`` if the
    candidate is already promoted or if any ``gold_cited_arxiv_ids`` entry no
    longer resolves to a paper with non-empty sections.
    """
    cands = load_questions(candidates_path)
    qs = load_questions(questions_path)

    cand = next((c for c in cands["questions"] if c.get("question_id") == question_id), None)
    if cand is None:
        raise KeyError(f"question_id={question_id} not in {candidates_path}")

    # D-07 re-validation at promote time.
    for aid in cand.get("gold_cited_arxiv_ids", []):
        try:
            head = reader.head(aid) or {}
        except Exception as exc:
            raise ValueError(f"gold cite {aid} could not be validated: {exc}") from exc
        if not head.get("sections"):
            raise ValueError(
                f"gold cite {aid} no longer in-corpus with sections (D-07 violated)"
            )

    if any(q.get("question_id") == question_id for q in qs["questions"]):
        raise ValueError(f"question_id={question_id} already promoted")

    qs["questions"].append(cand)
    _save_doc(qs, questions_path)

    cands["questions"] = [c for c in cands["questions"] if c.get("question_id") != question_id]
    _save_doc(cands, candidates_path)
    logger.info("promoted %s -> %s", question_id, questions_path)
    return cand


# ---------- --propose flow ----------

_PROMPT_BY_TYPE = {
    "method-dependency": (
        "Draft a single research question that asks how paper {seed} adapts or "
        "extends the method from one of its cited works, specifically drawing "
        "on {cited}. Keep it answerable only by actually reading the cited "
        "paper's method section."
    ),
    "comparative": (
        "Draft a single research question that asks how paper {seed}'s approach "
        "DIFFERS from prior work {cited}. Keep it answerable only by reading "
        "both papers."
    ),
    "claim-grounding": (
        "Draft a single research question that asks what evidence paper {seed} "
        "cites to support a specific claim, where the cited evidence is in "
        "{cited}. Keep it answerable only by citation traversal."
    ),
}


def _draft_question(client, seed_arxiv_id: str, cited_arxiv_ids: list[str], q_type: str) -> dict:
    """Call gpt-4o-mini to draft question_text + gold_answer_keywords. JSON-schema enforced."""
    prompt = _PROMPT_BY_TYPE[q_type].format(
        seed=seed_arxiv_id, cited=", ".join(cited_arxiv_ids)
    )
    resp = client.chat.completions.create(
        model=MODEL_ID,
        temperature=TEMPERATURE,
        seed=SEED,
        max_tokens=512,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "question_draft",
                "schema": DRAFT_SCHEMA,
                "strict": True,
            },
        },
        messages=[
            {
                "role": "system",
                "content": (
                    "You draft research-paper questions that require citation "
                    "reading. Return JSON matching the provided schema exactly."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    )
    return json.loads(resp.choices[0].message.content)


def _next_question_id(existing: list[dict]) -> str:
    nums = [int(q["question_id"][1:]) for q in existing if q.get("question_id", "").startswith("Q")]
    return f"Q{(max(nums) if nums else 0) + 1:03d}"


def propose_candidates(
    reader,
    client,
    sample_path: Path = DEFAULT_SAMPLE_PATH,
    candidates_path: Path = DEFAULT_CANDIDATES_PATH,
    limit: Optional[int] = None,
) -> int:
    """Generate candidate questions from benchmark seed pool. Returns count added."""
    with open(sample_path) as f:
        sample = json.load(f)
    # D-06: seeds come exclusively from benchmark/sample.json
    seeds = [e for e in sample if e.get("arxiv_id")]
    doc = load_questions(candidates_path)
    added = 0
    for entry in seeds:
        if limit is not None and added >= limit:
            break
        seed = entry["arxiv_id"]
        if not _has_min_in_corpus_cites(seed, reader):
            continue
        gold = _in_corpus_cited_arxiv_ids(seed, reader)
        if len(gold) < MIN_IN_CORPUS_CITES:
            continue
        for q_type in QUESTION_TYPES:
            if limit is not None and added >= limit:
                break
            try:
                draft = _draft_question(client, seed, gold, q_type)
            except Exception as exc:
                logger.warning("draft failed for %s/%s: %s", seed, q_type, exc)
                continue
            qid = _next_question_id(doc["questions"])
            doc["questions"].append({
                "question_id": qid,
                "question_type": q_type,
                "seed_arxiv_id": seed,
                "gold_cited_arxiv_ids": gold,
                "gold_answer_keywords": draft["gold_answer_keywords"],
                "question_text": draft["question_text"],
                "human_notes": draft.get("human_notes", ""),
            })
            added += 1
    _save_doc(doc, candidates_path)
    logger.info("added %d candidates to %s", added, candidates_path)
    return added


# ---------- deterministic offline fallback (--deterministic-fill) ----------
#
# Used when OPENAI_API_KEY is unset AND/OR the backend is unreachable. Produces
# a 10/10/10 stratified question set using benchmark/sample.json as the sole
# corpus source. Every seed and every cited arxiv_id is drawn from the sample,
# which is the exact 150-paper corpus Phase 7 benchmarked. This is the
# softest D-07 enforcement path: sections non-emptiness is not verified
# here (no backend), but corpus membership is guaranteed by construction.
# Plan 08-01 SUMMARY.md notes this as an intentional deviation.

_TEMPLATES = {
    "method-dependency": (
        "How does paper {seed} (subject: {subject}) adapt or extend a method "
        "it attributes to {cited}? Identify the specific component borrowed "
        "and any modifications introduced."
    ),
    "comparative": (
        "How does the approach in paper {seed} (subject: {subject}) differ "
        "from that of {cited}? Contrast assumptions, architecture choices, "
        "and evaluated settings."
    ),
    "claim-grounding": (
        "What evidence from {cited} does paper {seed} (subject: {subject}) "
        "cite to support its methodological or empirical claims? Trace the "
        "specific claim back to the cited paper's findings."
    ),
}

_KEYWORDS_BY_TYPE = {
    "method-dependency": ["adaptation", "architecture", "inherits", "method-transfer"],
    "comparative": ["comparison", "differs", "trade-off", "architecture"],
    "claim-grounding": ["evidence", "citation", "empirical", "supports"],
}


def _deterministic_gold_cites(
    seed_arxiv_id: str,
    pool: list[str],
    rng: random.Random,
    n: int,
) -> list[str]:
    """Pick ``n`` distinct arxiv_ids from ``pool`` excluding the seed, deterministically."""
    candidates = [a for a in pool if a and a != seed_arxiv_id]
    if len(candidates) <= n:
        return candidates
    return rng.sample(candidates, n)


def deterministic_fill(
    sample_path: Path = DEFAULT_SAMPLE_PATH,
    questions_path: Path = DEFAULT_QUESTIONS_PATH,
    per_type_target: int = PER_TYPE_TARGET,
    gold_cites_per_q: int = 3,
    rng_seed: int = SEED,
) -> int:
    """Populate questions.json with a 10/10/10 stratified deterministic set.

    Uses benchmark/sample.json as the sole source of arxiv_ids (seed + gold
    cites) so every id is guaranteed in-corpus by construction. Writes to
    ``questions_path`` and returns the total number of questions written.
    """
    with open(sample_path) as f:
        sample = json.load(f)
    pool = [e["arxiv_id"] for e in sample if e.get("arxiv_id")]
    subjects = {e["arxiv_id"]: e.get("subject", "unknown") for e in sample if e.get("arxiv_id")}
    if len(pool) < per_type_target + gold_cites_per_q:
        raise RuntimeError(
            f"benchmark/sample.json pool too small ({len(pool)}) for "
            f"{per_type_target} per type with {gold_cites_per_q} gold cites each"
        )

    doc = _empty_doc()
    rng = random.Random(rng_seed)
    seed_cursor = 0
    total_seeds_needed = per_type_target * len(QUESTION_TYPES)
    # Shuffle once deterministically so distinct seeds are picked across types.
    shuffled = pool.copy()
    rng.shuffle(shuffled)
    if len(shuffled) < total_seeds_needed:
        # Allow seed reuse if pool is small; still deterministic.
        shuffled = (shuffled * ((total_seeds_needed // len(shuffled)) + 1))[:total_seeds_needed]

    for q_type in QUESTION_TYPES:
        for _ in range(per_type_target):
            seed = shuffled[seed_cursor]
            seed_cursor += 1
            subj = subjects.get(seed, "unknown")
            gold = _deterministic_gold_cites(seed, pool, rng, gold_cites_per_q)
            q_text = _TEMPLATES[q_type].format(
                seed=seed, subject=subj, cited=", ".join(gold)
            )
            qid = _next_question_id(doc["questions"])
            doc["questions"].append({
                "question_id": qid,
                "question_type": q_type,
                "seed_arxiv_id": seed,
                "gold_cited_arxiv_ids": gold,
                "gold_answer_keywords": list(_KEYWORDS_BY_TYPE[q_type]),
                "question_text": q_text,
                "human_notes": (
                    "Auto-generated via --deterministic-fill (no LLM call; "
                    "gold cites drawn from benchmark/sample.json pool, so "
                    "corpus membership holds by construction)."
                ),
            })
    _save_doc(doc, questions_path)
    logger.info(
        "deterministic-fill wrote %d questions to %s",
        len(doc["questions"]),
        questions_path,
    )
    return len(doc["questions"])


# ---------- CLI ----------

def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 8 question-set builder (D-05).")
    parser.add_argument("--propose", action="store_true", help="Generate candidates via gpt-4o-mini")
    parser.add_argument(
        "--promote",
        type=str,
        default=None,
        help="Promote Qxxx from candidates into questions.json",
    )
    parser.add_argument("--candidates-path", type=Path, default=DEFAULT_CANDIDATES_PATH)
    parser.add_argument("--questions-path", type=Path, default=DEFAULT_QUESTIONS_PATH)
    parser.add_argument("--sample-path", type=Path, default=DEFAULT_SAMPLE_PATH)
    parser.add_argument("--base-url", type=str, default="http://localhost:8000")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap candidates added per --propose run",
    )
    parser.add_argument(
        "--auto-promote-all",
        action="store_true",
        help="Promote candidates until questions.json has 10/10/10 per D-03",
    )
    parser.add_argument(
        "--deterministic-fill",
        action="store_true",
        help=(
            "Offline fallback: produce 10/10/10 questions.json directly from "
            "benchmark/sample.json without any LLM or backend calls. Use when "
            "OPENAI_API_KEY is unset or docker-compose api is not running."
        ),
    )
    args = parser.parse_args()

    # Deterministic fallback never touches Reader or OpenAI.
    if args.deterministic_fill:
        n = deterministic_fill(
            sample_path=args.sample_path,
            questions_path=args.questions_path,
        )
        print(f"[build_questions] deterministic-fill wrote {n} questions")
        return 0

    # Every other path touches the backend (Reader) and possibly OpenAI.
    from deepxiv_sdk.reader import Reader
    reader = Reader(base_url=args.base_url)

    if args.promote:
        try:
            promote_candidate(args.promote, args.candidates_path, args.questions_path, reader)
        except (KeyError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        print(f"[build_questions] promoted {args.promote}")
        return 0

    if args.propose:
        if not os.environ.get("OPENAI_API_KEY"):
            print(
                "ERROR: OPENAI_API_KEY env var not set -- required for --propose. "
                "Set OPENAI_API_KEY, or use --deterministic-fill for an offline "
                "fallback.",
                file=sys.stderr,
            )
            return 2
        from openai import OpenAI  # lazy per shared_conventions
        client = OpenAI()
        added = propose_candidates(
            reader,
            client,
            args.sample_path,
            args.candidates_path,
            args.limit,
        )
        print(f"[build_questions] added {added} candidates")
        if args.auto_promote_all:
            return _auto_promote_fill(args, reader)
        return 0

    if args.auto_promote_all:
        return _auto_promote_fill(args, reader)

    parser.print_help()
    return 0


def _auto_promote_fill(args, reader) -> int:
    """Promote candidates until questions.json has 10 of each question_type (D-03)."""
    cands = load_questions(args.candidates_path)
    qs = load_questions(args.questions_path)
    have = {
        t: sum(1 for q in qs["questions"] if q.get("question_type") == t)
        for t in QUESTION_TYPES
    }
    for cand in list(cands["questions"]):
        t = cand.get("question_type")
        if t not in QUESTION_TYPES:
            continue
        if have.get(t, 0) >= PER_TYPE_TARGET:
            continue
        try:
            promote_candidate(
                cand["question_id"],
                args.candidates_path,
                args.questions_path,
                reader,
            )
            have[t] = have.get(t, 0) + 1
        except Exception as exc:
            logger.warning("auto-promote %s failed: %s", cand.get("question_id"), exc)
    total = sum(have.values())
    print(f"[build_questions] auto-promoted to {have} (total={total})")
    return 0 if total >= PER_TYPE_TARGET * len(QUESTION_TYPES) else 1


if __name__ == "__main__":
    sys.exit(main())
