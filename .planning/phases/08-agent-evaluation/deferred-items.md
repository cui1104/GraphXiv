# 08-agent-evaluation — Deferred Items

Pre-existing issues observed during Wave 2 execution that are out of scope per
the gsd-executor scope boundary (only auto-fix issues directly caused by the
current task's changes).

## 1. `tests/test_eval.py::test_promote_moves_candidate` pre-existing failure

- **Discovered during:** 08-03 Wave 2 test run (2026-04-21).
- **Symptom:** `ValueError: gold cite 1706.03762 no longer resolvable in corpus (D-20 violated)`
  raised from `eval/build_questions.py:170`.
- **Root cause (untouched):** The test sets up a synthetic candidate with
  `gold_cited_arxiv_ids: ["1706.03762"]` and calls `promote_candidate(...)`,
  which now validates gold IDs against the real corpus DB. The ID
  `1706.03762` (arXiv: *Attention Is All You Need*) is apparently no longer in
  the local corpus snapshot, so the check fails.
- **Pre-existing:** Verified by stashing all Wave 2 edits and re-running the
  test: the failure reproduces on commit `4752d1c` alone.
- **Fix direction (future):** either (a) use a real in-corpus arxiv_id as the
  test fixture's gold ID, or (b) inject a mock `reader.head()` that short-circuits
  the corpus check in `promote_candidate`. Out of scope for 08-03; was broken
  before Wave 2 started.
