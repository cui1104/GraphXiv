---
phase: 4
slug: normalizer-storage
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-15
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (installed) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `pytest tests/test_normalize.py -x -q` |
| **Full suite command** | `pytest tests/ -x -q -m "not gpu"` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_normalize.py -x -q`
- **After every plan wave:** Run `pytest tests/ -x -q -m "not gpu"`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 4-01-01 | 01 | 1 | NORM-01 | unit | `pytest tests/test_normalize.py::test_normalize_s2orc -x` | ❌ W0 | ⬜ pending |
| 4-01-02 | 01 | 1 | NORM-01 | unit | `pytest tests/test_normalize.py::test_normalize_mineru -x` | ❌ W0 | ⬜ pending |
| 4-01-03 | 01 | 1 | NORM-01 | unit | `pytest tests/test_normalize.py::test_parse_tei_sections -x` | ❌ W0 | ⬜ pending |
| 4-01-04 | 01 | 1 | NORM-05 | unit | `pytest tests/test_normalize.py::test_section_shape -x` | ❌ W0 | ⬜ pending |
| 4-01-05 | 01 | 1 | NORM-05 | unit | `pytest tests/test_normalize.py::test_citation_shape -x` | ❌ W0 | ⬜ pending |
| 4-02-01 | 02 | 1 | NORM-02 | unit | `pytest tests/test_normalize.py::test_token_count -x` | ❌ W0 | ⬜ pending |
| 4-02-02 | 02 | 1 | NORM-02 | integration | `pytest tests/test_normalize.py::test_token_count_in_db -x -m integration` | ❌ W0 | ⬜ pending |
| 4-02-03 | 02 | 1 | NORM-03 | unit | `pytest tests/test_normalize.py::test_tldr_always_present -x` | ❌ W0 | ⬜ pending |
| 4-02-04 | 02 | 1 | NORM-03 | unit | `pytest tests/test_normalize.py::test_tldr_content -x` | ❌ W0 | ⬜ pending |
| 4-02-05 | 02 | 1 | NORM-06 | unit | `pytest tests/test_normalize.py::test_parse_quality -x` | ❌ W0 | ⬜ pending |
| 4-03-01 | 03 | 2 | NORM-04 | unit | `pytest tests/test_normalize.py::test_dedup_fingerprint -x` | ❌ W0 | ⬜ pending |
| 4-03-02 | 03 | 2 | NORM-04 | integration | `pytest tests/test_normalize.py::test_cross_source_dedup -x -m integration` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_normalize.py` — all 12 test stubs covering NORM-01 through NORM-06; inline fixture data (minimal S2ORC JSON dict, MinerU content_list JSON, GROBID TEI XML bytes — no external files needed)

*Existing pytest infrastructure covers framework setup — only the test file is missing.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| deepxiv_sdk Reader field accesses work on 5+ stored papers | NORM-05 | Requires live DB + real paper data | Run `python -c "from deepxiv_sdk import Reader; r=Reader(); p=r.get('2401.00001'); assert p.sections[0].heading"` against 5 papers |
| tiktoken vocab pre-cached in Docker image | NORM-02 | Docker image build verification | `docker build -t test .` — must succeed without network access during `import tiktoken; tiktoken.get_encoding('cl100k_base')` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
