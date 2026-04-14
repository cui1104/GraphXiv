---
phase: 1
slug: foundation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-13
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (latest) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `pytest tests/test_infra.py -x -v` |
| **Full suite command** | `pytest tests/ -v` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_infra.py -x -v`
- **After every plan wave:** Run `pytest tests/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 1-01-01 | 01 | 1 | INFRA-01 | smoke/manual | `docker compose ps --format json \| jq '.[] \| select(.Health != "healthy")'` | manual | ⬜ pending |
| 1-02-01 | 02 | 1 | INFRA-02, INFRA-06 | integration | `pytest tests/test_infra.py::test_schema -x` | ❌ W0 | ⬜ pending |
| 1-02-02 | 02 | 1 | INFRA-05 | integration | `pytest tests/test_infra.py::test_alembic -x` | ❌ W0 | ⬜ pending |
| 1-02-03 | 02 | 1 | INFRA-06 | integration | `pytest tests/test_infra.py::test_pgvector -x` | ❌ W0 | ⬜ pending |
| 1-03-01 | 03 | 2 | INFRA-03 | integration | `pytest tests/test_infra.py::test_redis -x` | ❌ W0 | ⬜ pending |
| 1-03-02 | 03 | 2 | INFRA-04 | integration | `pytest tests/test_infra.py::test_celery_queues -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/conftest.py` — shared fixtures: db engine from `DATABASE_URL`, Redis client, Celery app import
- [ ] `tests/test_infra.py` — stubs for INFRA-01 through INFRA-06 (schema, alembic, redis, celery queues, pgvector)
- [ ] `pytest` and `pytest-timeout` install via `pyproject.toml` dev dependencies

*Wave 0 must run before any plan tasks execute.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| All 5 services healthy after `docker compose up` | INFRA-01 | Requires running Docker daemon | `docker compose up -d && docker compose ps` — all services show `healthy` status |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
