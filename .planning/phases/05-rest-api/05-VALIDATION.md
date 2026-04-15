---
phase: 5
slug: rest-api
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-15
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (already installed) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `pytest tests/test_api.py -x -q` |
| **Full suite command** | `pytest tests/ -x -q` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_api.py -x -q`
- **After every plan wave:** Run `pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 5-01-01 | 01 | 1 | API-01,02,03,04 | unit (TestClient) | `pytest tests/test_api.py::test_arxiv_head tests/test_api.py::test_arxiv_brief tests/test_api.py::test_arxiv_sections tests/test_api.py::test_arxiv_full -x` | ❌ W0 | ⬜ pending |
| 5-01-02 | 01 | 1 | API-05 | unit (TestClient) | `pytest tests/test_api.py::test_search -x` | ❌ W0 | ⬜ pending |
| 5-01-03 | 01 | 1 | API-06,07 | unit (TestClient) | `pytest tests/test_api.py::test_pmc_head tests/test_api.py::test_pmc_full -x` | ❌ W0 | ⬜ pending |
| 5-01-04 | 01 | 1 | API-08 | unit (TestClient) | `pytest tests/test_api.py::test_404 -x` | ❌ W0 | ⬜ pending |
| 5-02-01 | 02 | 2 | API-09 | unit (mock Redis) | `pytest tests/test_api.py::test_redis_cache -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_api.py` — stubs for all 9 test functions covering API-01 through API-09; uses `fastapi.testclient.TestClient` with mock DB session and fixture papers
- [ ] `tests/conftest.py` — shared fixtures: fixture Paper row with full content JSONB, mock Redis client

*No framework install needed — pytest already in dev deps. `fastapi.testclient` available once fastapi is added to pyproject.toml in plan 05-01.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Redis cache active on live stack | API-09 | Requires live Redis + real HTTP | `curl http://localhost:8000/arxiv/1803.00679/head` twice; `docker exec redis redis-cli KEYS 'papers:*'` shows entry |
| Embeddings backfill populates pgvector | API-05 (vector mode) | Requires sentence-transformers inference | After backfill task runs: `SELECT count(*) FROM papers WHERE embeddings IS NOT NULL` returns > 0 |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
