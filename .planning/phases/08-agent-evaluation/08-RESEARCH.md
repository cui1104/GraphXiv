# Phase 8: Agent Evaluation - Research

**Researched:** 2026-04-21
**Domain:** LLM-as-judge A/B evaluation of a citation-aware ReAct agent
**Confidence:** HIGH (every mechanism exists in the repo today; only glue code and prompts are new)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Directory layout**
- **D-01:** New self-contained `eval/` directory at project root; mirrors `benchmark/` structure.
- **D-02:** Artefacts: `eval/questions.json`, `eval/rubric.md`, `eval/build_questions.py`, `eval/run_eval.py`, `eval/score.py`, `eval/analyze.py`, `eval/FINDINGS.md`, `eval/notebook/eval_analysis.ipynb`, `eval/results/runs.jsonl`, `eval/results/scores.jsonl`, `tests/test_eval.py`.

**Question set design**
- **D-03:** Exactly 30 questions minimum, stratified 10/10/10 across method-dependency, comparative, claim-grounding.
- **D-04:** Per-question schema: `question_id`, `question_type`, `seed_arxiv_id`, `gold_cited_arxiv_ids`, `gold_answer_keywords`, `question_text`, `human_notes`.
- **D-05:** Semi-automatic construction — candidates proposed from citation-graph structure + LLM, promoted by hand via `--promote Q001`.
- **D-06:** Seed papers drawn exclusively from `benchmark/sample.json` (Phase 7 150-paper sample).
- **D-07:** `gold_cited_arxiv_ids` must resolve to in-corpus papers with non-empty `Reader.head().sections`.

**Agent conditions**
- **D-08:** Baseline = `citation_depth=0`; tools available `search_papers`, `get_paper_head`, `get_paper_brief`, `get_paper_sections`, `get_references` (titles), `get_cited_by` (titles); `fetch_cited_paper_sections` disabled via monkey-patch.
- **D-09:** Citation-aware = `citation_depth=1`; all tools available including `fetch_cited_paper_sections`.
- **D-10:** Both conditions use identical LLM + temperature + seed + prompts; only tool set and `citation_depth` differ.
- **D-11:** LLM = `gpt-4o-mini`, `temperature=0.0`, `seed=42`. Same model used as judge with a separate prompt.
- **D-12:** `max_llm_calls=20`, `max_time_seconds=600`, `max_tokens=4096`.

**Paired runner**
- **D-13:** `eval/run_eval.py` iterates sequentially. One JSONL row per `(question_id, condition)` with answer, tool_calls, tokens_prompt, tokens_completion, wallclock_seconds, llm_calls, hit_limit, error.
- **D-14:** Resumable — skips `(question_id, condition)` pairs already present in `runs.jsonl`.
- **D-15:** Baseline condition implemented by replacing `agent.tool_executor.get_tools_definition()` return value with a subset that excludes `fetch_cited_paper_sections`. No Agent class edits.

**Scoring**
- **D-16:** Judge = `gpt-4o-mini`; sees question text, `gold_cited_arxiv_ids` (titles only), `gold_answer_keywords`, and both answers side-by-side (randomised A/B order per question).
- **D-17:** Rubric = four 1–5 dimensions per answer: `answer_correctness`, `faithfulness`, `citation_coverage`, `completeness`.
- **D-18:** Per-question `scores.jsonl` schema includes per-condition rubric scores, judge justification, `judge_preference`, `judge_confidence`.
- **D-19:** Deterministic grounding check runs alongside the judge; `citation_coverage` is reported BOTH by judge and by deterministic counter; FINDINGS flags disagreement.

**Analysis & reporting**
- **D-20:** `eval/analyze.py` → `eval/FINDINGS.md` with Methodology, Question-Set Composition, Per-Dimension Score Comparison, Paired Win-Rate, Cost/Latency Tradeoff, Failure Modes, Depth Recommendation.
- **D-21:** Notebook has ≥4 matplotlib cells: grouped bar, delta histogram, tokens-vs-uplift scatter, wallclock box plot.
- **D-22:** "Unambiguous win" definition = (mean-4-dim delta ≥ +1.0) AND (deterministic_citation_coverage delta ≥ +1).

**Test strategy**
- **D-23:** `tests/test_eval.py` covers promote/reject, tool-subset isolation, rubric parser, aggregation math. All mocked; no live OpenAI calls.
- **D-24:** LLM calls use `OPENAI_API_KEY`; tests inject `MagicMock`. One optional live smoke test gated by key presence.

**Reproducibility**
- **D-25:** Both JSONL files record model name + prompt hash + seed.
- **D-26:** `questions.json` is version-controlled; any change bumps `questions_schema_version`.

### Claude's Discretion
- Exact prompt wording for `build_questions.py` proposal step
- Exact judge prompt (may iterate to reduce position-bias variance)
- Whether to use structured outputs (JSON mode) vs freeform-parse on the judge response
- Whether to record per-tool-call latency or only total wallclock
- Whether `eval/notebook/` has a single `.ipynb` or multiple per question-type

### Deferred Ideas (OUT OF SCOPE)
- Backend/API changes; new agent tools; Reader additions
- Human annotation of answer quality (LLM-as-judge only)
- Training or fine-tuning
- Cross-model comparison (one LLM per paired run)
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| EVAL-01 | Curated, reproducible ≥30-question set stratified by type; gold-truth evidence IDs resolvable in-corpus | Citation-graph seed selection (D-06) ties to Phase 7 `benchmark/sample.json`; `Reader.head().sections` non-empty invariant is verifiable at build time (see §Question-Set Construction) |
| EVAL-02 | Paired A/B runner produces `runs.jsonl` for baseline (titles-only) and citation-aware conditions; resumable | Tool-subset isolation verified by reading `sdk/deepxiv_sdk/agent/tools.py` + `sdk/deepxiv_sdk/agent/graph.py` (see §Tool-Subset Isolation); JSONL resume pattern mirrors `benchmark/run_benchmark.py::_load_done_pairs` |
| EVAL-03 | LLM-as-judge + deterministic grounding check produce rubric scores per question; cross-validated for sanity | G-Eval / Chatbot Arena / RAGAS rubric research (see §LLM-as-Judge Best Practices); position-bias mitigation via A/B randomisation + order-swap is the documented consensus |
| EVAL-04 | Findings report with paired win-rate, per-dimension deltas, cost/latency, and default-depth recommendation; supporting notebook with ≥4 matplotlib cells | Wilcoxon signed-rank is the standard paired test for ordinal 1–5 scores at n=30 (see §Statistical Test); matplotlib aggregation pattern reused from `benchmark/notebook/analysis.ipynb` |
</phase_requirements>

---

## Summary

Phase 8 ships an empirical A/B evaluation in a self-contained `eval/` directory that re-uses Phase 6's `Agent` class as-is. Two conditions are run against the same 30+ curated questions with an identical LLM, temperature, and seed; the only differences are (a) whether the `fetch_cited_paper_sections` tool is exposed to the model, and (b) the `citation_depth` parameter. A paired-answer LLM judge scores both answers side-by-side across four 1–5 dimensions, and a deterministic grounding counter cross-validates the judge's `citation_coverage` score. Findings use the Wilcoxon signed-rank test on per-question score deltas, which is the honest statistic for this paired ordinal setup at n=30.

**Key confirmations from reading the source:**
- `gpt-4o-mini` exposes `seed`, `response_format={"type":"json_schema", ...}` (strict structured outputs), and `temperature=0.0`, which together give the closest available thing to determinism. Empirically, seed produces identical outputs on most calls but **drift is possible** when `system_fingerprint` changes — FINDINGS must record both.
- The SDK Agent already exposes every knob we need (`citation_depth`, `temperature`, `max_llm_calls`, `max_tokens`). No Agent-class modifications are required.
- The deterministic grounding check is trivial: it just scans the recorded `tool_calls` for each condition and counts how many `gold_cited_arxiv_ids` appear as arguments in any `get_paper_*` or `fetch_cited_paper_sections` call. No ML or judge required.

**Primary recommendation:** Use `gpt-4o-mini` with `temperature=0.0`, `seed=42`, and `response_format={"type":"json_schema", "json_schema":{...}}` for the judge. Use `unittest.mock.patch("openai.OpenAI")` in tests. For the baseline tool-subset isolation, patch the **module-level** `deepxiv_sdk.agent.graph.get_tools_definition` (not the instance method on `ToolExecutor`) — see §Tool-Subset Isolation for the exact reason.

**One adjustment required to CONTEXT.md D-08 and D-15** — see §Discrepancies with CONTEXT.md at the bottom. Both are wording-level and do not change the phase boundary.

---

## Standard Stack

### Core (already in `pyproject.toml` or `sdk/`)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `openai` | ≥1.50.0 | Chat Completions API + JSON schema mode | Already a transitive dep via `sdk/` Agent; needed for judge + mocking |
| `tiktoken` | ≥0.7.0 | Prompt hashing for reproducibility (D-25) + token counting | Already in `pyproject.toml` |
| `httpx` | 0.28.1 | Backend calls via `Reader` | Already installed |
| `pytest` | latest | Unit tests | Already in `[project.optional-dependencies] dev` |
| `pytest-timeout` | latest | Cap per-test wallclock in integration smoke | Already in dev extras |

### Supporting (new — small additions)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `scipy` | ≥1.11 | `scipy.stats.wilcoxon` signed-rank test | Paired per-question score deltas in `analyze.py` |
| `matplotlib` | ≥3.8 | Notebook charts (D-21) | Same dep used by Phase 7 notebook |
| `pandas` | ≥2.0 | Aggregation of `runs.jsonl`/`scores.jsonl` → markdown tables | Lighter than polars; already pulled in transitively |
| `notebook` or `jupyter` | ≥7.0 | `eval/notebook/eval_analysis.ipynb` | Same as Phase 7 |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `scipy.stats.wilcoxon` | Paired bootstrap | Wilcoxon is the textbook paired-ordinal test and gives a p-value directly; bootstrap adds code for no extra signal at n=30 |
| `response_format={"type":"json_schema", ...}` | Freeform regex parse of judge output | JSON schema is guaranteed valid by the OpenAI runtime; no retry logic or parse errors — recommended |
| `unittest.mock.patch` | `respx`/`pytest-httpx` | We mock the Python client directly, not the HTTP layer; simpler |

**Installation delta (append to `pyproject.toml` optional-dependencies, NOT the core `dependencies`):**
```toml
[project.optional-dependencies]
eval = [
    "openai>=1.50.0",
    "scipy>=1.11",
    "matplotlib>=3.8",
    "pandas>=2.0",
    "notebook>=7.0",
]
```

**Version verification (2026-04-21):**
- `openai` Python SDK ≥ 1.50 supports `response_format={"type":"json_schema", ...}` on `gpt-4o-mini-2024-07-18` and later snapshots (per OpenAI Structured Outputs announcement 2024-08-06 and still current).
- `scipy.stats.wilcoxon` has been stable since scipy 1.0 (2017); 1.11+ is the current maintained branch.

---

## Architecture Patterns

### Recommended Project Structure
```
eval/
├── build_questions.py        # citation-graph + LLM → candidates; --promote writes questions.json
├── rubric.md                 # human-readable rubric (referenced by judge prompt)
├── run_eval.py               # paired A/B runner → results/runs.jsonl (resumable)
├── score.py                  # LLM judge + deterministic grounding → results/scores.jsonl
├── analyze.py                # runs+scores → FINDINGS.md + CSV tables
├── questions.json            # ≥30 curated questions, version-controlled
├── results/
│   ├── runs.jsonl            # 2N rows: (question_id, condition) answer traces
│   └── scores.jsonl          # N rows: per-question paired scores
├── FINDINGS.md
└── notebook/
    └── eval_analysis.ipynb   # ≥4 matplotlib cells
tests/
└── test_eval.py              # ≥10 unit tests, all mocked
```

### Pattern 1: OpenAI Chat Completions with Seed + JSON Schema (judge call)
**What:** Request a strict JSON object from `gpt-4o-mini`; the returned content is guaranteed to parse against the supplied schema.
**When to use:** `eval/score.py` — one call per question, returns per-dimension ratings + preference + confidence.
**Example:**
```python
# Source: https://platform.openai.com/docs/guides/structured-outputs (verified 2026-04-21)
# Source: https://platform.openai.com/docs/api-reference/chat/create (parameters: seed, response_format)
from openai import OpenAI

client = OpenAI()  # reads OPENAI_API_KEY

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "a": {
            "type": "object",
            "properties": {
                "answer_correctness": {"type": "integer", "minimum": 1, "maximum": 5},
                "faithfulness":       {"type": "integer", "minimum": 1, "maximum": 5},
                "citation_coverage":  {"type": "integer", "minimum": 1, "maximum": 5},
                "completeness":       {"type": "integer", "minimum": 1, "maximum": 5},
            },
            "required": ["answer_correctness", "faithfulness", "citation_coverage", "completeness"],
            "additionalProperties": False,
        },
        "b": {
            "type": "object",
            "properties": {
                "answer_correctness": {"type": "integer", "minimum": 1, "maximum": 5},
                "faithfulness":       {"type": "integer", "minimum": 1, "maximum": 5},
                "citation_coverage":  {"type": "integer", "minimum": 1, "maximum": 5},
                "completeness":       {"type": "integer", "minimum": 1, "maximum": 5},
            },
            "required": ["answer_correctness", "faithfulness", "citation_coverage", "completeness"],
            "additionalProperties": False,
        },
        "preference":       {"type": "string", "enum": ["a", "b", "tie"]},
        "confidence":       {"type": "integer", "minimum": 1, "maximum": 5},
        "justification":    {"type": "string"},
    },
    "required": ["a", "b", "preference", "confidence", "justification"],
    "additionalProperties": False,
}

resp = client.chat.completions.create(
    model="gpt-4o-mini",
    temperature=0.0,
    seed=42,
    max_tokens=1024,
    response_format={
        "type": "json_schema",
        "json_schema": {"name": "judge_verdict", "schema": JUDGE_SCHEMA, "strict": True},
    },
    messages=[
        {"role": "system", "content": SYSTEM_JUDGE_PROMPT},  # defined in rubric.md
        {"role": "user",   "content": user_prompt_with_A_and_B},
    ],
)
verdict = json.loads(resp.choices[0].message.content)  # schema-valid, guaranteed
system_fingerprint = resp.system_fingerprint            # record alongside seed (D-25)
```

**Key parameter notes (verified against `platform.openai.com/docs/api-reference/chat/create`):**
- `seed` — integer, "best-effort" determinism; OpenAI does **not** guarantee byte-identical output even with identical seed+params, but the same seed + same `system_fingerprint` produces identical output "most of the time". Record `system_fingerprint` in every `runs.jsonl` / `scores.jsonl` row (D-25).
- `response_format={"type":"json_schema", "json_schema":{"strict": True, ...}}` — supported on `gpt-4o-mini-2024-07-18` and later; the runtime rejects schema violations before returning to you, so `json.loads()` on the response is safe without try/except.
- `temperature=0.0` — still not strictly deterministic (kernel-level floating-point non-associativity + batch-routing effects), but collapses almost all variance. Combined with `seed` this is the closest available thing to reproducibility.
- `tool_choice` — not needed for the judge (no tools). For the Agent runs, the SDK does not set `tool_choice` explicitly, which defaults to `"auto"` — correct behaviour (model decides when to call tools).

### Pattern 2: Tool-Subset Isolation for the Baseline Condition
**What:** Prevent the model from calling `fetch_cited_paper_sections` without modifying the Agent class.
**When to use:** `eval/run_eval.py` baseline condition setup.

**CRITICAL — read before implementing.** The SDK has TWO places where the tool list lives:

1. **Module-level function** `get_tools_definition()` at `sdk/deepxiv_sdk/agent/tools.py:9` — returns the full list.
2. **Instance method** `ToolExecutor.get_tools_definition()` at `sdk/deepxiv_sdk/agent/tools.py:649` — just calls the module function.

`sdk/deepxiv_sdk/agent/graph.py:12` imports the **module-level** function, and `graph.py:223` calls it directly (`tools = get_tools_definition()`). **It never calls `tool_executor.get_tools_definition()`** — that instance method is dead code from the Agent's perspective. Therefore monkey-patching the instance method has **no effect** on what tools the model sees.

**Correct approach — patch the module-level name used by `graph.py`:**
```python
# eval/run_eval.py
import deepxiv_sdk.agent.graph as _graph
from deepxiv_sdk.agent.tools import get_tools_definition as _full_tools

def _baseline_tools():
    return [t for t in _full_tools() if t["function"]["name"] != "fetch_cited_paper_sections"]

def run_baseline(agent, question: str) -> str:
    # Patch the symbol that graph.py:223 actually calls
    original = _graph.get_tools_definition
    _graph.get_tools_definition = _baseline_tools
    try:
        return agent.query(question, reset_papers=True)
    finally:
        _graph.get_tools_definition = original
```

Equivalently, using `unittest.mock.patch`:
```python
from unittest.mock import patch
with patch("deepxiv_sdk.agent.graph.get_tools_definition", side_effect=_baseline_tools):
    answer = agent.query(question, reset_papers=True)
```

**Belt-and-braces:** Set `citation_depth=0` on the baseline Agent anyway. Even if a stray `fetch_cited_paper_sections` call leaked through, `ToolExecutor.fetch_cited_paper_sections` computes `max_papers = self.citation_depth * 5 = 0`, so it returns "No in-corpus cited papers…" without fetching anything (`tools.py:694`). This is defence in depth, not the primary mechanism.

**Verification test (mandatory in `tests/test_eval.py`):** Call `run_baseline()` against an Agent whose `client` is a MagicMock, inspect the captured `tools` kwarg on `client.chat.completions.create`, and assert that `fetch_cited_paper_sections` is **not** in the list.

### Pattern 3: Resumable JSONL Runner
**What:** `run_eval.py` skips `(question_id, condition)` pairs already written to `runs.jsonl`, so interrupted runs resume cleanly.
**When to use:** Every long-running Agent loop over the 30 questions × 2 conditions.
**Example (mirrors `benchmark/run_benchmark.py::_load_done_pairs`):**
```python
import json, os
from pathlib import Path

RUNS_PATH = Path("eval/results/runs.jsonl")

def load_done_pairs() -> set[tuple[str, str]]:
    """Return set of (question_id, condition) already successfully recorded."""
    if not RUNS_PATH.exists():
        return set()
    done = set()
    with RUNS_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("error"):
                continue  # re-try errored rows on next run
            done.add((row["question_id"], row["condition"]))
    return done

def append_row(row: dict) -> None:
    RUNS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RUNS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

def main():
    done = load_done_pairs()
    for q in load_questions():
        for cond in ("baseline", "citation_aware"):
            if (q["question_id"], cond) in done:
                continue
            row = run_one(q, cond)  # returns dict matching D-13 schema
            append_row(row)
```

Notes:
- Append-mode (`"a"`) write is atomic per-line on POSIX for lines < 4 KiB; for longer rows (tool_calls can be large) use `f.flush(); os.fsync(f.fileno())` after each write, OR switch to `write → rename` temp-file-per-row. The benchmark runner uses the flush pattern in practice and it's sufficient.
- Errored rows (`row["error"] != None`) are **retried** on the next run by excluding them from `done` — matches `benchmark/run_benchmark.py:916`.

### Pattern 4: OpenAI Client Mocking in pytest
**What:** Mock `openai.OpenAI` at the module level so no live API calls happen in unit tests.
**When to use:** Every test in `tests/test_eval.py` that touches `eval/score.py` or exercises `Agent.query()` end-to-end.

**Example — mock the client constructor + the `.chat.completions.create` call:**
```python
# tests/test_eval.py
import json
from unittest.mock import MagicMock, patch
import pytest

@pytest.fixture
def mock_openai_client():
    """A MagicMock shaped like openai.OpenAI for injection into Agent or score.py."""
    client = MagicMock()
    # Default: return a valid judge JSON. Tests override per-call.
    default_verdict = {
        "a": {"answer_correctness": 3, "faithfulness": 4, "citation_coverage": 1, "completeness": 2},
        "b": {"answer_correctness": 5, "faithfulness": 5, "citation_coverage": 4, "completeness": 4},
        "preference": "b", "confidence": 4, "justification": "B cites more gold refs.",
    }
    msg = MagicMock()
    msg.content = json.dumps(default_verdict)
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    resp.system_fingerprint = "fp_test_0000"
    client.chat.completions.create.return_value = resp
    return client

def test_score_parses_schema_valid_verdict(mock_openai_client):
    from eval.score import score_pair
    row = score_pair(
        question={"question_id": "Q001", "question_text": "...", "gold_cited_arxiv_ids": ["1706.03762"]},
        baseline_row={"answer": "Base answer", "tool_calls": []},
        citation_aware_row={"answer": "Citation answer", "tool_calls": [{"name": "load_paper", "args": {"arxiv_id": "1706.03762"}}]},
        client=mock_openai_client,
    )
    assert row["judge_preference"] in ("baseline", "citation_aware", "tie")
    assert 1 <= row["citation_aware"]["answer_correctness"] <= 5
```

**When the test needs to mock `openai.OpenAI` at import time** (e.g., `score.py` does `from openai import OpenAI` at module top and `OpenAI()` at module scope — which it should NOT, but just in case):
```python
with patch("eval.score.OpenAI") as mock_cls:
    mock_cls.return_value = mock_openai_client
    import eval.score  # now safe to exercise
```

**Project precedent:** `sdk/tests/test_cli.py:60–130` already uses `@mock.patch("deepxiv_sdk.cli.Reader")` to patch the class at the import path used by the code under test — same pattern.

### Pattern 5: Deterministic Grounding Check (D-19)
**What:** Count how many `gold_cited_arxiv_ids` for a question appear as an `arxiv_id` argument in any recorded `tool_calls` for that run.
**When to use:** Called on each `runs.jsonl` row during scoring, stored alongside the judge's `citation_coverage` for cross-validation.
**Example:**
```python
def deterministic_citation_coverage(tool_calls: list[dict], gold_ids: list[str]) -> int:
    """
    Returns count (0..len(gold_ids)) of gold cited papers that appear as arxiv_id
    in any tool call args. Symmetric across all tools that accept arxiv_id.
    """
    called_ids = set()
    for call in tool_calls:
        args = call.get("args") or call.get("arguments") or {}
        aid = args.get("arxiv_id")
        if aid:
            called_ids.add(aid)
        for aid in args.get("arxiv_ids") or []:
            called_ids.add(aid)
    return sum(1 for gid in gold_ids if gid in called_ids)

def coverage_agreement(judge_score: int, det_count: int, n_gold: int) -> bool:
    """Judge uses 1..5 ordinal; bin det_count into the same bucket."""
    if n_gold == 0: return True
    frac = det_count / n_gold
    det_bucket = 1 if frac == 0 else 2 if frac < 0.25 else 3 if frac < 0.5 else 4 if frac < 0.75 else 5
    return abs(judge_score - det_bucket) <= 1  # within ±1 is "agrees"
```

### Pattern 6: Wilcoxon Signed-Rank on Per-Question Deltas
**What:** The correct paired test for ordinal 1–5 scores when the same 30 questions are evaluated under both conditions.
**When to use:** `eval/analyze.py`, once per rubric dimension + once on the 4-dim mean.

```python
# Source: https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.wilcoxon.html
from scipy.stats import wilcoxon

def paired_test(baseline_scores: list[int], citation_scores: list[int]) -> dict:
    """
    Wilcoxon signed-rank on paired deltas. Null hypothesis: median delta = 0.
    Alternative: citation_aware > baseline (one-sided 'greater').
    """
    assert len(baseline_scores) == len(citation_scores)
    # zero_method="wilcox" (default) drops zero-diff pairs — standard.
    stat, p = wilcoxon(citation_scores, baseline_scores, alternative="greater", zero_method="wilcox")
    deltas = [c - b for c, b in zip(citation_scores, baseline_scores)]
    wins  = sum(1 for d in deltas if d > 0)
    losses= sum(1 for d in deltas if d < 0)
    ties  = sum(1 for d in deltas if d == 0)
    return {"W": float(stat), "p_value": float(p), "wins": wins, "losses": losses, "ties": ties,
            "mean_delta": sum(deltas)/len(deltas), "median_delta": sorted(deltas)[len(deltas)//2]}
```

**Sample-size adequacy at n=30:** Wilcoxon's asymptotic normal approximation is considered valid for n ≥ 20–25, so n=30 is fine. Per Conover (*Practical Nonparametric Statistics*, 3rd ed.), effect sizes of Cohen's-d ≈ 0.5 are detectable at 80% power at n=30 for a one-sided test at α=0.05. If the citation-aware uplift is real (e.g. mean delta ≈ +1.0 on a 5-point scale with SD ≈ 1.5), we have >90% power. If deltas are small (mean ≈ +0.3), n=30 is underpowered — FINDINGS should report this honestly rather than claim a null result.

### Pattern 7: Question-Set Construction (build_questions.py)
**What:** Seed-paper selection from `benchmark/sample.json`, in-corpus citation-graph filter, LLM-generated question text, manual promotion.
**When to use:** One-shot script, run offline by a human.
**Skeleton:**
```python
# eval/build_questions.py
# 1. Load seed pool
seed_ids = [p["arxiv_id"] for p in json.load(open("benchmark/sample.json"))]

# 2. For each seed, find in-corpus cited papers with non-empty sections (D-07)
reader = Reader(base_url="http://localhost:8000")
candidates = []
for seed in seed_ids:
    refs = reader.references(seed).get("references", [])
    gold = []
    for r in refs:
        if not r.get("in_corpus") or not r.get("arxiv_id"):
            continue
        head = reader.head(r["arxiv_id"])
        if head and head.get("sections"):
            gold.append(r["arxiv_id"])
    if len(gold) >= 3:
        candidates.append({"seed_arxiv_id": seed, "gold_cited_arxiv_ids": gold[:5]})

# 3. For each candidate, LLM-generate question text per type (method-dependency, comparative, claim-grounding)
#    Use response_format=json_schema with {"question_text": str, "gold_answer_keywords": [str]}.
#    Write to candidates.json.

# 4. --promote Q001 flag: moves Q001 from candidates.json into questions.json,
#    bumps questions_schema_version if schema changed (D-26).
```

### Anti-Patterns to Avoid
- **Monkey-patching `tool_executor.get_tools_definition`** — the graph calls the module-level function, not the instance method. See §Tool-Subset Isolation above.
- **Editing the `Agent` class to add a "disabled tools" parameter** — explicitly ruled out by D-15. Monkey-patch the symbol the graph imports.
- **Forgetting `reset_papers=True`** between questions — `Agent.query()` keeps a `persistent_papers` dict across calls (`agent.py:99`), which would leak state from Q001 into Q002. Call `agent.reset_papers()` or `agent.query(..., reset_papers=True)` between every question, for both conditions.
- **Running without recording `system_fingerprint`** — without it, reproducibility claims (D-25) are unverifiable. Every row in `runs.jsonl` and `scores.jsonl` must include it.
- **Using `response_format={"type":"json_object"}`** instead of `json_schema` — json_object only guarantees "is valid JSON", not "matches our rubric shape". Schema mode is a near-free upgrade on `gpt-4o-mini-2024-07-18+`.
- **Sending gold answer text to the judge** — we send only `gold_answer_keywords` and `gold_cited_arxiv_ids` (titles). Sending full expected answers would leak the answer into the prompt and bias the judge — explicitly forbidden by D-16.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Paired significance test | Custom bootstrap / sign test | `scipy.stats.wilcoxon(..., alternative="greater")` | Textbook paired-ordinal test; p-value and W statistic for free |
| JSON-mode output validation | Retry loops + try/except parsing | `response_format={"type":"json_schema", "json_schema":{..., "strict":True}}` | OpenAI runtime rejects invalid output; no parse errors possible |
| Token accounting | Custom tokeniser | `tiktoken.get_encoding("o200k_base")` (already imported in `sdk/deepxiv_sdk/agent/agent.py:15`) | Already in repo; matches model tokenisation |
| Tool-subset plumbing | Fork of `Agent` / `graph.py` | `unittest.mock.patch("deepxiv_sdk.agent.graph.get_tools_definition")` | No code fork; reversible; testable |
| Resume on interruption | Custom state file | `_load_done_pairs` pattern from `benchmark/run_benchmark.py:909` | Already in repo; behaviourally correct (retries errors, skips successes) |
| Position-bias mitigation | Nothing (trust the judge) | Randomise A/B label per question + record the mapping | Consensus mitigation in MT-Bench, Chatbot Arena, G-Eval literature (see sources) |

**Key insight:** 100% of Phase 8's primitives already exist in the codebase or as one-line imports. The work is to glue them together, not to build anything new.

---

## LLM-as-Judge Best Practices

Consensus from G-Eval (Liu et al. 2023, arXiv:2303.16634), Chatbot Arena / MT-Bench (Zheng et al. 2023, arXiv:2306.05685), and follow-up position-bias work (Shi et al. 2024, arXiv:2406.07791):

### 1. Paired comparison beats absolute scoring
Humans are noisy at absolute 1–5 ratings but reliable at A-vs-B preference. Our D-17 hybrid (ask for BOTH absolute dimension scores AND a pairwise preference) is the standard Chatbot Arena setup. Reported human–judge agreement is typically 65–85% on pairwise preference with GPT-4-class judges; `gpt-4o-mini` is slightly below that (expect ~60–75%) but sufficient for directional A/B signal. DATS5990 scope does not require human validation.

### 2. Position bias is real and systematic
Published result: swapping A/B order changes the verdict for 15–40% of items depending on judge and task (Shi et al. 2024). Mitigation consensus: **randomise** the A/B label (record the mapping so scores can be un-scrambled) and optionally **run both orders and average**. Given n=30 and cost under $1, running both orders is cheap — recommended as a stretch goal, not required by D-16.

### 3. Rubric dimensions should be orthogonal
Our four dimensions (correctness, faithfulness, citation_coverage, completeness) are the standard RAG-eval dimensions (RAGAS: Es et al. 2023, arXiv:2309.15217; TruLens "RAG triad"; LangSmith eval metrics):

| Our Dimension (D-17) | RAGAS Equivalent | TruLens Equivalent |
|----------------------|------------------|--------------------|
| `answer_correctness` | `answer_correctness` | `Answer Relevance` |
| `faithfulness` | `faithfulness` | `Groundedness` |
| `citation_coverage` | `context_recall` (analogue) | `Context Relevance` (analogue) |
| `completeness` | — (custom) | `Answer Comprehensiveness` |

These are well-motivated and publication-supported. `citation_coverage` is the custom dimension most tied to our hypothesis (citation-aware should cover more gold cited papers).

### 4. Provide evidence, not opinions
The judge prompt should **show** the tool-call trace so the judge can compute `faithfulness` by matching claims to retrieved evidence. Our `runs.jsonl` schema (D-13) records full `tool_calls` for this reason. Without them, the judge has to guess at grounding.

### 5. Keep the judge model separate from the agent model in theory; OK to share for DATS5990 scope
Best practice (MT-Bench): use a stronger judge than the agent. Here both are `gpt-4o-mini` (D-11) — this is noted as a limitation in G-Eval and accepted as a scope tradeoff for cost. FINDINGS must disclose this explicitly.

### Reference judge prompt structure (to be iterated per "Claude's Discretion")
```
System: You are an evaluator of two AI assistants' answers to a research-paper
question. Score each answer 1–5 on: answer_correctness, faithfulness (grounded
in the retrieved evidence shown), citation_coverage (how many of the listed
gold cited papers the answer draws on), completeness. Ignore style.

User:
Question: {question_text}
Gold cited papers (titles only): {titles}
Gold answer keywords: {keywords}

Answer A (tool_calls: {trace_a}):
{answer_a}

Answer B (tool_calls: {trace_b}):
{answer_b}

Return your verdict as JSON matching the provided schema.
```

---

## Runtime State Inventory

Phase 8 is greenfield — `eval/` does not exist yet. No rename / migration concerns. The only "runtime state" created by the phase is:
- `eval/results/runs.jsonl` — append-only; delete to rerun from scratch
- `eval/results/scores.jsonl` — append-only; same

Neither is cached outside the repo. `OPENAI_API_KEY` is the only required env var (D-24). Nothing else needs inventory.

---

## Common Pitfalls

### Pitfall 1: `seed` drift when OpenAI rotates model infrastructure
**What goes wrong:** Two runs a week apart with identical seed produce slightly different answers.
**Why it happens:** OpenAI rotates `system_fingerprint` on infra updates. Per their docs, this happens "a few times a year".
**How to avoid:** Record `system_fingerprint` in every JSONL row. If fingerprints don't match across a resume, FINDINGS should note it and optionally re-run the affected rows. Don't claim "fully deterministic" in the report.
**Warning signs:** Rerunning the same question gives a different tool call sequence.

### Pitfall 2: The monkey-patched `get_tools_definition` is scoped to the wrong module
**What goes wrong:** You patch `deepxiv_sdk.agent.tools.get_tools_definition` but the graph has already imported the symbol, so the patch has no effect.
**Why it happens:** Python imports bind at import time — `from .tools import get_tools_definition` in `graph.py` creates a new name in the graph module.
**How to avoid:** Always patch `deepxiv_sdk.agent.graph.get_tools_definition` (the consumer's name), not `deepxiv_sdk.agent.tools.get_tools_definition` (the definition's name). Verify with a test that inspects the `tools` kwarg passed to `client.chat.completions.create`.

### Pitfall 3: `fetch_cited_paper_sections` returning empty strings
**What goes wrong:** The Agent calls `fetch_cited_paper_sections` on a seed paper whose references are all external to the corpus, and the tool returns `"No in-corpus cited papers with sections found"`. The citation-aware agent now answers with no extra evidence, and the A/B comparison becomes a tie — wasting a question.
**Why it happens:** Silent-skip semantics of `fetch_cited_paper_sections` (tools.py:709). This is **intended** behaviour per CONTEXT.md "Specific Ideas".
**How to avoid:** `build_questions.py` enforces ≥3 in-corpus citations with non-empty `sections` before accepting a candidate (D-07). This is the primary defence. Additionally: if a question's citation-aware run records zero `fetch_cited_paper_sections` tool calls or all returned empty, FINDINGS should flag it as a "degenerate" question and exclude it from the headline win-rate.
**Warning signs:** `citation_aware` row has `tool_calls` without any `fetch_cited_paper_sections` entry, or that entry's result length < 200 chars.

### Pitfall 4: Judge position bias swamps the signal
**What goes wrong:** The judge systematically prefers whichever answer is labelled "A" (or "B"), and the measured win-rate reflects that bias rather than quality.
**Why it happens:** Documented systematic bias; see G-Eval / MT-Bench / Shi et al. 2024.
**How to avoid:** Randomise A/B per question using a seeded RNG (record the mapping per `scores.jsonl` row). Optionally run both orders and average — cheap at n=30. FINDINGS should include a section that checks "in how many cases did A match baseline vs citation_aware" — if balanced, randomisation worked.

### Pitfall 5: Hitting `max_llm_calls=20` on citation-aware runs
**What goes wrong:** Citation-aware agent makes more tool calls (reads references → fetches sections → reads sections) and hits the 20-call cap before composing a final answer.
**Why it happens:** Each `fetch_cited_paper_sections` returns up to 5 papers' sections; the agent may want to explore more.
**How to avoid:** `max_llm_calls=20` is locked by D-12 to keep conditions comparable. Instead, emit a `hit_limit=True` row (D-13) and let `analyze.py` report how often each condition was truncated. If >20% of citation-aware runs truncate, FINDINGS must disclose that the measured quality is a lower bound and recommend re-running with `max_llm_calls=30`.
**Warning signs:** Per-question `llm_calls=20` with no answer or a very short answer.

### Pitfall 6: `temperature=0.0` still produces flaky outputs across runs
**What goes wrong:** Despite `temperature=0.0` and `seed=42`, two runs of the same question produce different final answers.
**Why it happens:** Empirical observation: zero temperature reduces variance dramatically but does not eliminate it on any production OpenAI deployment (floating-point non-associativity + batch routing). Seed further tightens it but doesn't guarantee.
**How to avoid:** This is unavoidable. Record `system_fingerprint` (D-25). If a re-run is needed, note it in FINDINGS. Do not make "exactly reproducible" claims — say "reproducible modulo provider non-determinism."

### Pitfall 7: OpenAI quota / rate limit interrupts the overnight run
**What goes wrong:** 429 mid-run; `eval/run_eval.py` exits; partial results in `runs.jsonl`.
**Why it happens:** Free/Tier-1 accounts have 500 RPM / 10 000 TPM on `gpt-4o-mini`; an interactive Agent can burst.
**How to avoid:** The runner is resumable (D-14). On 429, catch the exception, write an errored row (`error="RateLimitError: ..."`), and continue. On next invocation with `--resume`, errored rows are retried (matches `benchmark` pattern).
**Warning signs:** Multiple rows with `error` containing "rate_limit".

### Pitfall 8: The judge produces schema-valid but semantically wrong JSON
**What goes wrong:** Schema mode guarantees the JSON parses, but the judge might return `citation_coverage=5` for an answer that didn't cite anything.
**Why it happens:** Structured outputs enforces shape, not correctness.
**How to avoid:** This is exactly why D-19 mandates the deterministic grounding check. If the judge's `citation_coverage` disagrees with the deterministic count by >1 bucket on >20% of questions, the report flags the judge as unreliable on that dimension.

---

## Code Examples

### Verified Pattern: OpenAI chat.completions.create with seed + JSON schema
```python
# Source: https://platform.openai.com/docs/api-reference/chat/create (verified 2026-04-21)
# Source: https://platform.openai.com/docs/guides/structured-outputs
from openai import OpenAI
client = OpenAI()

resp = client.chat.completions.create(
    model="gpt-4o-mini",
    seed=42,
    temperature=0.0,
    max_tokens=1024,
    response_format={
        "type": "json_schema",
        "json_schema": {"name": "verdict", "schema": {...}, "strict": True},
    },
    messages=[{"role": "system", "content": SYSTEM},
              {"role": "user", "content": USER}],
)
content = resp.choices[0].message.content
fingerprint = resp.system_fingerprint
prompt_tokens = resp.usage.prompt_tokens
completion_tokens = resp.usage.completion_tokens
```

### Verified Pattern: scipy Wilcoxon signed-rank
```python
# Source: https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.wilcoxon.html (verified 2026-04-21)
from scipy.stats import wilcoxon
# x: citation_aware scores; y: baseline scores; alternative: 'greater' tests
# that citation_aware's median > baseline's median.
stat, p = wilcoxon(x, y, alternative="greater", zero_method="wilcox")
# stat is the sum of ranks of positive differences (W+); p is the one-sided p-value.
```

### Verified Pattern: Monkey-patch with context manager
```python
from unittest.mock import patch
with patch("deepxiv_sdk.agent.graph.get_tools_definition",
           return_value=[t for t in full_tools if t["function"]["name"] != "fetch_cited_paper_sections"]):
    answer = agent.query("...", reset_papers=True)
```

### Verified Pattern: JSONL append + resume (mirrors benchmark/run_benchmark.py:909)
```python
import json
from pathlib import Path

def load_done(path: Path) -> set:
    if not path.exists():
        return set()
    out = set()
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("error"):
            continue
        out.add((row["question_id"], row["condition"]))
    return out

def append_row(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        f.flush()
```

### Verified Pattern: unittest.mock for OpenAI client (per sdk/tests/test_cli.py:60)
```python
from unittest.mock import patch, MagicMock

@patch("eval.score.OpenAI")  # patch at the import path where score.py uses it
def test_score_happy_path(mock_openai_cls):
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content='{"a":{...},"b":{...},"preference":"b","confidence":4,"justification":"..."}'))]
    mock_resp.system_fingerprint = "fp_test"
    mock_client.chat.completions.create.return_value = mock_resp
    mock_openai_cls.return_value = mock_client
    from eval.score import score_pair
    row = score_pair(...)
    assert row["judge_preference"] in ("baseline", "citation_aware", "tie")
```

---

## Dependencies & Environment

**Append to `pyproject.toml` (new optional group, keeps core deps lean):**
```toml
[project.optional-dependencies]
eval = [
    "openai>=1.50.0",
    "scipy>=1.11",
    "matplotlib>=3.8",
    "pandas>=2.0",
    "notebook>=7.0",
]
```

Install via `pip install -e ".[eval]"`.

**Env vars:**
- `OPENAI_API_KEY` — required for real runs (D-24). Tests mock the client and do not read this.

**External services:**
- Backend API at `http://localhost:8000` — required for Agent runs and for `build_questions.py` (calls `Reader.references()` and `Reader.head()` on corpus papers).
- No Docker changes. Eval scripts run on the host, against the running docker-compose stack.

**Python version:** 3.11 (matches `pyproject.toml:requires-python`).

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Absolute 1–5 rating by LLM judge | Paired preference + absolute 1–5 | 2023 (Chatbot Arena / MT-Bench) | Much lower variance; our D-17 follows this |
| `response_format={"type":"json_object"}` | `response_format={"type":"json_schema", "strict":True}` | 2024-08 (Structured Outputs release) | No retry loops; schema-guaranteed output |
| No `seed` on OpenAI API | `seed` + `system_fingerprint` | 2023-11 (Chat Completions update) | Near-reproducibility; fingerprint tracking mandatory |
| `gpt-4` as judge | `gpt-4o-mini` as judge where cost matters | 2024 | 10× cheaper; slightly worse human-alignment; disclose in FINDINGS |
| t-test on absolute scores | Wilcoxon signed-rank on paired deltas | Standard stats practice | Correct test for ordinal + paired |

---

## Open Questions

1. **Should we run both A/B orders for the judge and average?**
   - What we know: Reduces position bias; costs ~$0.02 extra; trivially implementable.
   - What's unclear: Whether CONTEXT.md author considers this in scope (not mentioned in D-16).
   - Recommendation: Include as a `--swap` flag in `score.py`, off by default. FINDINGS can note whether it changes the headline win-rate.

2. **How to handle questions where both conditions fail (`hit_limit=True` or `error != None`)?**
   - What we know: Such rows should not contribute to win-rate, only to failure-mode analysis.
   - What's unclear: Whether we still run the judge on them (might judge an error string).
   - Recommendation: `score.py` skips rows where either condition has `error != None`; records a "both_failed" entry in `scores.jsonl` with null rubric values. `analyze.py` reports these separately.

3. **Does `gpt-4o-mini-2024-07-18` produce the same answer as the latest alias for a given seed?**
   - What we know: OpenAI pins model snapshots; the alias `gpt-4o-mini` may route to a newer snapshot that differs under the same seed.
   - What's unclear: Whether to pin to `gpt-4o-mini-2024-07-18` or use the alias.
   - Recommendation: Pin to a specific dated snapshot (e.g., `gpt-4o-mini-2024-07-18`) in a `MODEL_ID` constant in `eval/run_eval.py` and record it in every row. Reproducibility > always-latest.

4. **Judge model vs agent model — share or separate?**
   - What we know: D-11 locks both to `gpt-4o-mini`. Best practice is a stronger judge (GPT-4-class).
   - What's unclear: Whether to add a `--judge-model` override for stretch goal comparison.
   - Recommendation: Accept D-11 as-is for DATS5990 scope; disclose the shared-model limitation in FINDINGS methodology section.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (already in project: `pytest`, `pytest-timeout`) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` — `testpaths = ["tests"]` |
| Quick run command | `pytest tests/test_eval.py -x -q` |
| Full suite command | `pytest tests/ -x -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| EVAL-01 | `build_questions.py --promote Q001` moves candidate into `questions.json` | unit (mock Reader) | `pytest tests/test_eval.py::test_promote_moves_candidate -x` | ❌ Wave 0 |
| EVAL-01 | `build_questions.py` rejects candidates with <3 in-corpus refs | unit | `pytest tests/test_eval.py::test_reject_insufficient_refs -x` | ❌ Wave 0 |
| EVAL-01 | `questions.json` schema-valid on load | unit | `pytest tests/test_eval.py::test_questions_schema -x` | ❌ Wave 0 |
| EVAL-02 | Baseline condition tools passed to OpenAI do NOT include `fetch_cited_paper_sections` | unit (MagicMock OpenAI client) | `pytest tests/test_eval.py::test_baseline_tool_subset -x` | ❌ Wave 0 |
| EVAL-02 | Citation-aware condition tools DO include `fetch_cited_paper_sections` | unit | `pytest tests/test_eval.py::test_citation_aware_tools -x` | ❌ Wave 0 |
| EVAL-02 | `run_eval.py --resume` skips already-recorded `(qid, cond)` pairs | unit (fixture JSONL) | `pytest tests/test_eval.py::test_resume_skips_done -x` | ❌ Wave 0 |
| EVAL-02 | `run_eval.py --resume` retries errored rows | unit | `pytest tests/test_eval.py::test_resume_retries_errors -x` | ❌ Wave 0 |
| EVAL-03 | `score.py` parses valid judge JSON into `scores.jsonl` row | unit (mock OpenAI) | `pytest tests/test_eval.py::test_score_parser -x` | ❌ Wave 0 |
| EVAL-03 | `deterministic_citation_coverage()` counts gold IDs in tool calls | unit | `pytest tests/test_eval.py::test_deterministic_grounding -x` | ❌ Wave 0 |
| EVAL-04 | `analyze.py` computes mean delta and win-rate per dimension | unit | `pytest tests/test_eval.py::test_aggregation_math -x` | ❌ Wave 0 |
| EVAL-04 | `FINDINGS.md` contains required sections | smoke (string search on generated file) | `pytest tests/test_eval.py::test_findings_sections -x` | ❌ Wave 0 |
| EVAL-* | Optional live smoke: one question against real `gpt-4o-mini` | integration (skipped if no key) | `pytest tests/test_eval.py::test_live_smoke -x -m live` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_eval.py -x -q`
- **Per wave merge:** `pytest tests/ -x -q`
- **Phase gate:** All `test_eval` tests green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_eval.py` — covers all EVAL requirements above
- [ ] `tests/fixtures/mock_questions.json` — 3-item question set for unit tests
- [ ] `tests/fixtures/mock_runs.jsonl` — 4 rows (2 questions × 2 conditions) for resume and aggregation tests
- [ ] `eval/rubric.md` — written first so judge prompt and test expectations reference the same document

*(No existing test infrastructure covers eval requirements — all test artefacts are Wave 0 creates. The test patterns themselves are established in `sdk/tests/test_agent.py` and `sdk/tests/test_cli.py`.)*

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| **R1. Judge position bias produces biased win-rate** | MEDIUM | HIGH — invalidates primary finding | Seeded random A/B label per question; record mapping in `scores.jsonl`; optional `--swap` flag to run both orders; FINDINGS reports A vs B assignment balance as a sanity check |
| **R2. `gpt-4o-mini` seed non-determinism drifts over run duration** | MEDIUM | MEDIUM — small reproducibility gap | Record `system_fingerprint` in every row (D-25); pin to dated model snapshot (e.g., `gpt-4o-mini-2024-07-18`); FINDINGS language says "reproducible modulo provider drift" |
| **R3. `fetch_cited_paper_sections` returns empty for valid questions (tool says "No in-corpus cited papers")** | MEDIUM | HIGH — turns citation-aware wins into ties | `build_questions.py` enforces ≥3 in-corpus cites with non-empty sections at candidate time (D-07); `analyze.py` flags questions with zero non-empty `fetch_cited_paper_sections` calls and excludes from headline win-rate |
| **R4. OpenAI API rate-limit / quota during overnight run** | MEDIUM | LOW — resumable | `run_eval.py` is resumable by (question_id, condition) per D-14; catches rate-limit errors and writes errored row; `--resume` retries errored rows next invocation |
| **R5. Agent hits `max_llm_calls=20` on citation-aware more often than baseline** | LOW | MEDIUM — biases cost/latency comparison | Emit `hit_limit=True` per D-13; `analyze.py` reports truncation rate per condition; if >20% truncation, FINDINGS recommends rerun with higher cap |
| **R6. Judge schema-valid but semantically wrong (e.g. gives citation_coverage=5 with no citations)** | LOW | MEDIUM — misleads FINDINGS | Deterministic grounding counter (D-19) cross-checks every judge verdict on `citation_coverage`; if judge disagrees by >1 bucket on >20% of questions, FINDINGS reports judge unreliability |
| **R7. Wilcoxon is underpowered at n=30 if true effect is small** | MEDIUM | LOW — is a null result the hypothesis allows | FINDINGS reports mean/median delta regardless of p-value; honestly labels null results; does not claim effect if n is too small |
| **R8. Test mocks fall out of sync with real `openai` SDK structure** | LOW | LOW — caught by optional live smoke | Optional live `test_live_smoke` runs one real call against `gpt-4o-mini` when `OPENAI_API_KEY` is present; skipped otherwise |

---

## Discrepancies with CONTEXT.md (minor)

These do NOT change the phase boundary or success criteria. They are wording-level corrections the planner should make.

1. **D-08 tool names do not match the SDK.** CONTEXT.md lists "`search_papers`, `get_paper_head`, `get_paper_brief`, `get_paper_sections`, `get_references`, `get_cited_by`" as baseline tools. The actual tool names in `sdk/deepxiv_sdk/agent/tools.py:16–217` are:
   - `search_papers`, `load_paper`, `read_section`, `get_full_paper`, `get_paper_preview`, `quick_preview`, `get_references`, `get_cited_by`, `fetch_cited_paper_sections`.
   - The intent is clear: "every tool EXCEPT `fetch_cited_paper_sections`." The plan should use the verified tool names. There is no tool named `get_paper_head` / `get_paper_brief` / `get_paper_sections` in the SDK.

2. **D-15 patch target is wrong.** CONTEXT.md says "replace `agent.tool_executor.get_tools_definition()` return value". The graph (`sdk/deepxiv_sdk/agent/graph.py:12, 223`) calls the **module-level** `get_tools_definition()` imported from `deepxiv_sdk.agent.tools`, not the instance method on `ToolExecutor`. The correct target is the module symbol `deepxiv_sdk.agent.graph.get_tools_definition` (or equivalently `unittest.mock.patch("deepxiv_sdk.agent.graph.get_tools_definition")`). See §Tool-Subset Isolation for the verified example.

Both fixes are one-line changes to the plan; no phase-scope impact.

---

## Sources

### Primary (HIGH confidence)
- OpenAI Chat Completions API reference — `seed`, `response_format`, `tool_choice`, `system_fingerprint`: https://platform.openai.com/docs/api-reference/chat/create
- OpenAI Structured Outputs guide — `json_schema` vs `json_object`, `strict:true`, model support on `gpt-4o-mini-2024-07-18+`: https://platform.openai.com/docs/guides/structured-outputs
- OpenAI Reproducibility guide / cookbook — `seed` is best-effort, record `system_fingerprint`: https://cookbook.openai.com/examples/reproducible_outputs_with_the_seed_parameter
- scipy `wilcoxon` reference — paired signed-rank test: https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.wilcoxon.html
- `sdk/deepxiv_sdk/agent/tools.py` (lines 9, 221–711) — full tool list, `ToolExecutor`, `fetch_cited_paper_sections` silent-skip behaviour
- `sdk/deepxiv_sdk/agent/graph.py` (lines 12, 223) — confirms module-level `get_tools_definition` is the tool source
- `sdk/deepxiv_sdk/agent/agent.py` (lines 46–99, 101–168) — confirms `citation_depth`, `seed`-independent knobs, and `reset_papers` semantics
- `benchmark/run_benchmark.py` (lines 905–960) — resumable JSONL-ish runner pattern to mirror
- `sdk/tests/test_cli.py` (lines 60–130) — `@mock.patch` pattern on client class

### Secondary (MEDIUM confidence — consulted literature, not code-verified)
- Liu et al. 2023, "G-EVAL: NLG Evaluation using GPT-4 with Better Human Alignment", arXiv:2303.16634 — absolute + form-filling rubric on 1–5
- Zheng et al. 2023, "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena", arXiv:2306.05685 — pairwise preference, position-bias quantification, swap-and-average mitigation
- Shi et al. 2024, "Judging the Judges: A Systematic Investigation of Position Bias in Pairwise Comparative Assessments by LLMs", arXiv:2406.07791 — 15–40% verdict flip under position swap
- Es et al. 2023, "Ragas: Automated Evaluation of Retrieval Augmented Generation", arXiv:2309.15217 — faithfulness / answer_correctness / context_recall dimensions
- TruLens docs — "RAG triad" (Context Relevance, Groundedness, Answer Relevance): https://www.trulens.org/
- LangSmith evaluator catalog — correctness, groundedness, conciseness evaluators: https://docs.smith.langchain.com/evaluation/how_to_guides/evaluators
- Conover, *Practical Nonparametric Statistics* (3rd ed., 1999) — Wilcoxon asymptotic validity for n≥20

### Tertiary (LOW confidence — verify at implementation)
- Whether the current `gpt-4o-mini` alias routes to `gpt-4o-mini-2024-07-18` or a newer snapshot on 2026-04-21 — recommend pinning to a dated snapshot in code.
- Exact `usage.prompt_tokens_details.cached_tokens` field name for prompt-cache accounting if we want to report cache hits (not required by D-13).

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — openai, scipy, pandas are mature; `response_format={"type":"json_schema"}` verified against current OpenAI docs
- Architecture: HIGH — every primitive exists in the repo; tool-subset isolation verified by reading graph.py and tools.py
- Tool isolation mechanics (D-15 correction): HIGH — directly read from `sdk/deepxiv_sdk/agent/graph.py:12` and `:223`
- Statistical test: HIGH — Wilcoxon signed-rank is textbook for this setup
- Judge best practices: MEDIUM-HIGH — consensus from 2023–2024 literature; still an active research area, but our rubric dimensions are stable
- Pitfalls: HIGH — most come from reading the SDK source + OpenAI official docs
- Cost/risk estimates: MEDIUM — rely on OpenAI published pricing and empirical rate-limit behaviour on Tier-1 accounts

**Research date:** 2026-04-21
**Valid until:** 2026-07-21 (OpenAI API surface is stable; re-verify `gpt-4o-mini` snapshot alias before pinning)
