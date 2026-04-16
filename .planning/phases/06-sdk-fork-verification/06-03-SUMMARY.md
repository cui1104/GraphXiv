---
phase: 06-sdk-fork-verification
plan: 03
subsystem: sdk-agent
tags: [citation-graph, agent-tools, react-agent, deepxiv_sdk, tool-executor, pytest]

# Dependency graph
requires:
  - phase: 06-01
    provides: "SDK fork with Reader.references() and Reader.cited_by() methods"
  - phase: 06-02
    provides: "Full test suite for SDK fork (unit + contract + integration)"
provides:
  - "ToolExecutor with three citation-aware tools: get_references, get_cited_by, fetch_cited_paper_sections"
  - "Agent with citation_depth parameter"
  - "Unit tests covering all citation tool methods"
  - "SDK-03 integration tests for references/cited_by endpoints"
affects:
  - sdk/deepxiv_sdk/agent/tools.py
  - sdk/deepxiv_sdk/agent/agent.py
  - sdk/tests/test_agent.py
  - sdk/tests/test_integration.py

# Tech stack
added: []
patterns:
  - "ToolExecutor instance method get_tools_definition() delegates to module-level function"
  - "citation_depth * 5 cap per hop for fetch_cited_paper_sections"
  - "Silent exception swallowing in fetch_cited_paper_sections for network failures"
  - "in_corpus=True filter ensures only locally available papers are fetched"

# Key files
created:
  - sdk/tests/test_agent.py
modified:
  - sdk/deepxiv_sdk/agent/tools.py
  - sdk/deepxiv_sdk/agent/agent.py
  - sdk/tests/test_integration.py

# Key decisions
decisions:
  - "Added get_tools_definition() as instance method on ToolExecutor (wraps module-level function) — plan verify script expected te.get_tools_definition() but codebase uses standalone function; instance method satisfies both the test API and the ReAct graph which calls the standalone"
  - "Force-added test_agent.py via git add -f — upstream SDK .gitignore explicitly excludes test_agent.py; this is a project test that must be tracked"
  - "tool_names extraction in TestToolDefinitions uses ['function']['name'] path — actual format is OpenAI function-calling style with {type: function, function: {name: ...}}"

# Metrics
duration: 5min
completed: 2026-04-16
tasks_completed: 2
files_modified: 4
---

# Phase 06 Plan 03: Citation-Aware Agent Tools Summary

**One-liner:** Three citation-graph tools added to ToolExecutor (get_references, get_cited_by, fetch_cited_paper_sections) with citation_depth cap, plus Agent citation_depth parameter and full unit test coverage.

## What Was Built

### Task 1: Citation-aware Agent tools in ToolExecutor
- Added `citation_depth: int = 1` parameter to `ToolExecutor.__init__`
- Added `get_tools_definition()` instance method on `ToolExecutor` that wraps the module-level function (enabling `te.get_tools_definition()` as required by tests)
- Added three new tool methods to `ToolExecutor`:
  - `get_references(arxiv_id)`: calls `reader.references()`, separates in-corpus vs external, returns formatted string with counts
  - `get_cited_by(arxiv_id)`: calls `reader.cited_by()`, lists all citing papers in corpus
  - `fetch_cited_paper_sections(arxiv_id)`: fetches sections for in-corpus cited papers only, capped at `citation_depth * 5` papers; silently skips failed fetches
- Added all three tools to module-level `get_tools_definition()` in OpenAI function-calling format with citation-aware descriptions
- Added routing for all three tools in `execute_tool_call()`
- Added `citation_depth: int = 1` parameter to `Agent.__init__` and passed to `ToolExecutor`

### Task 2: Unit tests and integration test updates
- Created `sdk/tests/test_agent.py` with 12 unit tests (all mocked, no live backend):
  - `TestToolExecutorInit`: default (1) and custom citation_depth
  - `TestGetReferencesTool`: string return, in-corpus paper display, reader call verification
  - `TestGetCitedByTool`: string return, citing paper display
  - `TestFetchCitedPaperSections`: in-corpus-only fetching, citation_depth cap (2 in-corpus = 2 sections calls), empty refs graceful return, silent exception handling
  - `TestToolDefinitions`: all 3 tools present in get_tools_definition() output
- Appended `TestSDK03CitationGraph` to `test_integration.py`:
  - `test_references_returns_list`: references key is list, paper_id present
  - `test_cited_by_returns_list`: cited_by key is list, paper_id present
  - `test_reference_items_have_in_corpus_flag`: each ReferenceItem has bool in_corpus field

## Verification Results

```
98 passed, 12 skipped, 14 deselected in 0.32s
```
- 12 new agent tests all pass
- 98 total non-integration tests pass
- 12 trending tests skip (upstream-only, expected)
- 14 integration tests deselected (require live backend, expected)

## Commits

| Task | Commit | Files |
|------|--------|-------|
| 1 - Citation tools in ToolExecutor and Agent | 4c5c25a | sdk/deepxiv_sdk/agent/tools.py, sdk/deepxiv_sdk/agent/agent.py |
| 2 - Unit tests and integration tests | be7326f | sdk/tests/test_agent.py, sdk/tests/test_integration.py |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] get_tools_definition() is module-level, not a ToolExecutor method**
- **Found during:** Task 1 verification
- **Issue:** Plan's verify script called `te.get_tools_definition()` but `get_tools_definition()` is a standalone module-level function in the actual codebase
- **Fix:** Added `get_tools_definition()` as an instance method on `ToolExecutor` that delegates to the module-level function; both the test API and the ReAct graph (which imports the standalone function) continue to work correctly
- **Files modified:** sdk/deepxiv_sdk/agent/tools.py

**2. [Rule 3 - Blocking] test_agent.py excluded by upstream .gitignore**
- **Found during:** Task 2 git commit
- **Issue:** sdk/.gitignore explicitly lists `test_agent.py` as excluded (upstream SDK excludes its own scratch tests); `git add` rejected the file
- **Fix:** Used `git add -f` to force-track the file since it's a project test that must be version-controlled
- **Files modified:** (git tracking change, no code modification)

**3. [Rule 1 - Adaptation] TestToolDefinitions test format**
- **Found during:** Task 2 test writing
- **Issue:** Plan's example used `t["name"]` but actual tools dict format is `{"type": "function", "function": {"name": ...}}` (OpenAI function-calling style)
- **Fix:** Test uses `t["function"]["name"]` path with fallback, matching the actual data structure
- **Files modified:** sdk/tests/test_agent.py

## Known Stubs

None — all three tools are fully wired to `reader.references()`, `reader.cited_by()`, and `reader.sections()` respectively.

## Self-Check: PASSED
