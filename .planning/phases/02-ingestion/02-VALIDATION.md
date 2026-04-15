# Phase 2: Ingestion - Validation

**Created:** 2026-04-14
**Source:** 02-RESEARCH.md Validation Architecture section

---

## Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (already in pyproject.toml dev dependencies) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (testpaths = ["tests"]) |
| Quick run command | `pytest tests/test_ingest.py -x -q` |
| Full suite command | `pytest tests/ -x -q` |

---

## Requirement-to-Test Map

| Req ID | Behavior | Test Type | Automated Command | Plan |
|--------|----------|-----------|-------------------|------|
| INGEST-01 | arXiv OAI-PMH harvests records for cs:cs:LG set | integration (live network) | `pytest tests/test_ingest.py::test_arxiv_oai_harvest_smoke -x` | 02-04 |
| INGEST-01 | Rate limiter enforces 3 req/sec | unit | `pytest tests/test_ingest.py::test_rate_limiter -x` | 02-02 |
| INGEST-01 | User-Agent header present on request | unit (httpx mock) | `pytest tests/test_ingest.py::test_user_agent_header -x` | 02-02 |
| INGEST-02 | Content-Type routing: tar.gz to latex, pdf to pdf | unit | `pytest tests/test_ingest.py::test_download_eprint_content_type_latex -x` | 02-02 |
| INGEST-02 | Asset written to disk at correct path | integration | `pytest tests/test_ingest.py::test_asset_download -x` | 02-02 |
| INGEST-03 | PMC OAI-PMH returns records with PMC identifiers | integration | `pytest tests/test_ingest.py::test_pmc_harvest_smoke -x` | 02-04 |
| INGEST-03 | DL keyword filter correctly classifies papers | unit | `pytest tests/test_ingest.py::test_is_dl_paper_positive -x` | 02-03 |
| INGEST-04 | Restarting harvest skips already-ingested IDs | unit (DB) | `pytest tests/test_ingest.py::test_is_already_ingested_true -x` | 02-01 |
| INGEST-05 | arxiv_id normalization strips v1/v2 suffixes | unit | `pytest tests/test_ingest.py::test_normalize_arxiv_id_new_format -x` | 02-01 |
| INGEST-05 | Re-ingesting v2 paper updates existing record | unit (DB) | `pytest tests/test_ingest.py::test_upsert_on_version_update -x` | 02-02 |
| INGEST-06 | paper_sources row count >= 100 after 100-paper test run | integration | `pytest tests/test_ingest.py::test_100_paper_smoke -x` | 02-04 |

---

## Wave 0 Test Scaffold

Created in 02-01 Task 2:
- `tests/test_ingest.py` — unit tests for ID normalization, dedup logic, crawl_state upsert, constants
- `tests/conftest.py` — `mock_db_session` fixture (SQLite in-memory), `pytest_configure` with integration marker

Extended in 02-02 Task 2:
- XML parsing tests (`_parse_arxiv_records`, `_extract_resumption_token`)
- Content-Type routing tests (`download_eprint_content_type_latex`, `download_eprint_content_type_pdf`)

Extended in 02-03 Task 2:
- PMC ID extraction test (`_extract_pmc_id`)
- DL keyword filter tests (`_is_dl_paper`)
- PMC constants verification

Extended in 02-04 Task 1:
- Integration test for harvest runner status command

---

## Sampling Rate

- **Per task commit:** `pytest tests/test_ingest.py -x -q -k "not integration and not smoke and not 100_paper"`
- **Per wave merge:** `pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

---

## Dependencies

- `pytest-httpx` — for mocking httpx requests in unit tests (added to dev dependencies in 02-01)
