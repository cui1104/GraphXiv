# Phase 6: SDK Fork + Verification - Context

**Gathered:** 2026-04-16
**Status:** Ready for planning

<domain>
## Phase Boundary

Fork deepxiv_sdk, update it to point at this backend, verify all existing SDK Reader features work, add `Reader.references()` + `Reader.cited_by()` (SDK-03), and ship a citation-aware `Agent` (SDK-04). The fork is installable via `pip install -e ./sdk`. No new backend endpoints — Phase 5 already built everything the SDK needs.

</domain>

<decisions>
## Implementation Decisions

### Fork location
- **D-01:** Fork lives at `sdk/` subdirectory within this repo — not a separate GitHub repository
- **D-02:** `pip install -e ./sdk` installs it in development mode; `sdk/pyproject.toml` and `sdk/setup.py` are the package entrypoints
- **D-03:** The fork is seeded by cloning/copying the upstream `https://github.com/DeepXiv/deepxiv_sdk` into `sdk/`, then applying changes in-place

### URL construction rewrite (required, not optional)
- **D-04:** The original SDK sends `GET /arxiv/?arxiv_id=X&type=head` (query params). This backend uses path params: `GET /arxiv/{id}/head`. Every Reader method's URL construction must be rewritten to use path params.
- **D-05:** New endpoint pattern in Reader:
  - `head(arxiv_id)` → `GET {base_url}/arxiv/{arxiv_id}/head`
  - `brief(arxiv_id)` → `GET {base_url}/arxiv/{arxiv_id}/brief`
  - `section(arxiv_id, section_name)` → `GET {base_url}/arxiv/{arxiv_id}/sections` (fetch all, filter by name client-side)
  - `raw(arxiv_id)` / `json(arxiv_id)` → `GET {base_url}/arxiv/{arxiv_id}/full`
  - `pmc_head(pmc_id)` → `GET {base_url}/pmc/{pmc_id}/head`
  - `pmc_full(pmc_id)` / `pmc_json(pmc_id)` → `GET {base_url}/pmc/{pmc_id}/full`
  - `search(query, ...)` → `GET {base_url}/arxiv/search?q={query}&limit={size}&search_mode={mode}` (corrected: actual route is `/arxiv/search` per routes/search.py)
- **D-06:** Methods that don't map to this backend (`websearch`, `semantic_scholar`, `trending`, `biomed_*`, `social_impact`, `markdown`, `preview`) raise `NotImplementedError` with a clear message — they are not removed (preserves API surface for future phases)
- **D-07:** Default `base_url` changed from `"https://data.rag.ac.cn"` to `"http://localhost:8000"`

### SDK-03: new Reader methods
- **D-08:** `Reader.references(arxiv_id: str) -> Dict[str, Any]` — calls `GET {base_url}/arxiv/{arxiv_id}/references`, returns raw response dict (list of CitationObject dicts under key `references`)
- **D-09:** `Reader.cited_by(arxiv_id: str) -> Dict[str, Any]` — calls `GET {base_url}/arxiv/{arxiv_id}/cited_by`, returns raw response dict
- **D-10:** Return type is `Dict[str, Any]` — consistent with every other Reader method (no custom typed objects introduced)

### SDK-04: citation-aware Agent
- **D-11:** No new Agent subclass — extend by adding tools to `ToolExecutor`: `get_references(arxiv_id)`, `get_cited_by(arxiv_id)`, `fetch_cited_paper_sections(arxiv_id, depth)`. The existing ReAct graph picks them up automatically.
- **D-12:** `Agent.__init__` gets `citation_depth: int = 1` parameter — passed to `ToolExecutor` to cap recursion. Default 1 hop matches requirements spec.
- **D-13:** `fetch_cited_paper_sections` uses `in_corpus=True` filter: only fetches sections for papers where `head()["sections"]` is non-empty (i.e., paper is in our corpus). Silently skips papers not in corpus.
- **D-14:** Tool description in `get_tools_definition()` must clearly explain citation-aware behavior so the ReAct LLM knows when to use it

### Test strategy
- **D-15:** Two-tier testing:
  - Unit tests (`sdk/tests/test_reader.py` etc.): all existing tests pass without a live backend — they mock HTTP via `unittest.mock.patch`. Update fixtures to match new response schemas (path-param URLs, our field names).
  - Integration tests (`sdk/tests/test_integration.py`): marked `@pytest.mark.integration`, require `docker compose up` with the `api` service running and ≥10 papers in DB. Verify SDK-02 (10 papers return non-empty content) and SDK-03 (references/cited_by return lists).
- **D-16:** "Passes full test suite" in success criteria = `pytest sdk/tests/ -m not integration` passes with zero failures. Integration tests are documented as a separate manual step.
- **D-17:** Integration tests use `httpx` or `requests` directly against `http://localhost:8000` — no mock overrides

### Claude's Discretion
- Exact handling of `section()` method (our backend returns all sections; client-side filtering or a new `sections()` method that returns all)
- Whether to keep `sdk/examples/` and `sdk/skills/` unchanged or update example base_urls
- Exact field mapping for response dicts (e.g., `publish_at` vs `year` — match what the backend actually returns)

</decisions>

<specifics>
## Specific Ideas

- The `section()` method in the original SDK does fuzzy section name matching (`_match_section_name`). Since our backend returns all sections in `/sections`, the fork should preserve this UX: `section(arxiv_id, "Introduction")` still works by fetching all sections and filtering client-side.
- `fetch_cited_paper_sections` tool description should be explicit: "after reading paper X's sections, use this tool to fetch sections of papers cited by X that are in the corpus, to incorporate their context before answering"

</specifics>

<canonical_refs>
## Canonical References

### Backend API contract
- `app/api/schemas.py` — All Pydantic response models; field names are the ground truth for what the SDK will receive
- `app/api/routes/arxiv.py` — Exact URL paths and response structures for arXiv endpoints
- `app/api/routes/pmc.py` — PMC endpoint paths
- `app/api/routes/search.py` — Search endpoint query params (`q`, `limit`, `search_mode`)

### Upstream SDK (read-only reference)
- Upstream repo: `https://github.com/DeepXiv/deepxiv_sdk` — original Reader class, Agent class, ToolExecutor, test fixtures
- Key files to seed fork from: `deepxiv_sdk/reader.py`, `deepxiv_sdk/agent/`, `tests/conftest.py`, `tests/test_reader.py`

### Requirements
- `.planning/REQUIREMENTS.md` §SDK — SDK-01 through SDK-04 define the four deliverables

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `app/api/schemas.py`: The exact field names in `HeadResponse`, `BriefResponse`, `SectionsResponse`, `FullResponse`, `SearchResponse`, `ReferencesResponse`, `CitedByResponse` are what the SDK will receive — use these as the source of truth when updating test fixtures
- `tests/test_api.py` MockRedis + dependency_overrides pattern: good reference for how to write mocked SDK tests

### Established Patterns
- `@pytest.mark.integration` is already configured in `pyproject.toml` — use it for SDK live tests too
- `httpx` is already a project dependency — use it in integration tests

### Integration Points
- SDK's `Reader(base_url="http://localhost:8000")` connects to the `api` Docker service from Phase 5
- The `api` service must be running (`docker compose up api`) for integration tests

</code_context>

<deferred>
## Deferred Ideas

- Async Reader variant (`AsyncReader`) — the current SDK is sync; an async version would be a separate phase
- MCP connector update to point at this backend — out of scope for Phase 6
- CLI (`deepxiv_sdk/cli.py`) update for this backend — out of scope

</deferred>

---

*Phase: 06-sdk-fork-verification*
*Context gathered: 2026-04-16*
