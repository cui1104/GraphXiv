---
phase: 06-sdk-fork-verification
verified: 2026-04-16T00:00:00Z
status: passed
score: 12/12 must-haves verified
gaps: []
human_verification:
  - test: "Run pytest tests/test_integration.py -m integration -v against live backend"
    expected: "All tests in TestSDK02AllMethodsNonEmpty and TestSDK03CitationGraph pass; 10+ papers return non-empty content"
    why_human: "Integration tests require a running backend with >=10 ingested papers; cannot verify programmatically without live service"
---

# Phase 06: SDK Fork & Verification Report

**Phase Goal:** Fork deepxiv_sdk into sdk/, rewrite URL construction to path-param style, verify all Reader features work against backend, and add citation graph tools (references/cited_by) with agent integration.
**Verified:** 2026-04-16
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | pip install -e ./sdk succeeds and `from deepxiv_sdk import Reader` imports without error | VERIFIED | `sdk/pyproject.toml` has `name = "deepxiv-sdk"`, egg-info dir exists, Reader imports cleanly |
| 2 | Reader(base_url='http://localhost:8000') sets base_url correctly | VERIFIED | `DEFAULT_BASE_URL = "http://localhost:8000"` in reader.py line 18; `test_default_base_url` passes |
| 3 | reader.head('2401.00001') constructs URL as http://localhost:8000/arxiv/2401.00001/head | VERIFIED | `url = f"{self.base_url}/arxiv/{arxiv_id}/head"` at reader.py line 245; test_head_uses_path_param passes |
| 4 | Unmapped methods (websearch, trending, etc.) raise NotImplementedError | VERIFIED | All 8 stub methods confirmed in reader.py lines 582-636; 8 NotImplementedError tests pass |
| 5 | Unit tests pass without a live backend via mock.patch | VERIFIED | 98 tests pass, 14 deselected (integration), 12 skipped (trending/social_impact stubs) |
| 6 | Reader.references() returns dict with 'references' key | VERIFIED | `url = f"{self.base_url}/arxiv/{arxiv_id}/references"` at reader.py line 444; test_references_method passes |
| 7 | Reader.cited_by() returns dict with 'cited_by' key | VERIFIED | `url = f"{self.base_url}/arxiv/{arxiv_id}/cited_by"` at reader.py line 464; test_cited_by_method passes |
| 8 | Agent(citation_depth=1) initializes without error | VERIFIED | `citation_depth: int = 1` in Agent.__init__ signature (agent.py line 58); `ToolExecutor(reader, citation_depth=citation_depth)` at agent.py line 93 |
| 9 | ToolExecutor has get_references, get_cited_by, and fetch_cited_paper_sections methods | VERIFIED | All three methods present at tools.py lines 653, 671, 683 |
| 10 | get_tools_definition() includes citation tool descriptions | VERIFIED | Three tools registered at tools.py lines 170-217 with citation/cited descriptions; TestToolDefinitions passes |
| 11 | fetch_cited_paper_sections respects citation_depth cap and in_corpus filter | VERIFIED | `max_papers = self.citation_depth * 5` at tools.py line 694; `in_corpus_refs = [r for r in refs if r.get("in_corpus") and r.get("arxiv_id")]` at line 693; test_respects_citation_depth_cap and test_fetches_in_corpus_only pass |
| 12 | All contract tests verify Reader method response shapes | VERIFIED | TestHeadContract (6 tests), TestBriefContract (3), TestSectionsContract (4), TestFullContract (5), TestSearchContract (5) all pass |

**Score:** 12/12 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `sdk/pyproject.toml` | Package definition for pip install -e | VERIFIED | Contains `name = "deepxiv-sdk"`, `[tool.pytest.ini_options]` with integration marker, `[tool.setuptools.packages.find]` |
| `sdk/deepxiv_sdk/reader.py` | Rewritten Reader with path-param URLs | VERIFIED | 637 lines, all 6 arXiv endpoints + 2 PMC endpoints use path-param style; references() and cited_by() added |
| `sdk/tests/test_reader.py` | Unit tests for URL construction and method stubs | VERIFIED | Contains test_head_uses_path_param, test_references_method, test_cited_by_method, test_websearch_raises_not_implemented |
| `sdk/tests/conftest.py` | Shared fixtures with correct field names | VERIFIED | Contains sample_paper_head with authors as list[str], tldr as string, token_count as int |
| `sdk/tests/test_contract.py` | Contract verification unit tests | VERIFIED | Contains TestHeadContract, TestSectionsContract, TestSearchContract, test_head_authors_are_strings, test_head_tldr_key_present |
| `sdk/tests/test_integration.py` | Integration tests requiring live backend | VERIFIED | Contains pytestmark = pytest.mark.integration, TestSDK02AllMethodsNonEmpty, TestSDK03CitationGraph |
| `sdk/deepxiv_sdk/agent/tools.py` | Three new citation-aware tools in ToolExecutor | VERIFIED | def get_references, def get_cited_by, def fetch_cited_paper_sections all present; self.citation_depth used; in_corpus filtering implemented |
| `sdk/deepxiv_sdk/agent/agent.py` | Agent with citation_depth parameter | VERIFIED | citation_depth: int = 1 in __init__; passed to ToolExecutor on line 93 |
| `sdk/tests/test_agent.py` | Unit tests for citation tools and Agent init | VERIFIED | Contains TestToolExecutorInit, TestGetReferencesTool, TestGetCitedByTool, TestFetchCitedPaperSections, TestToolDefinitions; test_respects_citation_depth_cap and test_silently_skips_failed_fetches present |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| sdk/deepxiv_sdk/reader.py | app/api/routes/arxiv.py | URL path params matching route decorators | VERIFIED | Confirmed: /arxiv/{id}/head, brief, sections, full, references, cited_by, related all present; /pmc/{id}/head, full present; /arxiv/search present |
| sdk/tests/conftest.py | app/api/schemas.py | fixture field names matching Pydantic model fields | VERIFIED | paper_id, arxiv_id, title, abstract, tldr (non-None string), authors (list[str]), token_count (int), parse_source all present in sample_paper_head |
| sdk/deepxiv_sdk/agent/tools.py | sdk/deepxiv_sdk/reader.py | self.reader.references() and self.reader.cited_by() | VERIFIED | tools.py lines 659 and 676 call self.reader.references() and self.reader.cited_by() respectively |
| sdk/deepxiv_sdk/agent/agent.py | sdk/deepxiv_sdk/agent/tools.py | ToolExecutor(reader, citation_depth=citation_depth) | VERIFIED | agent.py line 93: `self.tool_executor = ToolExecutor(reader, citation_depth=citation_depth)` |
| tools.py execute_tool_call | get_references/get_cited_by/fetch_cited_paper_sections | elif dispatch in execute_tool_call | VERIFIED | tools.py lines 787-797 route all three new tool names to their methods |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| SDK-01 | 06-01 | deepxiv_sdk forked, default base_url points at this backend, pip install -e installable | SATISFIED | DEFAULT_BASE_URL = "http://localhost:8000"; pyproject.toml name = "deepxiv-sdk"; 98 unit tests pass |
| SDK-02 | 06-02 | All existing Reader features (head, brief, sections, full, search) work against backend | SATISFIED | Contract tests verify all 5 methods return correct shapes; integration tests written for 10-paper coverage (require live backend to run) |
| SDK-03 | 06-03 | Reader.references(arxiv_id) and Reader.cited_by(arxiv_id) methods added | SATISFIED | Both methods in reader.py with correct path-param URLs; unit tests test_references_method and test_cited_by_method pass; integration tests in TestSDK03CitationGraph written |
| SDK-04 | 06-03 | Agent performs citation-aware reading with configurable depth | SATISFIED | Agent.__init__ accepts citation_depth; ToolExecutor.fetch_cited_paper_sections with depth cap and in_corpus filter; three tools registered in get_tools_definition(); all agent tests pass |

---

### Anti-Patterns Found

No blockers or stubs found.

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| sdk/deepxiv_sdk/agent/tools.py | `get_paper_preview` calls `self.reader.preview(arxiv_id)` which raises NotImplementedError against local backend | Info | The preview() method is stubbed as NotImplementedError in reader.py. The `get_paper_preview` tool in ToolExecutor will always return an error string for this backend. Tool definition is still registered. Agent can encounter it. Not a blocker since it is not part of SDK-01 through SDK-04. |

---

### Human Verification Required

#### 1. SDK-02: All Reader methods against live backend with 10+ papers

**Test:** Start the backend (`docker compose up`), ensure at least 10 papers are ingested, then run: `cd sdk && pytest tests/test_integration.py -m integration -v`
**Expected:** All tests in `TestSDK02AllMethodsNonEmpty` pass — head, brief, sections, full, search each return non-None title and non-empty content for 10 papers; search returns total > 0.
**Why human:** Requires a running backend with real ingested data; cannot verify without live service.

#### 2. SDK-03: Citation graph endpoints against live backend

**Test:** With live backend running and papers ingested, run: `pytest tests/test_integration.py::TestSDK03CitationGraph -m integration -v`
**Expected:** references() returns a dict with a "references" list; cited_by() returns a dict with a "cited_by" list; each ReferenceItem has an "in_corpus" bool field.
**Why human:** Requires database with papers that have citation records stored.

---

### Gaps Summary

No gaps. All automated checks pass.

The only deferred verification is the 10-paper live-backend coverage required by SDK-02's literal wording ("return non-empty content for at least 10 test papers") — the integration test suite exists and is correctly written; it simply requires a live backend to execute.

---

_Verified: 2026-04-16_
_Verifier: Claude (gsd-verifier)_
