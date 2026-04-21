# Phase 8 Evaluation Rubric

**Version:** 1
**Source of truth:** CONTEXT.md D-17, D-19
**Consumed by:** `eval/score.py` (judge prompt in plan 08-03) and `eval/analyze.py`
  (dimension-by-dimension paired comparison in plan 08-03).
**Audience:** An LLM judge (`gpt-4o-mini`) scoring two candidate answers
  side-by-side for each question in `eval/questions.json`.

Every scored answer receives four integer 1–5 scores. The judge prompt in
plan 08-03 will cite this file verbatim, so scoring anchors must be stable.

---

## Dimensions

### 1. `answer_correctness` (1–5)

Does the answer factually match the question's intent? A correct answer resolves
the asked-about claim, relation, or comparison without introducing falsehoods.

**Anchors:**

- **1** — Answer contradicts the known ground truth or is non-responsive.
- **2** — Answer is partially on-topic but contains at least one factual error
  that a careful reader of the cited papers would catch.
- **3** — Answer is on-topic and mostly correct, but omits or misstates a
  non-trivial sub-claim.
- **4** — Answer is factually correct but lacks precision (e.g., names a
  method family when the question asks for the specific variant).
- **5** — Answer is precise, complete, and factually consistent with the
  cited-paper evidence.

### 2. `faithfulness` (1–5)

Are the claims supported by evidence the agent actually retrieved, as recorded
in the run's `tool_calls`? This dimension penalises hallucinations and rewards
grounding in fetched section content.

**Anchors:**

- **1** — Answer introduces claims that cannot be traced to any `tool_calls`
  result (pure hallucination).
- **2** — Majority of key claims lack a supporting tool call; some claims are
  copy-paste from parametric memory.
- **3** — Most claims are plausibly supported by retrieved content but at least
  one is not.
- **4** — Every substantive claim has a corresponding `tool_calls` result, but
  the linkage is implicit rather than quoted.
- **5** — Every substantive claim is directly supported by specific text that
  appears in the `tool_calls` results (`read_section`, `get_full_paper`,
  `fetch_cited_paper_sections`, etc.).

### 3. `citation_coverage` (1–5)

How many of the question's `gold_cited_arxiv_ids` did the agent actually invoke
a tool against? This dimension is computed *both* by the judge *and* by a
deterministic counter (per D-19) to cross-validate the judge.

**Anchors (fraction = `|called ∩ gold| / |gold|`):**

- **1** — Zero gold cited papers touched by any tool call.
- **2** — 0 < fraction ≤ 0.25 (one of four gold papers touched).
- **3** — 0.25 < fraction ≤ 0.5.
- **4** — 0.5 < fraction ≤ 0.75.
- **5** — fraction > 0.75 (almost every gold paper was loaded or had its
  sections fetched).

### 4. `completeness` (1–5)

Does the answer address every sub-part of the question, including any
comparative, enumerative, or claim-grounding facets?

**Anchors:**

- **1** — Only a single aspect of a multi-part question is addressed.
- **2** — Half of the sub-parts are addressed; others are ignored or hand-waved.
- **3** — Most sub-parts are addressed; one is clearly missing.
- **4** — All sub-parts are addressed but coverage of at least one is shallow.
- **5** — Every sub-part is addressed at publication-style depth with
  contextual nuance.

---

## Deterministic grounding cross-check (D-19)

Per CONTEXT.md D-19, the judge's `citation_coverage` score is cross-validated
by a deterministic function that counts how many `gold_cited_arxiv_ids`
appear as `arxiv_id` arguments in the run's `tool_calls`. Both numbers are
recorded in `scores.jsonl` and `FINDINGS.md` flags disagreement > 1 bucket.

The deterministic counter is the fallback source of truth when the judge and
counter disagree by more than one bucket on more than 20% of questions, per
Pitfall 8 in 08-RESEARCH.md: schema-valid judge output is not automatically
correct.

---

## Pitfalls the judge must avoid

- **Position bias.** Answers are presented as "A" and "B" in randomised order
  per question (08-03 runner). The judge must not anchor on position.
- **Style over substance.** Ignore prose style; score only the four dimensions.
- **Leakage via full answers.** The judge sees `gold_answer_keywords` and
  `gold_cited_arxiv_ids` (titles only, via Reader.head()), *not* reference
  answers. The judge must not assume the keyword list is exhaustive.
- **Tool-call volume ≠ quality.** A run with 20 tool calls is not automatically
  more grounded than one with 3. Faithfulness is about whether claims trace to
  retrieved content, not how much was retrieved.
- **Schema-valid does not mean correct.** The `response_format=json_schema`
  guarantee only enforces shape. Semantic correctness of the verdict is an
  independent concern and is cross-validated by the deterministic counter
  where possible (D-19).
