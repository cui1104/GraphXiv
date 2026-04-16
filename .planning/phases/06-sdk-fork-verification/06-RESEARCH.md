# Phase 6: SDK Fork + Verification - Research

**Researched:** 2026-04-16
**Domain:** Python SDK forking, HTTP client rewriting, pytest mock patterns, ReAct agent extension
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Fork location**
- D-01: Fork lives at `sdk/` subdirectory within this repo — not a separate GitHub repository
- D-02: `pip install -e ./sdk` installs it in development mode; `sdk/pyproject.toml` and `sdk/setup.py` are the package entrypoints
- D-03: The fork is seeded by cloning/copying the upstream `https://github.com/DeepXiv/deepxiv_sdk` into `sdk/`, then applying changes in-place

**URL construction rewrite (required, not optional)**
- D-04: The original SDK sends `GET /arxiv/?arxiv_id=X&type=head` (query params). This backend uses path params: `GET /arxiv/{id}/head`. Every Reader method's URL construction must be rewritten to use path params.
- D-05: New endpoint pattern in Reader:
  - `head(arxiv_id)` → `GET {base_url}/arxiv/{arxiv_id}/head`
  - `brief(arxiv_id)` → `GET {base_url}/arxiv/{arxiv_id}/brief`
  - `section(arxiv_id, section_name)` → `GET {base_url}/arxiv/{arxiv_id}/sections` (fetch all, filter by name client-side)
  - `raw(arxiv_id)` / `json(arxiv_id)` → `GET {base_url}/arxiv/{arxiv_id}/full`
  - `pmc_head(pmc_id)` → `GET {base_url}/pmc/{pmc_id}/head`
  - `pmc_full(pmc_id)` / `pmc_json(pmc_id)` → `GET {base_url}/pmc/{pmc_id}/full`
  - `search(query, ...)` → `GET {base_url}/search?q={query}&limit={size}&search_mode={mode}`
- D-06: Methods that don't map to this backend (`websearch`, `semantic_scholar`, `trending`, `biomed_*`, `social_impact`, `markdown`, `preview`) raise `NotImplementedError` with a clear message — they are not removed (preserves API surface for future phases)
- D-07: Default `base_url` changed from `"https://data.rag.ac.cn"` to `"http://localhost:8000"`

**SDK-03: new Reader methods**
- D-08: `Reader.references(arxiv_id: str) -> Dict[str, Any]` — calls `GET {base_url}/arxiv/{arxiv_id}/references`, returns raw response dict
- D-09: `Reader.cited_by(arxiv_id: str) -> Dict[str, Any]` — calls `GET {base_url}/arxiv/{arxiv_id}/cited_by`, returns raw response dict
- D-10: Return type is `Dict[str, Any]` — consistent with every other Reader method (no custom typed objects introduced)

**SDK-04: citation-aware Agent**
- D-11: No new Agent subclass — extend by adding tools to `ToolExecutor`: `get_references(arxiv_id)`, `get_cited_by(arxiv_id)`, `fetch_cited_paper_sections(arxiv_id, depth)`. The existing ReAct graph picks them up automatically.
- D-12: `Agent.__init__` gets `citation_depth: int = 1` parameter — passed to `ToolExecutor` to cap recursion. Default 1 hop matches requirements spec.
- D-13: `fetch_cited_paper_sections` uses `in_corpus=True` filter: only fetches sections for papers where `head()["sections"]` is non-empty (i.e., paper is in our corpus). Silently skips papers not in corpus.
- D-14: Tool description in `get_tools_definition()` must clearly explain citation-aware behavior so the ReAct LLM knows when to use it

**Test strategy**
- D-15: Two-tier testing:
  - Unit tests (`sdk/tests/test_reader.py` etc.): all existing tests pass without a live backend — they mock HTTP via `unittest.mock.patch`. Update fixtures to match new response schemas (path-param URLs, our field names).
  - Integration tests (`sdk/tests/test_integration.py`): marked `@pytest.mark.integration`, require `docker compose up` with the `api` service running and ≥10 papers in DB. Verify SDK-02 (10 papers return non-empty content) and SDK-03 (references/cited_by return lists).
- D-16: "Passes full test suite" in success criteria = `pytest sdk/tests/ -m not integration` passes with zero failures. Integration tests are documented as a separate manual step.
- D-17: Integration tests use `httpx` or `requests` directly against `http://localhost:8000` — no mock overrides

### Claude's Discretion
- Exact handling of `section()` method (our backend returns all sections; client-side filtering or a new `sections()` method that returns all)
- Whether to keep `sdk/examples/` and `sdk/skills/` unchanged or update example base_urls
- Exact field mapping for response dicts (e.g., `publish_at` vs `year` — match what the backend actually returns)

### Deferred Ideas (OUT OF SCOPE)
- Async Reader variant (`AsyncReader`) — the current SDK is sync; an async version would be a separate phase
- MCP connector update to point at this backend — out of scope for Phase 6
- CLI (`deepxiv_sdk/cli.py`) update for this backend — out of scope
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SDK-01 | deepxiv_sdk is forked and the default `base_url` is updated to point at this backend; fork is installable via `pip install -e` | D-01 through D-07; upstream pyproject.toml uses setuptools>=45, pip install -e works via `sdk/` subdirectory |
| SDK-02 | All existing deepxiv_sdk features work against this backend — `Reader.head()`, `Reader.brief()`, `Reader.sections()`, `Reader.full()`, `Reader.search()` return non-empty content for at least 10 test papers | D-04/D-05 URL rewrite; backend schemas confirmed; integration test tier documented |
| SDK-03 | SDK fork adds `Reader.references(arxiv_id)` and `Reader.cited_by(arxiv_id)` methods that call the citation graph endpoints | D-08/D-09; backend endpoints `/arxiv/{id}/references` and `/arxiv/{id}/cited_by` confirmed in routes/arxiv.py |
| SDK-04 | SDK fork ships an improved Agent that performs citation-aware reading; depth configurable, default 1 hop | D-11 through D-14; ToolExecutor extension pattern confirmed from upstream graph.py |
</phase_requirements>

---

## Summary

Phase 6 forks the upstream `deepxiv_sdk` (Reader + Agent) into the `sdk/` subdirectory of this repo and adapts it to talk to the FastAPI backend built in Phase 5. The central technical challenge is a URL construction rewrite: the upstream SDK uses query params (`?arxiv_id=X&type=head`) while this backend uses REST path params (`/arxiv/{id}/head`). Every Reader method that hits an arXiv or PMC endpoint must be rewritten. About a dozen upstream methods have no equivalent endpoint in this backend and must raise `NotImplementedError`.

The test strategy is two-tier. Unit tests mock all HTTP and run without a live server; they inherit the existing upstream `mock.patch` patterns but need updated fixtures to match path-param URLs and the exact field names from `app/api/schemas.py`. Integration tests (`@pytest.mark.integration`) run against a live `docker compose up api` instance and assert non-empty returns for at least 10 corpus papers.

The new SDK-04 citation-aware Agent is built by extending `ToolExecutor` (not subclassing Agent) with three new tools: `get_references`, `get_cited_by`, and `fetch_cited_paper_sections`. The existing ReAct graph dispatches tool calls through `configurable["tool_executor"]`, so adding methods to `ToolExecutor` and entries to `get_tools_definition()` is sufficient — no graph surgery required.

**Primary recommendation:** Copy the upstream repo into `sdk/`, rewrite `reader.py` URL construction, stub out non-mapped methods as `NotImplementedError`, update test fixtures to path-param URLs + our schema field names, then add new Reader and ToolExecutor methods in dedicated commits matched to plans 06-01, 06-02, 06-03.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| requests | upstream uses it internally | HTTP client for Reader | Already in upstream SDK; synchronous, matches SDK's sync design |
| pytest | upstream uses it; project already configured | Unit + integration test runner | Already in project pyproject.toml dev deps |
| unittest.mock | stdlib | HTTP mock for unit tests | Pattern established in upstream test suite and in `tests/test_api.py` |
| httpx | 0.28.1 (already in project deps) | Integration test HTTP calls (D-17) | Already a project dependency |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| setuptools | >=45 (upstream constraint) | `pip install -e ./sdk` package build | Required for editable install |
| pytest-cov | upstream dev dep | Coverage reporting | Optional; useful if verifying test coverage |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| requests (SDK) | httpx | httpx is already a project dep, but upstream SDK is built around requests; switching would require rewriting `_make_request`/`_make_post_request` — unnecessary for this phase |
| unittest.mock.patch | pytest-httpx | pytest-httpx is cleaner for httpx-based tests but upstream tests use mock.patch for requests; staying consistent reduces fixture rewrite scope |

**Installation (for sdk/ subdirectory):**
```bash
pip install -e ./sdk
```

**sdk/pyproject.toml minimum shape (carry over from upstream):**
```toml
[build-system]
requires = ["setuptools>=45", "wheel"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "deepxiv-sdk"
version = "0.2.0-local"
requires-python = ">=3.8"
dependencies = ["requests"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
  "integration: marks integration tests (deselect with '-m not integration')",
]
```

---

## Architecture Patterns

### Recommended Project Structure
```
sdk/
├── pyproject.toml           # package entrypoint (pip install -e ./sdk)
├── setup.py                 # legacy shim (keep for upstream compat)
├── deepxiv_sdk/
│   ├── __init__.py
│   ├── reader.py            # REWRITTEN: path-param URLs, NotImplementedError stubs
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── agent.py         # MODIFIED: add citation_depth param (D-12)
│   │   ├── graph.py         # unchanged
│   │   ├── prompts.py       # unchanged
│   │   ├── state.py         # unchanged
│   │   └── tools.py         # MODIFIED: add 3 citation tools + updated get_tools_definition
│   ├── cli.py               # unchanged (out of scope)
│   └── mcp_server.py        # unchanged (out of scope)
├── tests/
│   ├── conftest.py          # NEW: fixtures matching our response schemas
│   ├── test_reader.py       # REWRITTEN: path-param URL assertions + new method tests
│   ├── test_agent.py        # NEW: tests for citation_depth param + new tools
│   └── test_integration.py  # NEW: @pytest.mark.integration, requires live api
└── examples/                # unchanged or update base_url comments (discretion)
```

### Pattern 1: URL Construction Rewrite

**What:** Replace all `?arxiv_id=X&type=Y` query-param calls with path-param REST calls.

**When to use:** Every existing Reader method that called the upstream data.rag.ac.cn API.

**Example:**
```python
# BEFORE (upstream pattern)
def head(self, arxiv_id: str) -> Dict[str, Any]:
    params = {"arxiv_id": arxiv_id, "type": "head"}
    return self._make_request(self.arxiv_endpoint, params=params)

# AFTER (this backend)
def head(self, arxiv_id: str) -> Dict[str, Any]:
    url = f"{self.base_url}/arxiv/{arxiv_id}/head"
    return self._make_request(url)
```

### Pattern 2: NotImplementedError Stubs for Unmapped Methods

**What:** Preserve API surface but signal clearly that these endpoints are not backed.

**When to use:** Any method without a corresponding Phase 5 endpoint.

**Example:**
```python
def trending(self, *args, **kwargs):
    raise NotImplementedError(
        "trending() is not available against this backend. "
        "It requires the upstream data.rag.ac.cn service."
    )
```

Methods requiring stubs: `websearch`, `semantic_scholar`, `trending`, `biomed_search`, `biomed_data`, `social_impact`, `markdown`, `preview`.

### Pattern 3: New Reader Methods (SDK-03)

**What:** Thin wrappers that call citation graph endpoints and return raw dicts.

**When to use:** `Reader.references()` and `Reader.cited_by()`.

**Example:**
```python
def references(self, arxiv_id: str) -> Dict[str, Any]:
    """Return outgoing references for an arXiv paper.
    
    Returns dict with keys: paper_id (str), references (list of ReferenceItem dicts).
    Each ReferenceItem: target_arxiv_id, target_doi, context_text, in_corpus (bool),
    paper_id, title, abstract, authors, year, arxiv_id, pmc_id, doi, tldr, token_count.
    """
    url = f"{self.base_url}/arxiv/{arxiv_id}/references"
    return self._make_request(url)

def cited_by(self, arxiv_id: str) -> Dict[str, Any]:
    """Return papers in the corpus that cite this arXiv paper.
    
    Returns dict with keys: paper_id (str), cited_by (list of CitedByItem dicts).
    """
    url = f"{self.base_url}/arxiv/{arxiv_id}/cited_by"
    return self._make_request(url)
```

### Pattern 4: ToolExecutor Extension (SDK-04)

**What:** Add three citation-aware tools to `ToolExecutor` and register them in `get_tools_definition()`.

**When to use:** The ReAct graph dispatches by tool name through `tool_executor.execute_tool_call()`. Adding methods to `ToolExecutor` and entries to `get_tools_definition()` is sufficient — no changes needed to `graph.py`.

**Example (tool method):**
```python
def get_references(self, arxiv_id: str, state: dict) -> str:
    result = self.reader.references(arxiv_id)
    refs = result.get("references", [])
    in_corpus = [r for r in refs if r.get("in_corpus")]
    return (
        f"Paper {arxiv_id} has {len(refs)} references, "
        f"{len(in_corpus)} are in the local corpus.\n"
        + "\n".join(
            f"- {r.get('arxiv_id','?')}: {r.get('title','(no title)')}"
            for r in in_corpus[:20]
        )
    )

def fetch_cited_paper_sections(self, arxiv_id: str, state: dict) -> str:
    """Fetch sections for papers cited by arxiv_id that are in corpus.
    Respects self.citation_depth. Silently skips papers not in corpus."""
    result = self.reader.references(arxiv_id)
    refs = result.get("references", [])
    in_corpus_refs = [r for r in refs if r.get("in_corpus") and r.get("arxiv_id")]
    sections_gathered = []
    for ref in in_corpus_refs[:self.citation_depth * 5]:  # cap fetches
        cited_id = ref["arxiv_id"]
        try:
            head = self.reader.head(cited_id)
            if head.get("sections"):  # only if paper has sections in corpus
                sections = self.reader.sections(cited_id)
                sections_gathered.append((cited_id, sections))
        except Exception:
            continue
    # ... format and return
```

**Agent.__init__ change:**
```python
def __init__(self, ..., citation_depth: int = 1):
    ...
    self.tool_executor = ToolExecutor(reader, citation_depth=citation_depth)

# ToolExecutor.__init__:
def __init__(self, reader: Reader, citation_depth: int = 1):
    self.reader = reader
    self.citation_depth = citation_depth
    ...
```

### Pattern 5: Unit Test Mocking for Rewritten URLs

**What:** Update upstream test fixtures to assert path-param URLs and our field names.

**When to use:** All unit tests in `sdk/tests/test_reader.py`.

**Example:**
```python
# conftest.py fixture update
@pytest.fixture
def sample_paper_head():
    # Field names from app/api/schemas.py HeadResponse
    return {
        "paper_id": "00000000-0000-0000-0000-000000000001",
        "arxiv_id": "2401.00001",
        "pmc_id": None,
        "doi": None,
        "title": "Test Paper",
        "abstract": "Test abstract.",
        "tldr": "Test abstract.",   # tldr always present (NORM-03)
        "authors": ["Author One"],
        "year": 2024,
        "venue": None,
        "src_url": "https://arxiv.org/abs/2401.00001",
        "token_count": 512,
        "parse_source": "latex",
    }

# test_reader.py URL assertion
def test_head_uses_path_param(mock_reader):
    with patch.object(mock_reader, "_make_request") as mock_req:
        mock_req.return_value = sample_paper_head()
        mock_reader.head("2401.00001")
        mock_req.assert_called_once_with("http://localhost:8000/arxiv/2401.00001/head")
```

### Anti-Patterns to Avoid

- **Modifying graph.py:** The ReAct graph is wired at module level. Adding tools via `ToolExecutor` + `get_tools_definition()` is the correct extension point — do not touch graph.py.
- **Subclassing Agent for citation-awareness:** D-11 locks this. Extend `ToolExecutor`, not `Agent`.
- **Removing unmapped methods:** D-06 requires they raise `NotImplementedError`, not be deleted. API surface must be preserved.
- **Hardcoding `http://localhost:8000` in test fixtures for integration tests:** Use a `BASE_URL` env var or pytest fixture param — allows CI to override.
- **Fetching all sections in `fetch_cited_paper_sections` without a cap:** Without a cap, a paper with 50 in-corpus citations would make 50 network calls. Use `citation_depth * N` as a ceiling.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HTTP retry with backoff | Custom retry loop | The existing `_make_request()` in `reader.py` already implements exponential backoff with tenacity | It handles timeout, connection errors, 429, 5xx — reimplementing introduces regression risk |
| Section fuzzy matching | New string similarity logic | The upstream `_match_section_name()` helper in `reader.py` already does case-insensitive partial matching | Reuse as-is; our backend returns all sections via `/sections`, so the fetch changes but matching logic doesn't |
| pytest marker registration | Separate pytest plugin | The project `conftest.py` already registers `integration` marker via `pytest_configure` | Copy the existing pattern into `sdk/tests/conftest.py` — don't invent a second mechanism |
| Mock HTTP for unit tests | Custom HTTP intercept | `unittest.mock.patch` on `_make_request` | Established pattern in both upstream and project test suites |

**Key insight:** The upstream SDK's `_make_request` abstraction (single internal method) is the correct seam for testing. All public methods call it. Patching that one method mocks all HTTP.

---

## Common Pitfalls

### Pitfall 1: `sections()` vs `section()` naming

**What goes wrong:** The upstream SDK has `section(arxiv_id, section_name)` (singular, takes a name filter). The SDK-02 success criterion mentions `Reader.sections()` (plural, returns all). These are different signatures.

**Why it happens:** The CONTEXT.md discretion note says "Exact handling of `section()` method (our backend returns all sections; client-side filtering or a new `sections()` method that returns all)" — both should exist.

**How to avoid:** Keep `section(arxiv_id, section_name)` with client-side filtering (calls `/sections` internally, uses upstream `_match_section_name`). Add `sections(arxiv_id)` as a new convenience method that returns the raw sections list. Success criterion test calls `Reader.sections()` — this method must exist.

**Warning signs:** Integration test calling `reader.sections("2401.00001")` raises `AttributeError`.

### Pitfall 2: `tldr` field must always be present (NORM-03)

**What goes wrong:** SDK tests assert `result["tldr"]` is not None, but backend always returns `tldr` key (value may be null). Tests that do `assert result["tldr"]` (truthy check) will fail for papers with no TLDR.

**Why it happens:** NORM-03 guarantees the key exists but the value may be None. Upstream test fixtures may have assumed a non-null value.

**How to avoid:** In fixture data, set `tldr` to a non-None string. In tests that just verify the key exists: `assert "tldr" in result` (not truthiness check). In integration tests: assert `result.get("tldr") is not None` only for papers known to have TLDRs.

**Warning signs:** 5-10 integration tests failing on `AssertionError: None is not truthy`.

### Pitfall 3: `search` endpoint path difference

**What goes wrong:** The upstream SDK calls `/arxiv/?...` for all methods. The search endpoint is at `/arxiv/search?q=...` in this backend (note: `GET /arxiv/search`, not `GET /search`).

**Why it happens:** D-05 says `search(query, ...)` → `GET {base_url}/search?q={query}...` but checking `app/api/routes/search.py` the actual router path is `@router.get("/arxiv/search", ...)`. The `search.py` router is mounted at `/` in `main.py` (no prefix) so the full path is `/arxiv/search`.

**How to avoid:** Verify by reading `app/api/main.py` to confirm router mount prefixes before writing the SDK URL. The correct URL is `{base_url}/arxiv/search?q={query}&limit={limit}&search_mode={mode}`.

**Warning signs:** 404 responses from `Reader.search()` even when backend is running.

### Pitfall 4: `pip install -e ./sdk` fails if `sdk/` has no `__init__.py` at top-level

**What goes wrong:** Editable install fails if `sdk/pyproject.toml` doesn't have the correct `[tool.setuptools.packages.find]` or if the package is not discoverable.

**Why it happens:** The upstream repo structure has `deepxiv_sdk/` inside the repo root. When copied into `sdk/deepxiv_sdk/`, setuptools must find it.

**How to avoid:** `sdk/pyproject.toml` should include:
```toml
[tool.setuptools.packages.find]
where = ["."]
include = ["deepxiv_sdk*"]
```
Test with `pip install -e ./sdk --dry-run` before wiring any tests.

**Warning signs:** `ModuleNotFoundError: No module named 'deepxiv_sdk'` when running `python -c "from deepxiv_sdk import Reader"`.

### Pitfall 5: `authors` field shape mismatch

**What goes wrong:** Upstream SDK response fixtures may have `authors` as a list of dicts (with name, affiliation). This backend returns `authors` as `list[str]` per `HeadResponse`.

**Why it happens:** The upstream deepxiv_sdk used a richer author object from data.rag.ac.cn. This backend's normalizer stores and returns flat string lists per NORM-01 (`"authors": list[str]`).

**How to avoid:** Update all fixture `authors` values to `["Author One", "Author Two"]` (strings). Check test assertions — any that do `result["authors"][0]["name"]` will break.

**Warning signs:** `TypeError: string indices must be integers` inside SDK tests.

### Pitfall 6: Unit tests must NOT need a live backend

**What goes wrong:** If `sdk/tests/conftest.py` imports from `app.*` or tries to start the FastAPI app, tests fail in environments where the app module is not installed.

**Why it happens:** The SDK is a standalone package. Its unit tests must be runnable with just `pip install -e ./sdk`.

**How to avoid:** SDK `conftest.py` must not import anything from `app/`. All HTTP is mocked via `mock.patch("deepxiv_sdk.reader.Reader._make_request", ...)`. Check imports at the top of every `sdk/tests/*.py` file.

**Warning signs:** `ModuleNotFoundError: No module named 'app'` when running `pytest sdk/tests/ -m not integration`.

---

## Code Examples

Verified patterns from project source files:

### Backend Field Names (authoritative — from `app/api/schemas.py`)

```python
# HeadResponse / BriefResponse fields (what SDK receives from head/brief/search items)
{
    "paper_id": str,           # UUID as string
    "arxiv_id": str | None,
    "pmc_id": str | None,
    "doi": str | None,
    "title": str | None,
    "abstract": str | None,
    "tldr": str | None,        # always present as key (NORM-03)
    "authors": list[str],      # flat strings, NOT dicts
    "year": int | None,
    "venue": str | None,
    "src_url": str,            # default ""
    "token_count": int,        # default 0
    "parse_source": str | None,
}

# SectionsResponse
{
    "paper_id": str,
    "title": str | None,
    "sections": [              # list of SectionObject
        {
            "heading": str,
            "sec_num": str | None,
            "text": str,
            "paragraphs": list,
            "token_count": int,
        }
    ],
    "token_count": int,
}

# ReferencesResponse (SDK-03)
{
    "paper_id": str,
    "references": [            # list of ReferenceItem
        {
            "target_arxiv_id": str | None,
            "target_doi": str | None,
            "context_text": str | None,
            "in_corpus": bool,    # KEY FIELD for fetch_cited_paper_sections filter
            "paper_id": str | None,
            "title": str | None,
            "abstract": str | None,
            "authors": list[str],
            "year": int | None,
            "arxiv_id": str | None,
            "pmc_id": str | None,
            "doi": str | None,
            "tldr": str | None,
            "token_count": int | None,
        }
    ]
}

# CitedByResponse (SDK-03)
{
    "paper_id": str,
    "cited_by": [              # list of CitedByItem
        {
            "paper_id": str,
            "arxiv_id": str | None,
            "pmc_id": str | None,
            "title": str | None,
            "abstract": str | None,
            "authors": list[str],
            "year": int | None,
            "tldr": str | None,
            "token_count": int | None,
            "context_text": str | None,
        }
    ]
}

# SearchResponse
{
    "total": int,
    "results": [               # list of SearchResultItem (subset of HeadResponse fields)
        {
            "paper_id": str,
            "arxiv_id": str | None,
            "pmc_id": str | None,
            "title": str | None,
            "abstract": str | None,
            "tldr": str | None,
            "authors": list[str],
            "year": int | None,
            "src_url": str,
            "token_count": int,
        }
    ]
}
```

### MockRedis Pattern (already in project, replicate in SDK tests)

```python
# From tests/test_api.py — replicate in sdk/tests/conftest.py for any tests
# that indirectly need HTTP mock consistency
class MockHTTPSession:
    """Mock requests.Session for SDK unit tests."""
    def __init__(self, response_data):
        self._data = response_data

    def get(self, url, **kwargs):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = self._data
        return mock_resp
```

### Integration Test Template (`sdk/tests/test_integration.py`)

```python
import pytest
import os

BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

@pytest.mark.integration
class TestSDKIntegration:
    @pytest.fixture(autouse=True)
    def reader(self):
        from deepxiv_sdk import Reader
        return Reader(base_url=BASE_URL)

    def test_head_returns_non_empty(self, reader):
        # Use a paper known to be in corpus
        result = reader.head("2401.00001")
        assert result["title"] is not None
        assert result["tldr"] is not None  # key always present

    def test_ten_papers_non_empty(self, reader):
        """SDK-02: at least 10 papers return non-empty content."""
        test_ids = [...]  # 10+ arxiv IDs from corpus
        for arxiv_id in test_ids:
            result = reader.head(arxiv_id)
            assert result["title"], f"Empty title for {arxiv_id}"
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| deepxiv_sdk uses query params `?arxiv_id=X&type=head` | This fork uses REST path params `/arxiv/{id}/head` | Phase 6 (this phase) | All URL construction in reader.py must be rewritten |
| `authors` returned as list of dicts from upstream API | `authors` returned as `list[str]` by this backend | Phase 4 NORM-01 | All test fixtures using `authors[0]["name"]` must be updated |
| upstream SDK targets `https://data.rag.ac.cn` | Fork targets `http://localhost:8000` | Phase 6 | `base_url` default changed in `__init__` |
| `Agent.__init__` has no `citation_depth` param | Fork adds `citation_depth: int = 1` | Phase 6 | Passed to `ToolExecutor`; caps recursion in `fetch_cited_paper_sections` |

---

## Open Questions

1. **Exact `main.py` router mount prefixes for `search.py`**
   - What we know: `search.py` has `@router.get("/arxiv/search", ...)` but the router may be mounted with a prefix in `app/api/main.py`
   - What's unclear: Whether the final URL is `/arxiv/search` or `/search`
   - Recommendation: Read `app/api/main.py` as first action in Plan 06-01 to confirm; use that confirmed path in the SDK `search()` method

2. **Whether upstream `test_reader.py` has tests for `trending`, `biomed_search`, etc.**
   - What we know: The upstream test suite has `TestSearch`, `TestPaperAccess`, `TestSectionAccess`, `TestPMCAccess`, `TestErrorHandling`
   - What's unclear: Whether there are tests for the methods we stub as `NotImplementedError` — those tests would need to be removed or updated
   - Recommendation: Review upstream `test_reader.py` during 06-01 and remove/update tests for stubbed methods

3. **`sections()` method name in success criteria**
   - What we know: Success criterion says `Reader.sections()` but upstream SDK has `section(arxiv_id, section_name)` (singular)
   - What's unclear: Whether success criterion means the existing `section()` method works, or a new `sections()` method is required
   - Recommendation: Add a `sections(arxiv_id)` method that returns the full sections list (no filter). Keep `section(arxiv_id, name)` as a filtered convenience. This satisfies both the success criterion and D-05.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (already in project pyproject.toml dev deps) |
| Config file | `sdk/pyproject.toml` — `[tool.pytest.ini_options]` to be created |
| Quick run command | `pytest sdk/tests/ -m "not integration" -x` |
| Full suite command | `pytest sdk/tests/ -m "not integration"` |
| Integration run | `pytest sdk/tests/ -m integration` (requires live backend) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SDK-01 | `pip install -e ./sdk` succeeds; `Reader(base_url="http://localhost:8000")` instantiates | smoke | `python -c "from deepxiv_sdk import Reader; Reader(base_url='http://localhost:8000')"` | Wave 0 |
| SDK-01 | `Reader.head()` calls `GET {base_url}/arxiv/{id}/head` (path param) | unit | `pytest sdk/tests/test_reader.py::TestReader::test_head_url_construction -x` | Wave 0 |
| SDK-01 | Unmapped methods raise `NotImplementedError` | unit | `pytest sdk/tests/test_reader.py::TestReader::test_not_implemented_methods -x` | Wave 0 |
| SDK-02 | `head/brief/sections/full/search` return non-empty for 10 corpus papers | integration | `pytest sdk/tests/test_integration.py::TestSDKIntegration::test_ten_papers_non_empty -m integration` | Wave 0 |
| SDK-03 | `Reader.references()` calls `/arxiv/{id}/references`, returns dict with `references` key | unit | `pytest sdk/tests/test_reader.py::TestReader::test_references_method -x` | Wave 0 |
| SDK-03 | `Reader.cited_by()` calls `/arxiv/{id}/cited_by`, returns dict with `cited_by` key | unit | `pytest sdk/tests/test_reader.py::TestReader::test_cited_by_method -x` | Wave 0 |
| SDK-03 | `references()`/`cited_by()` return non-empty lists for corpus papers | integration | `pytest sdk/tests/test_integration.py::TestSDKIntegration::test_references_cited_by -m integration` | Wave 0 |
| SDK-04 | `ToolExecutor` has `get_references`, `get_cited_by`, `fetch_cited_paper_sections` methods | unit | `pytest sdk/tests/test_agent.py::TestToolExecutor -x` | Wave 0 |
| SDK-04 | `Agent(citation_depth=2)` passes depth to `ToolExecutor` | unit | `pytest sdk/tests/test_agent.py::TestAgent::test_citation_depth_param -x` | Wave 0 |
| SDK-04 | `fetch_cited_paper_sections` skips papers where `in_corpus=False` | unit | `pytest sdk/tests/test_agent.py::TestToolExecutor::test_fetch_skips_not_in_corpus -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest sdk/tests/ -m "not integration" -x`
- **Per wave merge:** `pytest sdk/tests/ -m "not integration"`
- **Phase gate:** Full suite green before `/gsd:verify-work`; integration tests documented as manual step requiring `docker compose up api`

### Wave 0 Gaps (all test files must be created)
- [ ] `sdk/tests/conftest.py` — fixtures matching our schema field names (HeadResponse, SectionsResponse, ReferencesResponse, CitedByResponse shapes)
- [ ] `sdk/tests/test_reader.py` — rewritten from upstream; path-param URL assertions + new `references`/`cited_by`/`sections` method tests
- [ ] `sdk/tests/test_agent.py` — tests for `citation_depth` param, new ToolExecutor tools, `fetch_cited_paper_sections` corpus filter
- [ ] `sdk/tests/test_integration.py` — `@pytest.mark.integration`, 10-paper corpus verification, references/cited_by live calls
- [ ] `sdk/pyproject.toml` — `[tool.pytest.ini_options]` with `integration` marker and `testpaths = ["tests"]`

---

## Sources

### Primary (HIGH confidence)
- `/Users/henrycui/Desktop/DATS5990_final/app/api/schemas.py` — Exact response field names (authoritative ground truth for SDK fixtures)
- `/Users/henrycui/Desktop/DATS5990_final/app/api/routes/arxiv.py` — Exact endpoint paths, confirmed `/arxiv/{id}/references` and `/arxiv/{id}/cited_by` exist
- `/Users/henrycui/Desktop/DATS5990_final/app/api/routes/search.py` — Search endpoint at `@router.get("/arxiv/search", ...)` with `q`, `limit`, `search_mode` params
- `/Users/henrycui/Desktop/DATS5990_final/tests/test_api.py` — MockRedis pattern and `mock.patch` + `dependency_overrides` test patterns
- `https://github.com/DeepXiv/deepxiv_sdk` — Upstream repo structure confirmed: `reader.py`, `agent/tools.py`, `agent/graph.py`, `tests/test_reader.py`

### Secondary (MEDIUM confidence)
- Upstream `agent/graph.py` analysis via WebFetch: `tool_executor = configurable.get("tool_executor")` is the dispatch pattern — adding methods to `ToolExecutor` and entries to `get_tools_definition()` is sufficient
- Upstream `agent/agent.py` analysis: `self.tool_executor = ToolExecutor(reader)` — adding `citation_depth` requires changing this line and `ToolExecutor.__init__` signature
- Upstream `tests/test_reader.py` analysis: `mock.patch()` on `_make_request` is the established unit test pattern; fixtures use dict response returns

### Tertiary (LOW confidence)
- None — all key claims verified from project source files or upstream GitHub

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already in project or confirmed in upstream repo
- Architecture: HIGH — URL patterns confirmed from route files; ToolExecutor extension pattern confirmed from graph.py analysis
- Pitfalls: HIGH (field name mismatches, sections naming) — verified from schemas.py and CONTEXT.md; MEDIUM (pip install -e edge cases) — based on setuptools knowledge, not tested

**Research date:** 2026-04-16
**Valid until:** 2026-05-16 (stable libraries; upstream SDK structure unlikely to change)
