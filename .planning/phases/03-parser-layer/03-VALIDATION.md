---
phase: 3
slug: parser-layer
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-15
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (already in `[project.optional-dependencies] dev`) |
| **Config file** | `pyproject.toml` — `[tool.pytest.ini_options]` with `testpaths = ["tests"]` |
| **Quick run command** | `pytest tests/test_parse.py -x -q -m "not gpu"` |
| **Full suite command** | `pytest tests/ -x -q` |
| **Estimated runtime** | ~15 seconds (non-GPU); GPU tests skipped in CI |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_parse.py -x -q -m "not gpu"`
- **After every plan wave:** Run `pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green (GPU tests skipped unless on VM)
- **Max feedback latency:** ~15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 3-01-01 | 03-01 | 0 | PARSE-01 | unit | `pytest tests/test_parse.py::test_backslash_ratio_check -x` | ❌ W0 | ⬜ pending |
| 3-01-02 | 03-01 | 1 | PARSE-01 | integration | `pytest tests/test_parse.py::test_parse_latex_returns_s2orc -x` | ❌ W0 | ⬜ pending |
| 3-02-01 | 03-02 | 1 | PARSE-02 | unit | `pytest tests/test_parse.py::test_strip_doctype -x` | ❌ W0 | ⬜ pending |
| 3-02-02 | 03-02 | 1 | PARSE-02 | integration | `pytest tests/test_parse.py::test_parse_jats_returns_s2orc -x` | ❌ W0 | ⬜ pending |
| 3-03-01 | 03-03 | 1 | PARSE-03 | unit | `pytest tests/test_parse.py::test_scanned_pdf_detection -x` | ❌ W0 | ⬜ pending |
| 3-03-02 | 03-03 | 1 | PARSE-03 | integration (GPU) | `pytest tests/test_parse.py::test_mineru_pdf -x -m gpu` | ❌ W0 | ⬜ pending |
| 3-03-03 | 03-03 | 1 | PARSE-05 | unit | `pytest tests/test_parse.py::test_sentence_length_check -x` | ❌ W0 | ⬜ pending |
| 3-04-01 | 03-04 | 2 | PARSE-04 | unit (mock httpx) | `pytest tests/test_parse.py::test_grobid_references -x` | ❌ W0 | ⬜ pending |
| 3-04-02 | 03-04 | 2 | PARSE-05 | unit (mock tasks) | `pytest tests/test_parse.py::test_router_dispatch -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_parse.py` — all PARSE-* test stubs (listed above)
- [ ] `tests/fixtures/sample_arxiv.tar.gz` — minimal 1-page arXiv LaTeX paper for integration test
- [ ] `tests/fixtures/sample_pmc.xml` — minimal PMC JATS XML with NLM 2.x DOCTYPE
- [ ] `tests/fixtures/sample_scanned.pdf` — image-only PDF with no text layer (for scanned detection test)
- [ ] `pytest.ini` or `pyproject.toml` GPU marker — add `gpu` mark to `[tool.pytest.ini_options]` so GPU tests are skippable

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| tralics binary available in Docker | PARSE-01 | System package; cannot unit test | `docker compose run worker tralics --version` |
| MinerU model weights download | PARSE-03 | Multi-GB download; requires GPU worker | Run `parse_pdf_mineru` task on 1 real PDF, check Celery logs |
| GROBID reachable at `http://grobid:8070` | PARSE-04 | Docker network; requires compose up | `curl http://localhost:8070/api/isalive` |
| Celery group fan-out of 10k papers | PARSE-05 | Scale test; requires full corpus | Monitor Flower dashboard during batch dispatch |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
