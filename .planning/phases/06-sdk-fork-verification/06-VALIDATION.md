---
phase: 6
slug: sdk-fork-verification
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-16
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | `sdk/pyproject.toml` (pytest.ini_options created in Plan 01 Task 1) |
| **Quick run command** | `cd sdk && pytest tests/ -m "not integration" -x -q` |
| **Full suite command** | `cd sdk && pytest tests/ -m "not integration" -v` |
| **Integration command** | `cd sdk && pytest tests/ -m integration -v` (requires live backend) |
| **Estimated runtime** | ~15 seconds (unit), ~60 seconds (integration) |

---

## Sampling Rate

- **After every task commit:** Run `cd sdk && pytest tests/ -m "not integration" -x -q`
- **After every plan wave:** Run `cd sdk && pytest tests/ -m "not integration" -v`
- **Before `/gsd:verify-work`:** Full unit suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Created By | Status |
|---------|------|------|-------------|-----------|-------------------|-----------------|--------|
| 06-01-01 | 01 | 1 | SDK-01 | install + smoke | `pip install -e ./sdk && python -c "from deepxiv_sdk import Reader; r = Reader(); assert r.base_url == 'http://localhost:8000'"` | Plan 01 Task 1 | pending |
| 06-01-02 | 01 | 1 | SDK-01 | unit | `cd sdk && pytest tests/test_reader.py -x -v` | Plan 01 Task 2 | pending |
| 06-02-01 | 02 | 2 | SDK-02 | unit (contract) | `cd sdk && pytest tests/test_contract.py -x -v` | Plan 02 Task 1 | pending |
| 06-02-02 | 02 | 2 | SDK-02 | integration | `cd sdk && pytest tests/test_integration.py -m integration -v` | Plan 02 Task 2 | pending |
| 06-03-01 | 03 | 3 | SDK-03, SDK-04 | unit (agent) | `cd sdk && pytest tests/test_agent.py -x -v` | Plan 03 Task 2 | pending |
| 06-03-02 | 03 | 3 | SDK-03 | integration | `cd sdk && pytest tests/test_integration.py::TestSDK03CitationGraph -m integration -v` | Plan 03 Task 2 | pending |

*Status: pending / green / red / flaky*

---

## Wave 0 Requirements

All test files are created within their respective plan tasks (no separate Wave 0 needed):

- [x] `sdk/tests/__init__.py` — created by Plan 01 Task 2
- [x] `sdk/tests/conftest.py` — shared fixtures, created by Plan 01 Task 2
- [x] `sdk/tests/test_reader.py` — URL construction + NotImplementedError tests, created by Plan 01 Task 2
- [x] `sdk/tests/test_contract.py` — contract verification unit tests, created by Plan 02 Task 1
- [x] `sdk/tests/test_integration.py` — integration tests (SDK-02 + SDK-03), created by Plan 02 Task 2, extended by Plan 03 Task 2
- [x] `sdk/tests/test_agent.py` — citation tool unit tests, created by Plan 03 Task 2
- [x] `pytest` configured in `sdk/pyproject.toml` by Plan 01 Task 1

---

## Test-to-Requirement Mapping

| Requirement | Test File | Key Tests |
|-------------|-----------|-----------|
| SDK-01 | `test_reader.py` | `test_default_base_url`, `test_head_uses_path_param`, `test_search_uses_correct_url`, `test_websearch_raises_not_implemented` |
| SDK-02 | `test_contract.py` | `TestHeadContract`, `TestSectionsContract`, `TestSearchContract`, `TestFullContract` |
| SDK-02 | `test_integration.py` | `TestSDK02AllMethodsNonEmpty::test_head_for_10_papers`, `test_brief_for_10_papers`, `test_sections_for_10_papers`, `test_full_for_10_papers` |
| SDK-03 | `test_reader.py` | `test_references_method`, `test_cited_by_method` |
| SDK-03 | `test_agent.py` | `TestGetReferencesTool`, `TestGetCitedByTool` |
| SDK-03 | `test_integration.py` | `TestSDK03CitationGraph::test_references_returns_list`, `test_cited_by_returns_list`, `test_reference_items_have_in_corpus_flag` |
| SDK-04 | `test_agent.py` | `TestToolExecutorInit::test_custom_citation_depth`, `TestFetchCitedPaperSections`, `TestToolDefinitions::test_citation_tools_in_definitions` |

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `pip install -e ./sdk` succeeds on clean env | SDK-01 | Requires fresh venv; automated test assumes installed | Create a new venv, run `pip install -e ./sdk`, check exit code 0 |
| 10 real arXiv papers return non-empty content | SDK-02 | Requires live backend running at localhost:8000 | Start backend, run `cd sdk && pytest tests/test_integration.py -m integration -v` |
| Citation graph endpoints return data | SDK-03 | Requires live backend with citation data | Start backend, run `cd sdk && pytest tests/test_integration.py::TestSDK03CitationGraph -m integration -v` |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify commands
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all test file references (all created within plan tasks)
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
