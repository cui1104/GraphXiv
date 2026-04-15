---
phase: 03-parser-layer
plan: "03"
subsystem: parser
tags: [mineru, magic-pdf, pdf-parsing, celery, gpu-queue]
dependency_graph:
  requires: [03-01]
  provides: [parse_pdf_mineru task, MinerU GPU pipeline]
  affects: [app/tasks/parse.py, pyproject.toml, Dockerfile]
tech_stack:
  added: [magic-pdf[full]>=1.3.12]
  patterns: [lazy-import, scanned-pdf-detection, sentence-length-degradation, PymuDocDataset]
key_files:
  created: []
  modified:
    - app/tasks/parse.py
    - pyproject.toml
    - Dockerfile
    - tests/test_parse.py
decisions:
  - "All magic-pdf imports are lazy (inside parse_pdf_mineru body) to prevent ImportError on fast workers (Pitfall 3)"
  - "Scanned PDFs (text layer < 100 chars) set parse_status=scanned_skip and skip MinerU entirely"
  - "text_level_broken=True flag stored in content dict to warn Phase 4 about OSS MinerU limitation"
  - "MinerU GPU config (/root/magic-pdf.json) written before pip install in Dockerfile"
metrics:
  duration: 2m
  completed: "2026-04-15"
  tasks: 2
  files: 4
---

# Phase 03 Plan 03: MinerU PDF Parser Summary

MinerU PDF parsing task with pymupdf text-layer pre-check, PymuDocDataset pipeline, and sentence-length degradation detection using lazy magic-pdf imports.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add magic-pdf[full] to pyproject.toml and MinerU GPU config to Dockerfile | 9e2eaa0 | pyproject.toml, Dockerfile |
| 2 | Implement parse_pdf_mineru Celery task | 12d40bd | app/tasks/parse.py, tests/test_parse.py |

## What Was Built

The `parse_pdf_mineru` Celery task replaces the stub with a full MinerU-based PDF parsing pipeline:

1. **Text-layer pre-check** (`_has_text_layer` from parse_helpers): Scanned PDFs (< 100 chars total text) are immediately flagged as `parse_status=scanned_skip` without running MinerU.

2. **MinerU pipeline** (lazy imports, inside function body):
   - `PymuDocDataset.classify()` determines OCR vs txt mode
   - `doc_analyze` + `pipe_txt_mode` or `pipe_ocr_mode` runs the layout model
   - `dump_content_list()` writes structured JSON output

3. **Degradation check** (`_sentence_length_degraded` from parse_helpers): Avg sentence > 80 words sets `parse_quality=degraded` (multi-column concatenation artifact).

4. **DB update**: `paper.parse_source = "pdf_mineru"`, `text_level_broken=True` flag in content dict to warn Phase 4 that OSS MinerU does not provide heading hierarchy.

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None - parse_pdf_mineru is fully implemented. parse_pdf_grobid remains a stub (planned for 03-04).

## Self-Check: PASSED

- app/tasks/parse.py: FOUND (modified with parse_pdf_mineru implementation)
- pyproject.toml: FOUND (magic-pdf[full]>=1.3.12 added)
- Dockerfile: FOUND (magic-pdf.json config added before COPY pyproject.toml)
- tests/test_parse.py: FOUND (test_scanned_pdf_detection made real with importorskip)
- Commit 9e2eaa0: FOUND
- Commit 12d40bd: FOUND
