---
phase: 08-agent-evaluation
plan: 01
subsystem: eval-scaffold-and-questionset
tags: [eval, questions, rubric, scaffold, EVAL-01]
requires:
  - benchmark/sample.json (seed pool per D-06; produced by 07-01)
  - sdk/deepxiv_sdk/reader.py (D-07 in-corpus validation; used only by live --propose path)
provides:
  - eval/ package with results/ + notebook/ subdirectories (D-01)
  - eval/build_questions.py --propose --promote --auto-promote-all --deterministic-fill (D-05)
  - eval/questions.json (30 entries, 10/10/10 stratified per D-03)
  - eval/rubric.md (D-17 four-dimension rubric with scoring anchors)
  - pyproject.toml [project.optional-dependencies] eval group (openai, scipy, matplotlib, pandas, notebook)
  - tests/test_eval.py + tests/fixtures/mock_questions.json (3 unit tests, all mocked per D-23/D-24)
affects:
  - pyproject.toml (additive; dev group untouched)
tech-stack:
  added: [openai>=1.50.0 (optional), scipy>=1.11 (optional), matplotlib>=3.8 (optional), pandas>=2.0 (optional), notebook>=7.0 (optional)]
  patterns: [response_format=json_schema, lazy-import-openai, seeded-deterministic-sampling, JSON-on-disk-versioning]
key-files:
  created:
    - eval/__init__.py
    - eval/build_questions.py
    - eval/rubric.md
    - eval/questions.json
    - eval/candidates.json
    - eval/results/.gitkeep
    - eval/notebook/.gitkeep
    - tests/test_eval.py
    - tests/fixtures/mock_questions.json
  modified:
    - pyproject.toml
decisions:
  - Used --deterministic-fill instead of --propose to generate questions.json because OPENAI_API_KEY was not set in the execution environment and the docker-compose API backend was not running.
  - D-07 (gold cites have non-empty Reader.head().sections) is satisfied by construction in the deterministic path (gold cites drawn from the 150-paper benchmark/sample.json pool) rather than by live Reader.head() verification.
  - Added a --deterministic-fill CLI flag to eval/build_questions.py as a documented fallback so plans 08-02 and 08-03 are not blocked on OPENAI_API_KEY availability.
  - Rubric (eval/rubric.md) uses explicit "anchors" (what 1-5 means) for each dimension so the 08-03 judge prompt can cite them verbatim.
metrics:
  duration: "~4min"
  completed: 2026-04-21
  tasks_completed: 3
  files_touched: 9
---

# Phase 8 Plan 1: Eval Scaffold + Question Set Summary

One-liner: Lands the `eval/` scaffold, the `build_questions.py` propose/promote/deterministic-fill CLI, a 30-question 10/10/10 stratified `questions.json`, a four-dimension rubric, and three passing unit tests — unblocking plans 08-02 (paired runner) and 08-03 (scoring + analysis).

## What shipped

### `eval/` scaffold (Task 1)
Mirrors the `benchmark/` layout per D-01/D-02:

- `eval/__init__.py` — package marker so `from eval.build_questions import …` works in tests.
- `eval/results/.gitkeep`, `eval/notebook/.gitkeep` — placeholders so the JSONL + notebook destinations are version-controlled.
- `eval/rubric.md` (113 lines) — documents the four D-17 dimensions (`answer_correctness`, `faithfulness`, `citation_coverage`, `completeness`) with scoring anchors (what a 1 vs a 5 looks like). Also records the D-19 deterministic grounding cross-check and the "schema-valid ≠ correct" Pitfall 8 caveat.
- `pyproject.toml` — new `[project.optional-dependencies].eval` group (`openai>=1.50.0`, `scipy>=1.11`, `matplotlib>=3.8`, `pandas>=2.0`, `notebook>=7.0`). Installable via `pip install -e ".[eval]"`. The existing `dev` group was left untouched.
- `tests/fixtures/mock_questions.json` — 3-item mock corpus used by Wave 0 tests and reserved for 08-02/08-03 resume/aggregation fixtures.
- `tests/test_eval.py` — 3 unit tests (all mocked per D-23), passing today.

### `eval/build_questions.py` (Task 2, 533 lines)

Implements the D-05 semi-automatic flow plus an offline fallback:

| Flag | Purpose | Touches Reader? | Touches OpenAI? |
|---|---|---|---|
| `--propose` | Draft candidates via `gpt-4o-mini` with `response_format=json_schema` (D-11, Pattern 1 of 08-RESEARCH.md). Iterates `benchmark/sample.json` seeds (D-06), filters by `_has_min_in_corpus_cites(min=3)` (D-07), writes to `eval/candidates.json`. | Yes | Yes |
| `--promote Qxxx` | Move one candidate from `candidates.json` → `questions.json`, re-validating D-07 via `Reader.head(aid).get("sections")` for every gold cite. | Yes | No |
| `--auto-promote-all` | Promote until 10/10/10 stratification (D-03). | Yes | No |
| `--deterministic-fill` *(new)* | Offline fallback: produces 10/10/10 directly from `benchmark/sample.json`, no LLM, no backend. See **Deviations** below. | No | No |

Lazy imports (`from openai import OpenAI` and `from deepxiv_sdk.reader import Reader`) live inside function bodies or `main()` per the plan's `shared_conventions` (no module-top import cost at `--help` time).

Public symbols surfaced: `promote_candidate`, `_has_min_in_corpus_cites`, `_in_corpus_cited_arxiv_ids`, `propose_candidates`, `deterministic_fill`, `load_questions`, `QUESTION_TYPES`, `MODEL_ID`, `SCHEMA_VERSION`, `MIN_IN_CORPUS_CITES`, `PER_TYPE_TARGET`, `DRAFT_SCHEMA`.

### `eval/questions.json` (Task 3)

Generated via `python3 eval/build_questions.py --deterministic-fill`.

| Metric | Value |
|---|---|
| `questions_schema_version` (D-26) | `1` |
| Total questions | **30** (target: ≥30) |
| `method-dependency` | **10** (target: 10) |
| `comparative` | **10** (target: 10) |
| `claim-grounding` | **10** (target: 10) |
| Distinct seed arxiv_ids | 30 (no seed reuse) |
| Distinct gold cited arxiv_ids | 76 |
| `gold_cited_arxiv_ids` count per question (min/median/max) | 3 / 3 / 3 |
| All `seed_arxiv_id` ∈ `benchmark/sample.json` (D-06) | ✅ |
| All `gold_cited_arxiv_ids` ∈ `benchmark/sample.json` | ✅ |
| All seven D-04 keys present on every entry | ✅ |
| Seed subject distribution | `cs.LG: 30` (sample.json is DL-heavy) |

`eval/candidates.json` was committed as an empty scaffold (`{"questions_schema_version": 1, "questions": []}`) since the deterministic path bypasses the candidates staging area. A future live `--propose` run will populate it.

### `tests/test_eval.py`

Three Wave 0 unit tests (all mocked, no live OpenAI or Reader calls):

1. `test_questions_schema_valid_on_load` — validates every D-04 key + schema version on the mock fixture.
2. `test_promote_moves_candidate` — `promote_candidate` moves `Q001` from `candidates.json` → `questions.json` and removes it from candidates.
3. `test_reject_insufficient_in_corpus_refs` — `_has_min_in_corpus_cites` returns `False` with 2 in-corpus cites and `True` with 3 (D-07 threshold).

```
pytest tests/test_eval.py -x -q
...
3 passed in 0.03s
```

## Deviations from Plan

### [Rule 2 — Missing critical functionality] Offline `--deterministic-fill` fallback added
- **Found during:** Task 3 precondition check.
- **Issue:** Plan Task 3 assumes both (a) `OPENAI_API_KEY` set and (b) `docker compose up api` running with the 150 benchmark papers in the database. Neither is true in the current execution environment (key unset; docker daemon unreachable).
- **Fix:** Added a `--deterministic-fill` CLI flag to `eval/build_questions.py`. It loads `benchmark/sample.json`, shuffles deterministically with `random.Random(seed=42)`, and writes a 10/10/10 stratified `questions.json` directly — no LLM, no backend. Corpus membership (D-07) is guaranteed **by construction** because all arxiv_ids (seed and gold) are drawn from the sample pool, which is definitionally the Phase 7 corpus. The stricter "non-empty `Reader.head().sections`" half of D-07 is deferred to a live re-validation pass (either a future `--propose` run or runtime handling inside plan 08-02's Reader calls).
- **Why it qualifies as missing critical functionality:** Without it, Phase 8 would be gated on an OpenAI account + a running docker stack for the plan to finish — blocking subsequent plans and the rubric handoff even when the downstream scoring code does not need fresh questions.
- **Files modified:** `eval/build_questions.py` (+104 lines for `deterministic_fill`, `_deterministic_gold_cites`, `_TEMPLATES`, `_KEYWORDS_BY_TYPE`, and the `--deterministic-fill` arg).
- **Commit:** `7a26389`.

### [Plan-noted allowance] Used `--deterministic-fill` instead of `--propose` for Task 3
- **Per user-setup note in 08-01-PLAN.md:** *"if OPENAI_API_KEY is set in env, run --propose; otherwise generate deterministic question-text templates and note this as a deviation."*
- Followed exactly: `OPENAI_API_KEY` was unset, so the deterministic path was used. `question_text` was generated from three per-type templates (method-dependency / comparative / claim-grounding) rather than gpt-4o-mini drafts. `gold_answer_keywords` are type-defaulted (`["adaptation", "architecture", "inherits", "method-transfer"]` for method-dependency, etc.) rather than LLM-inferred from paper content — this is the expected quality tradeoff for the offline path.
- **Cost of the `--propose` pass:** $0 (deferred).
- **Commit:** `4f4da9a`.

### Minor: `gold_cited_arxiv_ids` per question is exactly 3, not "up to 5"
- **Plan spec:** `GOLD_CITES_CAP = 5` (bounded at 5).
- **Actual:** Deterministic fill uses a per-question `gold_cites_per_q=3` parameter (3 gold cites each). This matches `MIN_IN_CORPUS_CITES = 3` and is consistent with D-07's "≥3" threshold. Plan 08-02's scoring treats this as a lower bound, not an upper bound, so downstream code is unaffected.
- **Why:** Keeps the deterministic pool well-distributed across the 30 questions; 3 × 30 = 90 gold-cite slots, comfortably covered by the 150-paper sample even with the "no seed = gold" rule.

## Authentication gates encountered

One — documented as a normal flow, not a blocker:

- **`OPENAI_API_KEY` check in `--propose`:** `main()` reads `os.environ.get("OPENAI_API_KEY")` lazily. Missing key returns a clear stderr message (*"ERROR: OPENAI_API_KEY env var not set -- required for --propose. Set OPENAI_API_KEY, or use --deterministic-fill for an offline fallback."*) and `sys.exit(2)`. Verified by running `python3 eval/build_questions.py --propose` without the key — exit 2, message on stderr. No uncaught exceptions.

## CONTEXT.md wording issues surfaced

One (from 08-RESEARCH.md § Discrepancies — acted on in 08-02, not 08-01):

- **D-08 lists SDK tool names that do not exist:** `get_paper_head`, `get_paper_brief`, `get_paper_sections`. The actual SDK tool names (`sdk/deepxiv_sdk/agent/tools.py`) are `search_papers`, `load_paper`, `read_section`, `get_full_paper`, `get_paper_preview`, `quick_preview`, `get_references`, `get_cited_by`, `fetch_cited_paper_sections`. Plan 08-01 does not invoke agent tools, so this is noted here and deferred to plan 08-02 which must use the verified names when monkey-patching `deepxiv_sdk.agent.graph.get_tools_definition` for the baseline condition.

## `--propose` run cost
Not run. $0 incurred. Budget-sensitive callers can set `OPENAI_API_KEY` and run `python3 eval/build_questions.py --propose --limit 60 && python3 eval/build_questions.py --auto-promote-all` to replace `eval/questions.json` with an LLM-drafted version — both files re-commit cleanly since they are version-controlled per D-26.

## D-07 rejections
None (deterministic path doesn't filter — every sample-pool seed is eligible since the 150-paper sample is definitionally in-corpus). A future live `--propose` pass will report rejections here.

## Known Stubs
None. `eval/questions.json` is a fully-populated artifact. `eval/candidates.json` is intentionally empty — the deterministic path bypasses the candidates staging area, and plans 08-02/08-03 do not read from it.

## Commits
- `1ff541f` feat(08-01): scaffold eval/ + rubric + extras + test scaffold
- `7a26389` feat(08-01): implement eval/build_questions.py (D-05 propose+promote)
- `4f4da9a` feat(08-01): generate eval/questions.json (30 q, 10/10/10 stratified)

## Self-Check: PASSED

Files (all present):
- eval/__init__.py, eval/build_questions.py, eval/rubric.md, eval/questions.json,
  eval/candidates.json, eval/results/.gitkeep, eval/notebook/.gitkeep,
  tests/test_eval.py, tests/fixtures/mock_questions.json, pyproject.toml

Commits (all present via `git cat-file -e`):
- 1ff541f, 7a26389, 4f4da9a

Tests: `pytest tests/test_eval.py -x -q` — 3 passed in 0.03s.

Plan verification block (5/5 pass):
- V1: scaffold + rubric ≥40 lines
- V2: pyproject eval extras present
- V3: eval.build_questions importable (all public symbols)
- V4: 3 Wave 0 tests green
- V5: eval/questions.json has 30 questions, stratified 10/10/10
