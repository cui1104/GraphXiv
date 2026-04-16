---
phase: 06-sdk-fork-verification
plan: 01
subsystem: sdk
tags: [sdk, reader, unit-tests, path-params, fork]
dependency_graph:
  requires: []
  provides: [sdk-installable, reader-path-params, reader-unit-tests]
  affects: [06-02, 06-03]
tech_stack:
  added: []
  patterns: [path-param URL construction, pytest mock.patch, pip editable install]
key_files:
  created:
    - sdk/pyproject.toml
    - sdk/deepxiv_sdk/reader.py
    - sdk/deepxiv_sdk/__init__.py
    - sdk/setup.py
    - sdk/tests/__init__.py
    - sdk/tests/conftest.py
    - sdk/tests/test_reader.py
  modified: []
decisions:
  - version=0.2.0.dev0 (PEP 440 compliant; 0.2.0-local rejected by setuptools)
  - raw() and json() are aliases for full() to preserve upstream API surface
  - section() does client-side filter on /sections endpoint (no separate section endpoint in local backend)
  - _make_request signature preserved unchanged; only URLs passed to it are changed
metrics:
  duration: "~5min"
  completed: "2026-04-16"
  tasks: 2
  files: 7
---

# Phase 6 Plan 1: SDK Fork + Reader Rewrite Summary

Fork upstream deepxiv_sdk into sdk/, rewrite Reader URL construction from query-param to path-param style matching the local backend routes, stub unmapped methods as NotImplementedError, and establish unit test infrastructure with 39 tests passing via mock.patch.

## What Was Built

**Task 1: Fork and Reader rewrite**

Cloned `https://github.com/DeepXiv/deepxiv_sdk` into `sdk/`, then rewrote the two key files:

- `sdk/pyproject.toml`: Converted from legacy build-system-only format to full `[project]` table (PEP 517/518). Version set to `0.2.0.dev0` (PEP 440 compliant — the originally planned `0.2.0-local` was rejected by setuptools). Added `[tool.setuptools.packages.find]` with `where=["."]` and `include=["deepxiv_sdk*"]`. Added pytest `markers` config with `integration` marker.

- `sdk/deepxiv_sdk/reader.py`: Complete rewrite of all URL construction from query-param to path-param style:
  - `DEFAULT_BASE_URL = "http://localhost:8000"`
  - `head(arxiv_id)` → `f"{self.base_url}/arxiv/{arxiv_id}/head"`
  - `brief(arxiv_id)` → `f"{self.base_url}/arxiv/{arxiv_id}/brief"`
  - `sections(arxiv_id)` → `f"{self.base_url}/arxiv/{arxiv_id}/sections"` (new convenience method)
  - `section(arxiv_id, name)` → calls `sections()` then filters client-side (no separate section endpoint in local backend)
  - `full(arxiv_id)` → `f"{self.base_url}/arxiv/{arxiv_id}/full"` (new method)
  - `raw()` / `json()` → aliases for `full()` (preserves upstream API surface)
  - `references(arxiv_id)` → `f"{self.base_url}/arxiv/{arxiv_id}/references"` (new)
  - `cited_by(arxiv_id)` → `f"{self.base_url}/arxiv/{arxiv_id}/cited_by"` (new)
  - `related(arxiv_id)` → `f"{self.base_url}/arxiv/{arxiv_id}/related"` (new)
  - `search(query, size, search_mode)` → `f"{self.base_url}/arxiv/search"` with `{"q": query, "limit": size, "search_mode": mode}`
  - `pmc_head(pmc_id)` → `f"{self.base_url}/pmc/{pmc_id}/head"`
  - `pmc_full(pmc_id)` → `f"{self.base_url}/pmc/{pmc_id}/full"`
  - Stubs: `websearch`, `semantic_scholar`, `trending`, `biomed_search`, `biomed_data`, `social_impact`, `markdown`, `preview` all raise `NotImplementedError`
  - `_make_request` retry/backoff logic preserved unchanged

**Task 2: Test infrastructure**

- `sdk/tests/__init__.py`: Empty module marker
- `sdk/tests/conftest.py`: 7 fixtures with field names matching `app/api/schemas.py` exactly (e.g., `authors: list[str]`, `token_count: int`, `tldr: str`, `paper_id: UUID string`)
- `sdk/tests/test_reader.py`: 39 unit tests covering all acceptance criteria

## Test Results

```
39 passed in 0.21s
```

All tests use `unittest.mock.patch` on `Reader._make_request`. No live backend. No `from app` imports.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] PEP 440 version string**
- **Found during:** Task 1 installation
- **Issue:** `version = "0.2.0-local"` rejected by setuptools with `configuration error: project.version must be pep440`
- **Fix:** Changed to `version = "0.2.0.dev0"` which is PEP 440 compliant and communicates the same intent
- **Files modified:** `sdk/pyproject.toml`
- **Commit:** 4ec1f38

## Known Stubs

None — all methods are either fully implemented or intentionally raise `NotImplementedError` (the stubs are the intended behavior, not placeholder data).

## Self-Check: PASSED

All created files confirmed present:
- sdk/pyproject.toml: FOUND
- sdk/deepxiv_sdk/reader.py: FOUND
- sdk/deepxiv_sdk/__init__.py: FOUND
- sdk/tests/__init__.py: FOUND
- sdk/tests/conftest.py: FOUND
- sdk/tests/test_reader.py: FOUND

Commits confirmed:
- 4ec1f38: feat(06-01): fork deepxiv_sdk, rewrite Reader URL construction
- f919a59: test(06-01): add test infrastructure and unit tests for Reader
