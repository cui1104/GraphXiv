---
phase: 02-ingestion
plan: 02
subsystem: ingestion
tags: [crawler, arxiv, oai-pmh, celery, async, httpx, rate-limiter]
dependency_graph:
  requires: [02-01]
  provides: [arxiv-oai-harvester, arxiv-asset-downloader, celery-ingest-tasks]
  affects: [02-03, 03-parser-layer]
tech_stack:
  added: [aiolimiter==1.2.1, tenacity==9.1.4, lxml==6.0.4, pytest-httpx==0.35.0]
  patterns: [async-oai-pmh-harvest, content-type-routing, celery-lazy-import, upsert-on-conflict]
key_files:
  created:
    - app/crawler/arxiv_oai.py
    - app/crawler/arxiv_assets.py
  modified:
    - app/tasks/ingest.py
    - tests/test_ingest.py
decisions:
  - "Lazy import of pmc_oai.harvest_pmc inside ingest_paper function body avoids ImportError at module load time, allowing 02-02 and 02-03 to be developed independently in parallel waves"
  - "lxml {*} wildcard namespace matching makes _parse_arxiv_records robust to both namespace-qualified and bare arXivRaw child elements"
  - "_fetch_page uses the module-level RATE_LIMITER so all calls across all sets share the same token bucket"
  - "rate_limiter in arxiv_assets.py is module-level AsyncLimiter; in production only one event loop exists, so no re-use issue"
metrics:
  duration: 8min
  completed_date: "2026-04-15"
  tasks: 2
  files: 4
---

# Phase 02 Plan 02: arXiv OAI-PMH Harvester and Asset Downloader Summary

**One-liner:** Async arXiv OAI-PMH harvester with 3 req/sec rate limiting, crash-resumable via crawl_state, enqueuing Celery download_asset tasks; plus Content-Type-routed e-print asset downloader replacing stub Celery tasks.

## What Was Built

### Task 1 — arXiv OAI-PMH Harvester (`app/crawler/arxiv_oai.py`)

- `RATE_LIMITER = AsyncLimiter(3, 1)` — module-level token bucket (3 req/sec)
- `_fetch_page(client, params)` — async, rate-limited, tenacity-retried (5 attempts, exponential backoff 4-60s); sends `User-Agent: DATS5990-ResearchKG/1.0 (mailto:hc1408@georgetown.edu)` on every request
- `_parse_arxiv_records(xml_text)` — lxml-based arXivRaw parser; uses `{*}` namespace wildcard so it handles both OAI-namespace-qualified and bare child elements; normalizes arxiv_id via `normalize_arxiv_id()`; logs and skips malformed records
- `_extract_resumption_token(xml_text)` — handles post-March-2025 arXiv tokens (no completeListSize/cursor); returns None when harvest is complete
- `harvest_arxiv_set(set_name, from_date)` — full harvest loop: resumes from crawl_state token, upserts Paper rows with `pg_insert(...).on_conflict_do_update(index_elements=["arxiv_id"])` (INGEST-05), creates PaperSource rows, enqueues `download_asset.apply_async` for each new paper (INGEST-02), saves crawl_state after every page
- `harvest_all_arxiv(from_date)` — sequential harvest of all 5 DL category sets (cs:cs:LG, cs:cs:AI, cs:cs:CV, cs:cs:CL, stat:stat:ML)

### Task 2 — Asset Downloader + Celery Tasks + Tests

**`app/crawler/arxiv_assets.py`:**
- `download_eprint_asset(arxiv_id, client)` — fetches `{ARXIV_EPRINT_BASE}/{arxiv_id}`, extracts Content-Type, maps to extension via `CONTENT_TYPE_TO_EXT`, classifies source_type as `"latex"` (for eprint), `"pdf"`, or `"unknown"`; saves to `{settings.data_dir}/assets/arxiv/{arxiv_id}{ext}`; logs warning for unknown content-types

**`app/tasks/ingest.py`** (stubs replaced):
- `ingest_paper(paper_id, source)` — `source="arxiv"` calls `asyncio.run(harvest_arxiv_set(paper_id))`; `source="pmc"` uses lazy import of `harvest_pmc` from `app.crawler.pmc_oai` (allows 02-03 to create pmc_oai.py independently); `time_limit=300s` (harvests take minutes)
- `download_asset(paper_id, source_type)` — calls `asyncio.run(download_eprint_asset(paper_id))`, updates `PaperSource.asset_path` and `PaperSource.source_type` in DB; `time_limit=120s`

**`tests/test_ingest.py`** (14 new tests added):
- `test_arxiv_oai_parse_records` — minimal arXivRaw XML with one record
- `test_arxiv_oai_extract_token` / `test_arxiv_oai_extract_token_empty`
- `test_rate_limiter` — verifies `AsyncLimiter(3, 1)` configuration
- `test_user_agent_header` — uses pytest-httpx to verify User-Agent on every request
- `test_download_eprint_content_type_latex` / `test_download_eprint_content_type_pdf`
- `test_asset_download` — verifies file written to `tmp_path/assets/arxiv/2401.00001.tar.gz`
- `test_ingest_paper_pmc_branch` — verifies PMC Celery branch with fake pmc_oai module
- `test_upsert_on_version_update` — `@pytest.mark.integration`, skips if PostgreSQL unavailable

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | `04c0399` | feat(02-02): implement arXiv OAI-PMH harvester |
| 2 | `4b1b225` | feat(02-02): arXiv asset downloader, real Celery tasks, and tests |

## Test Results

```
pytest tests/test_ingest.py -x -q -k "not integration and not smoke and not 100_paper"
24 passed, 1 deselected, 3 warnings in 0.21s
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed lxml element truth-testing in `_parse_arxiv_records`**
- **Found during:** Task 1 verification (test_arxiv_oai_parse_records failed)
- **Issue:** Using Python `or` with lxml elements triggers FutureWarning (element truth value) and fails when arXivRaw children are namespace-qualified — `meta_elem.find("{*}id") or meta_elem.find("id")` evaluates the first result as a boolean, which always returns True even for empty elements
- **Fix:** Replaced `or` with `is None` guard in `_text()` helper; added `{*}` wildcard for all child tag lookups
- **Files modified:** `app/crawler/arxiv_oai.py`
- **Commit:** `04c0399` (folded into same commit)

**2. [Rule 1 - Bug] Fixed pytest-httpx URL matcher mismatch in `test_user_agent_header`**
- **Found during:** Task 2 test run
- **Issue:** `httpx_mock.add_response(url=ARXIV_OAI_BASE)` uses exact URL matching but the actual request includes `?verb=ListRecords` query params — pytest-httpx 0.35.0 doesn't strip query params for this matcher
- **Fix:** Removed the `url=` parameter so the mock matches any request; the test still validates the User-Agent header
- **Files modified:** `tests/test_ingest.py`
- **Commit:** `4b1b225` (folded into same commit)

## Known Stubs

None — all stubs in `app/tasks/ingest.py` replaced with real implementations.

## Self-Check: PASSED

- `app/crawler/arxiv_oai.py` exists: FOUND
- `app/crawler/arxiv_assets.py` exists: FOUND
- `app/tasks/ingest.py` updated (no stubs): FOUND
- `tests/test_ingest.py` updated: FOUND
- Commit `04c0399` (Task 1): FOUND
- Commit `4b1b225` (Task 2): FOUND
- All 24 non-integration tests: PASSED
