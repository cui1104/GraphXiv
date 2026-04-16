---
phase: 6
slug: sdk-fork-verification
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-16
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | `sdk/pyproject.toml` (or Wave 0 installs) |
| **Quick run command** | `cd sdk && pytest tests/ -x -q` |
| **Full suite command** | `cd sdk && pytest tests/ -v` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `cd sdk && pytest tests/ -x -q`
- **After every plan wave:** Run `cd sdk && pytest tests/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 06-01-01 | 01 | 1 | SDK-01 | install | `pip install -e ./sdk && python -c "from deepxiv_sdk import Reader; r = Reader(); print('OK')"` | ❌ W0 | ⬜ pending |
| 06-01-02 | 01 | 1 | SDK-01 | unit | `cd sdk && pytest tests/test_reader.py::test_url_construction -x -q` | ❌ W0 | ⬜ pending |
| 06-01-03 | 01 | 1 | SDK-01 | integration | `cd sdk && pytest tests/test_reader.py::test_head -x -q` | ❌ W0 | ⬜ pending |
| 06-02-01 | 02 | 2 | SDK-02 | integration | `cd sdk && pytest tests/test_contract.py -x -q` | ❌ W0 | ⬜ pending |
| 06-02-02 | 02 | 2 | SDK-02 | integration | `cd sdk && pytest tests/test_contract.py::test_all_methods_non_empty -x -q` | ❌ W0 | ⬜ pending |
| 06-03-01 | 03 | 3 | SDK-03 | unit | `cd sdk && pytest tests/test_caching.py -x -q` | ❌ W0 | ⬜ pending |
| 06-03-02 | 03 | 3 | SDK-03 | integration | `cd sdk && pytest tests/test_new_capability.py -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `sdk/tests/__init__.py` — empty init
- [ ] `sdk/tests/conftest.py` — shared fixtures (base_url, sample arxiv IDs, mock responses)
- [ ] `sdk/tests/test_reader.py` — stubs for SDK-01 URL construction and method importability
- [ ] `sdk/tests/test_contract.py` — stubs for SDK-02 contract verification (non-empty content, 10 papers)
- [ ] `sdk/tests/test_caching.py` — stubs for SDK-03 caching behavior
- [ ] `sdk/tests/test_new_capability.py` — stubs for SDK-03 new capability (tables or caching TTL)
- [ ] `pytest` installed in SDK dev dependencies

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `pip install -e ./sdk` succeeds on clean env | SDK-01 | Requires fresh venv; automated test assumes installed | Create a new venv, run `pip install -e ./sdk`, check exit code 0 |
| 10 real arXiv papers return non-empty content | SDK-02 | Requires live backend running at localhost:8000 | Start backend, run `pytest tests/test_contract.py -k "live"` |
| Caching: second call does not make network request | SDK-03 | Requires network interception (mitmproxy or mock) | Use `responses` or `httpretty` to intercept — captured in test_caching.py |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
