# Phase 8: Agent Evaluation - Context

**Gathered:** 2026-04-21
**Status:** Ready for planning

<domain>
## Phase Boundary

Empirical evaluation of the citation-aware Agent (SDK-04) that was shipped in Phase 6. Phase 6 proved the code works (unit + contract + integration tests pass); Phase 8 proves the capability *matters* — i.e. reading cited-paper sections produces better answers than reading titles only.

**In scope:**
- Construct a reproducible question set grounded in the corpus (≥30 questions, each with a seed paper and gold-truth cited-paper evidence)
- Run both Agent conditions on every question: baseline (titles-only via `get_references` / `get_cited_by`) and citation-aware (`fetch_cited_paper_sections`, `citation_depth≥1`)
- Score paired answers with an LLM-as-judge rubric (4 dimensions, 1–5 scale) and a separate human-verifiable grounding check
- Write findings: paired win-rate, mean-score delta per dimension, cost/latency overhead, default-depth recommendation
- Produce one analysis notebook with win-rate + score-delta visualisations

**Out of scope:**
- Any backend/API changes (Phase 8 is evaluation only)
- New agent tools, new Reader methods, new endpoints
- Human annotation of answer quality (LLM-as-judge only; reproducible)
- Training or fine-tuning any model
- Cross-model comparison (one LLM per paired run; locked seed)

This phase does **not** modify `app/`, `sdk/`, or `benchmark/`. All new code lives in `eval/`.
</domain>

<decisions>
## Implementation Decisions

### Directory layout
- **D-01:** New self-contained `eval/` directory at project root. Mirrors `benchmark/` structure.
- **D-02:** Artefact layout:
  - `eval/questions.json` — canonical question set (≥30 items)
  - `eval/rubric.md` — scoring rubric, human-readable
  - `eval/build_questions.py` — constructs/refreshes `questions.json` from the live corpus
  - `eval/run_eval.py` — paired A/B runner (baseline + citation-aware)
  - `eval/score.py` — LLM-as-judge scorer + grounding check
  - `eval/analyze.py` — aggregation + `FINDINGS.md` writer
  - `eval/FINDINGS.md` — formal report
  - `eval/notebook/eval_analysis.ipynb` — matplotlib charts
  - `eval/results/runs.jsonl` — per-question, per-condition answer traces
  - `eval/results/scores.jsonl` — per-question, per-condition rubric scores
  - `tests/test_eval.py` — unit tests for question constructor + scorer

### Question set design
- **D-03:** **Exactly 30 questions minimum**, curated from the corpus. Stratified by question type:
  - 10 × "method-dependency" questions — "How does paper X adapt/extend the method from one of its cited works?" (forces agent to read cited paper)
  - 10 × "comparative" questions — "How does paper X's approach differ from prior work Y it cites?" (forces reading both)
  - 10 × "claim-grounding" questions — "What evidence does paper X cite to support claim Z?" (forces citation traversal)
- **D-04:** Each question entry schema:
  ```json
  {
    "question_id": "Q001",
    "question_type": "method-dependency" | "comparative" | "claim-grounding",
    "seed_arxiv_id": "2401.xxxxx",
    "gold_cited_arxiv_ids": ["1706.03762", ...],     // in-corpus papers the agent MUST read
    "gold_answer_keywords": ["attention", "transformer", ...],  // phrases a correct answer contains
    "question_text": "How does paper X ...",
    "human_notes": "Why this question tests citation reading"
  }
  ```
- **D-05:** Question construction is **semi-automatic**: `build_questions.py` proposes candidates from citation-graph structure (seed papers with ≥3 in-corpus references) + LLM-generated question text, then a human curator promotes candidates into `questions.json` by running `--promote Q001`. The proposed-vs-promoted separation keeps the set reproducible.
- **D-06:** Seed papers are drawn exclusively from the 150-paper benchmark sample (`benchmark/sample.json`) so Phase 7 parser quality data is directly relevant to any observed Agent failure modes.
- **D-07:** `gold_cited_arxiv_ids` MUST resolve to papers where `Reader.head().sections` is non-empty (i.e. actually in the parsed corpus). `build_questions.py` enforces this.

### Agent conditions
- **D-08:** **Baseline condition** (`baseline`): standard Agent with `citation_depth=0`. Tools available: `search_papers`, `load_paper`, `read_section`, `get_full_paper`, `get_paper_preview`, `quick_preview`, `get_references` (titles only), `get_cited_by` (titles only). `fetch_cited_paper_sections` tool **disabled** via monkey-patching the module-level `get_tools_definition` (see D-15) before the run. (Tool names verified against `sdk/deepxiv_sdk/agent/tools.py`.)
- **D-09:** **Citation-aware condition** (`citation_aware`): standard Agent with `citation_depth=1`. All tools available including `fetch_cited_paper_sections`.
- **D-10:** Both conditions use **identical LLM + temperature + seed + prompts**. Only the available tool set and `citation_depth` differ.
- **D-11:** LLM used: `gpt-4o-mini` at `temperature=0.0`, `seed=42`. Cheap enough for 2 × 30 = 60 runs per experiment; deterministic enough to make paired comparison meaningful. The same LLM is used for the **judge** in `score.py` with a separate prompt — standard practice and OK for DATS5990 scope.
- **D-12:** `max_llm_calls=20`, `max_time_seconds=600`, `max_tokens=4096` — same as SDK default. Emits clean failure rows if either Agent hits a limit.

### Paired runner
- **D-13:** `eval/run_eval.py` iterates questions sequentially (simpler than parallel; 60 total runs). Writes one JSONL row per (question_id, condition) to `eval/results/runs.jsonl`:
  ```json
  {
    "question_id": "Q001",
    "condition": "baseline" | "citation_aware",
    "answer": "...",
    "tool_calls": [{"name": "...", "args": {...}, "result": "..."}],
    "tokens_prompt": 12345,
    "tokens_completion": 678,
    "wallclock_seconds": 42.1,
    "llm_calls": 7,
    "hit_limit": false,
    "error": null
  }
  ```
- **D-14:** Resumable: runner skips `(question_id, condition)` pairs already present in `runs.jsonl`. Idempotent — can be interrupted mid-run.
- **D-15:** Baseline condition is implemented by monkey-patching the **module-level** function `deepxiv_sdk.agent.graph.get_tools_definition` (imported into `graph.py`, not the `ToolExecutor` instance method) to return a filtered list that excludes `fetch_cited_paper_sections`. Confirmed by reading `sdk/deepxiv_sdk/agent/graph.py:12,223`. Setting `citation_depth=0` on the baseline provides defence-in-depth: `fetch_cited_paper_sections` in `tools.py:694` caps paper fetches at `citation_depth * 5`, so depth 0 → 0 papers even if the tool is mistakenly exposed. No Agent class edits required.

### Scoring (LLM-as-judge)
- **D-16:** `eval/score.py` invokes `gpt-4o-mini` as judge. The judge sees: question text, gold_cited_arxiv_ids (titles only, not full text — avoids leakage), gold_answer_keywords, and **both** answers side-by-side (anonymised as A/B, random order per question to avoid position bias).
- **D-17:** Scoring rubric — four 1–5 dimensions per answer:
  1. **answer_correctness** — does the answer factually match the question's intent?
  2. **faithfulness** — are claims supported by evidence the agent actually retrieved (per `tool_calls`)? (avoids hallucination)
  3. **citation_coverage** — how many of `gold_cited_arxiv_ids` did the agent actually invoke a tool against?
  4. **completeness** — does the answer cover all sub-parts of the question?
- **D-18:** Score schema per `scores.jsonl` row:
  ```json
  {
    "question_id": "Q001",
    "baseline": {"answer_correctness": 3, "faithfulness": 4, "citation_coverage": 1, "completeness": 2, "justification": "..."},
    "citation_aware": {"answer_correctness": 5, "faithfulness": 5, "citation_coverage": 4, "completeness": 4, "justification": "..."},
    "judge_preference": "citation_aware" | "baseline" | "tie",
    "judge_confidence": 1-5
  }
  ```
- **D-19:** A **deterministic** grounding check runs alongside the LLM judge: count how many `gold_cited_arxiv_ids` appear in each condition's `tool_calls` → `citation_coverage` dimension is computed both by the judge AND by this deterministic counter; report both in FINDINGS for cross-validation. If they disagree significantly, the LLM judge is wrong and FINDINGS flags the issue.
- **D-20 (2026-04-21, Phase 8 Wave 0 execution):** `gold_cited_arxiv_ids` require only **`in_corpus=True` + resolvable `arxiv_id`**; non-empty sections on the cited paper are **not** required. Rationale: our 105k-paper corpus is metadata-mostly (~160 papers have parsed sections) because GROBID primary parsing has only been run on the 150 benchmark seeds. The agent uses `reader.head(aid)` which returns `{title, abstract, year, arxiv_id}` regardless of section presence -- sufficient to ground method-dependency / comparative / claim-grounding questions. This relaxes the stricter invariant in 08-01-PLAN.md's "shared_conventions.cited_paper_must_have_sections" so that Wave 0 can produce a 10/10/10 question set. The paired A/B contrast (with-tools vs title-only) still reveals whether citation-aware agents outperform baselines -- the evaluation does not *require* the cited paper to be fully parseable, only that it be citeable from the corpus. Implemented in `eval/build_questions.py:_has_min_in_corpus_cites`, `_in_corpus_cited_arxiv_ids`, and `promote_candidate`.

### Analysis & reporting
- **D-20:** `eval/analyze.py` → `eval/FINDINGS.md` with sections: Methodology, Question-Set Composition, Per-Dimension Score Comparison (table of mean & delta per condition), Paired Win-Rate (how often citation_aware beat baseline per question), Cost/Latency Tradeoff (extra tokens + wallclock for citation-aware), Failure Modes (qualitative — questions where both failed, questions where only citation-aware succeeded), Depth Recommendation (defaulting `citation_depth=1` based on observed grounding uplift vs. cost).
- **D-21:** Notebook `eval/notebook/eval_analysis.ipynb` with ≥4 matplotlib cells: (a) grouped bar chart of mean per-dimension scores, (b) histogram of pairwise score deltas (citation_aware − baseline), (c) scatter plot of extra tokens vs. score uplift per question, (d) box plot of wallclock per condition.
- **D-22:** A question is an "unambiguous win" for citation-aware if (mean-4-dim-score delta ≥ +1.0) AND (deterministic_citation_coverage delta ≥ +1). Used for headline win-rate in FINDINGS.

### Test strategy
- **D-23:** `tests/test_eval.py` covers: (1) `build_questions.py` promote/reject flow, (2) `run_eval.py` tool-subset isolation (baseline cannot call `fetch_cited_paper_sections`), (3) `score.py` rubric parser (valid judge JSON → valid scores row), (4) `analyze.py` aggregation math (delta computation, win-rate computation) — all mocked, no live OpenAI calls.
- **D-24:** LLM-touching code uses `OPENAI_API_KEY` env var; tests inject a `MagicMock` for the OpenAI client. One optional live smoke-test fixture runs against `gpt-4o-mini` if key is present (skipped otherwise via `pytest.importorskip`).

### Reproducibility
- **D-25:** Both `runs.jsonl` and `scores.jsonl` record the LLM model name + prompt hash + seed so the experiment can be reconstructed exactly.
- **D-26:** Question set (`questions.json`) is version-controlled. Any change bumps `questions_schema_version` inside the file.

### Wave 1 execution (2026-04-21) refinements

- **D-27 (Wave 1 condition naming + output layout):** Plan 08-02 as written specified `baseline` (all tools except `fetch_cited_paper_sections`, per D-08/D-15) vs `citation_aware` (all tools) into a single `eval/results/runs.jsonl`. Wave 1 instead ships a stricter, cleaner A/B contrast aligned with the parent-session user spec:
    - **`with_tools`**: the existing `deepxiv_sdk.agent.Agent(citation_depth=1)` with full tool access to the live Reader API at `http://localhost:8000`.
    - **`title_only`**: a direct `gpt-4o-mini` chat completion with no tools at all; the model is given only the seed paper's title + abstract (retrieved once up-front via `Reader.head(seed_arxiv_id)`) and must answer from that alone.

    Rationale:
    1. Under **D-20** the cited-paper sections are empty for most of the corpus, so the plan's `baseline`/`citation_aware` split (differing only in whether `fetch_cited_paper_sections` is exposed) would produce a degenerate contrast — `fetch_cited_paper_sections` returns empty content either way. `with_tools` vs `title_only` instead measures the cleanly separable effect of "any Reader access vs none".
    2. The SDK's real `Agent` API (verified against `sdk/deepxiv_sdk/agent/agent.py`) is `Agent(api_key, reader, model, ...)` with `.query(question, reset_papers=True) -> str` — it does not accept `base_url` directly, nor does `query()` return a dict. The plan's `Agent.run()` + `reset_papers=True` constructor kwarg pseudo-code is pre-factual. The runner therefore uses the real API shape (instantiate `Reader(base_url=...)` explicitly and pass it into `Agent(...)`; call `agent.query(q, reset_papers=True)`).
    3. The user-facing spec requires per-condition output directories and a top-level `manifest.json` with aggregated metrics, not a single JSONL.
- **D-28 (Model pin):** Wave 1 pins both the agent and (deferred) judge to `gpt-4o-mini` with `temperature=0.0` and `seed=42` per D-11. `gpt-4o` (the plan's `DEFAULT_MODEL`) is not used; it was an artifact of plan drafting.
- **D-29 (Results directory is ephemeral, gitignored):** `eval/results/` is the empirical output root and is added to `.gitignore`. Only runner code, schemas, tests, and this context document are version-controlled. Results must be regenerated by running `python eval/run_eval.py` against a live stack.
- **D-30 (Tool-call capture via non-invasive wrapping):** The runner captures agent tool calls by wrapping `agent.tool_executor.execute_tool_call` and `agent.client.chat.completions.create` at instance-attribute level. No edits to `sdk/deepxiv_sdk/**` — Anti-Pattern 2 holds. This is strictly more capable than the plan's monkey-patch of `deepxiv_sdk.agent.graph.get_tools_definition` because the plan's baseline would have no tool-exclusion effect under D-20 (see D-27.1).
- **D-31 (Output schema per row, D-13 descendant):** Each JSONL row is `{run_id, question_id, condition, model, seed, timestamp, prompt_hash, system_fingerprint, answer_text, tool_calls[], tokens_used{prompt,completion,total}, latency_s, error}`. `tool_calls` is `[]` for `title_only` by construction.

### Claude's Discretion
- Exact prompt wording for `build_questions.py` proposal step
- Exact judge prompt (may iterate to reduce position-bias variance)
- Whether to use `structured outputs` (JSON mode) vs freeform-parse on the judge response
- Whether to record per-tool-call latency or only total wallclock
- Whether `eval/notebook/` has a single .ipynb or multiple per question-type
</decisions>

<specifics>
## Specific Ideas

- **Paired test is critical.** The same 30 questions must be answered by both conditions; we care about *delta* per question, not absolute quality. A Wilcoxon signed-rank test on per-question score deltas is a more honest statistic than a mean comparison across independent samples.
- **Position bias mitigation.** Randomise which answer is labelled "A" vs "B" per question before showing to the judge. Record the order so the unscramble is deterministic.
- **Tool-subset isolation.** The cleanest way to disable `fetch_cited_paper_sections` in the baseline is: instantiate the Agent normally, then replace `agent.tool_executor.get_tools_definition` with a lambda that filters out the citation-fetch tool. Do NOT fork the Agent class.
- **Silent-skip semantics.** `fetch_cited_paper_sections` already silently skips cited papers not in corpus. We want to keep this; the question set should only require in-corpus evidence, so the citation-aware agent has a real chance.
- **Cost estimate.** 60 runs × (Agent: ~10K prompt + 2K completion) × `gpt-4o-mini` = ~$0.05 for the Agent runs. 30 × (judge: ~3K prompt + 500 completion) = ~$0.02 for judging. Total well under $1.
- **Citation-aware overhead.** Each `fetch_cited_paper_sections` call retrieves up to 5 in-corpus papers' full sections — roughly 5–15K extra tokens per agent turn. This is the cost citation-aware pays for the quality uplift, and is exactly what we want to measure.
- **Tie with Phase 7.** Seed papers come from `benchmark/sample.json`. If an observed Agent failure traces back to a parser issue (e.g. missing reference because MinerU failed on that paper), FINDINGS should reference the corresponding row in `benchmark/FINDINGS.md`.
</specifics>

<canonical_refs>
## Canonical References

### Upstream-to-Phase-8 interfaces
- `sdk/deepxiv_sdk/agent/agent.py:Agent.__init__` — already takes `citation_depth: int = 1` (added in 06-03)
- `sdk/deepxiv_sdk/agent/tools.py:ToolExecutor.__init__` — already takes `citation_depth` and exposes `get_references`, `get_cited_by`, `fetch_cited_paper_sections`
- `sdk/deepxiv_sdk/agent/tools.py:get_tools_definition()` — returns OpenAI function-calling tool list; `fetch_cited_paper_sections` is at a known index
- `sdk/deepxiv_sdk/reader.py:Reader.references/cited_by` — backend calls used by the tools
- `benchmark/sample.json` — 150-paper stratified sample; Phase 8 question seed pool

### Backend endpoints used
- `GET /arxiv/{id}/references` — in-corpus + external refs with `in_corpus` flag
- `GET /arxiv/{id}/cited_by` — reverse index
- `GET /arxiv/{id}/sections` — full sections for cited-paper reading
- `GET /arxiv/search?q=&limit=` — agent search tool

### Requirements
- `.planning/REQUIREMENTS.md` §Agent Evaluation — EVAL-01 through EVAL-04

### Patterns to reuse from Phase 7
- `benchmark/analyze_results.py` structure — per-condition aggregation + markdown table rendering
- `benchmark/notebook/analysis.ipynb` pattern — 4+ matplotlib cells, 10 code cells total
- `tests/test_benchmark.py` — MockRedis-style fixtures for offline testing

### SDK test patterns to reuse
- `sdk/tests/test_agent.py` — existing 12 unit tests that mock `Reader` and verify tool behaviour
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `Agent` class (`sdk/deepxiv_sdk/agent/agent.py`) accepts all the params we need; no fork required.
- `ToolExecutor.get_tools_definition()` is the only surface we need to manipulate for the baseline condition — no tool-method removal needed.
- `Reader` class caches HTTP calls via `httpx` — repeated identical calls are fast, so running baseline + citation-aware back-to-back is efficient.
- `tiktoken.get_encoding("o200k_base")` used by the Agent for token counting — reuse for cost accounting in `run_eval.py`.
- `tests/conftest.py` patterns for MockRedis / dependency_overrides can inspire the mock-OpenAI fixture.

### Established Patterns
- JSONL output for per-row results (mirrors `benchmark/results/benchmark.csv` row-oriented design, but JSONL allows nested tool_calls)
- `questions.json` version-controlled, schema-versioned
- FINDINGS.md rendered by a dedicated analyzer script (same pattern as 07-03)
- 4+ matplotlib cells per analysis notebook (same pattern as 07-03)

### Integration Points
- `Reader(base_url="http://localhost:8000")` — requires `docker compose up api` + at least 10 papers in DB (same as Phase 6 integration tests)
- OpenAI client — requires `OPENAI_API_KEY` env var; tests mock the client
- The 150-paper benchmark sample ties Phase 8 to Phase 7; `build_questions.py` reads `benchmark/sample.json`
</code_context>

## Success Metrics

The phase ships when:
- `eval/questions.json` has ≥30 curated, schema-valid questions with `gold_cited_arxiv_ids` all resolving to in-corpus papers
- `eval/run_eval.py --resume` completes both conditions for all questions with <5% `hit_limit=true` rows
- `eval/score.py` produces a `scores.jsonl` with valid rubric rows for every `runs.jsonl` pair
- `eval/FINDINGS.md` (≥80 lines) documents paired win-rate, per-dimension deltas, cost/latency overhead, and a default `citation_depth` recommendation
- `eval/notebook/eval_analysis.ipynb` has ≥4 matplotlib cells
- `pytest tests/test_eval.py` passes with ≥10 unit tests
- Deterministic grounding check agrees with LLM-judge citation_coverage within ±1 on ≥80% of questions

## Open Questions

1. **Does the citation-aware Agent actually win?** This is the experimental question the phase answers. If the result is a null (no significant delta), FINDINGS still ships with honest reporting (null results are findings-worthy — same pattern as 07-02.5 hierarchy_f1 null).
2. **Should we also test `citation_depth=2`?** Adds a third condition → 90 runs instead of 60. Cost is still <$2. Consider including as a stretch goal, not a required plan.
3. **Human validation sample?** Optional stretch: spot-check 5 random questions manually to sanity-check the LLM judge. Not required for EVAL-04 to pass.
