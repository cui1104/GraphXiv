# Phase 3: Parser Layer - Research

**Researched:** 2026-04-15
**Domain:** Scientific paper parsing — s2orc-doc2json (TEX2JSON/JATS2JSON), MinerU (magic-pdf), GROBID, Celery canvas
**Confidence:** MEDIUM-HIGH (core APIs verified against source; MinerU 1.x API verified against issue tracker example; system binary deps confirmed)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** TEX file detection: filename-arXiv-ID match first; if found with `\documentclass`, use it
- **D-02:** Largest `.tex` file containing `\documentclass` wins when no filename match
- **D-03:** No `\documentclass` found → inspect PDF: ≤3 tables → `parse_source=pdf_grobid`; >3 tables → `parse_source=pdf_mineru`
- **D-04:** Cascade on failure: TEX2JSON fails → MinerU if PDF exists; JATS2JSON fails → MinerU if PDF exists; MinerU fails → `parse_status=failed` (no further fallback)
- **D-05:** MinerU runs on existing Celery slow/GPU queue (`runtime: nvidia`); no new container
- **D-06:** For 10k batch, start with `concurrency=1` on slow queue; try `concurrency=2` if VRAM allows; use `celery group` for fan-out
- **D-07:** GROBID runs synchronously in chain, 30s timeout, non-blocking on failure → `citations=[]`
- **D-08:** MinerU JSON and GROBID TEI XML output flat section lists — hierarchy reconstruction is Phase 4
- **D-09:** Phase 4 normalizer MUST implement hierarchy reconstruction from `sec_num` strings
- **D-10:** All three parser outputs normalize to PaperJSON schema in Phase 4; Phase 3 returns raw parser output only
- **D-11:** s2orc-doc2json installed from GitHub HEAD (`git+https://github.com/allenai/s2orc-doc2json`); pin to commit SHA `71c022ed4bed3ffc71d22c2ac5cdbc133ad04e3c`
- **D-12:** Use `celery group` to fan out `pending` papers; group by asset type; saturate fast/slow queues concurrently

### Claude's Discretion
- Exact pymupdf table-count heuristic threshold calibration
- MinerU concurrency tuning (start at 1, tune up)
- GROBID HTTP client implementation details (httpx with 30s timeout)
- Temp directory cleanup strategy for `.tar.gz` extraction

### Deferred Ideas (OUT OF SCOPE)
- PySpark batch runner — evaluate only if Celery group throughput insufficient; not Phase 3 scope
- GPU concurrency tuning beyond `concurrency=2`
- Phase 4 hierarchy reconstruction implementation
- Nougat parser
- Table HTML rendering (EXT-03)
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PARSE-01 | TEX2JSON fast path — arXiv `.tar.gz` parsed by s2orc-doc2json; `\documentclass` heuristic for main `.tex`; >2% backslash tokens → `parse_quality=degraded` | `process_tex_stream` API confirmed; S2ORC JSON structure documented |
| PARSE-02 | JATS2JSON fast path — PMC JATS XML parsed by s2orc-doc2json; DOCTYPE detection; NLM 2.x normalization | `process_jats_stream` exists; s2orc-doc2json does NOT do DTD normalization internally — must be done before calling |
| PARSE-03 | MinerU PDF path — pymupdf text-layer pre-check; scanned PDFs flagged separately; MinerU on born-digital PDFs; avg sentence length >80 tokens → `parse_quality=degraded` | magic-pdf 1.3.12 PymuDocDataset API confirmed; text layer check pattern confirmed |
| PARSE-04 | GROBID reference extraction — `/api/processReferences`; enrich citations list | REST API format confirmed: POST multipart with `input` field; TEI XML response with `listBibl/biblStruct` |
| PARSE-05 | Parser routing — TEX2JSON → JATS2JSON → MinerU → GROBID priority; `parse_source` recorded; multi-column degradation detected | Celery chain/group patterns confirmed; queue routing already in celery_app.py |
</phase_requirements>

---

## Summary

Phase 3 fills in four Celery task stubs in `app/tasks/parse.py` with real parser implementations. Three distinct parsing paths exist: (1) TEX2JSON via `s2orc-doc2json` which wraps the system binaries `tralics` and `latexpand`, (2) JATS2JSON also via `s2orc-doc2json` using pure Python BeautifulSoup parsing, and (3) MinerU via `magic-pdf[full]` running on the GPU slow queue.

The most critical infrastructure discovery is that TEX2JSON requires two system binaries — `tralics` (C++ LaTeX-to-XML converter) and `latexpand` (from `texlive-extra-utils`) — that must be `apt install`ed in the Dockerfile. The current `Dockerfile` has `python:3.11-slim` base with no system packages installed beyond Python. This is a blocking prerequisite for plan 03-01.

The `process_tex_stream(fname, bytes)` function returns an S2ORC JSON dict directly; `process_jats_stream` follows the same pattern. Both write through temp files internally. For MinerU, the 1.x API uses `PymuDocDataset` + `doc_analyze` + `pipe_txt_mode`/`pipe_ocr_mode`, with `dump_content_list` for JSON output — but the open-source build has `text_level` always == 1 (no title/heading hierarchy detection), which means Phase 4 must reconstruct hierarchy from positional cues rather than `text_level`. GROBID `/api/processReferences` takes a `multipart/form-data` POST with field `input=<pdf_bytes>` and returns TEI XML parseable with lxml.

**Primary recommendation:** Add `tralics` + `texlive-extra-utils` to Dockerfile first (plan 03-01 prerequisite), then implement the four tasks strictly against the `process_tex_stream` / `process_jats_stream` / `PymuDocDataset` / httpx GROBID patterns documented below. All four tasks return raw dicts — zero normalization in Phase 3.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| s2orc-doc2json | git HEAD @ `71c022ed` | TEX2JSON + JATS2JSON parsers | Only maintained open-source S2ORC parser; AllenAI provenance |
| magic-pdf[full] | 1.3.12 | MinerU PDF-to-JSON (GPU-accelerated) | MinerU's official Python package; `[full]` includes layout models |
| PyMuPDF | 1.27.x | PDF text-layer pre-check, page-count | Best-in-class pymupdf; pure Python wheel, no system deps |
| httpx | 0.28.1 (already in pyproject.toml) | GROBID REST client with timeout | Already present; `httpx.Client(timeout=30)` for sync calls in Celery |
| lxml | 6.0.4 (already in pyproject.toml) | Parse GROBID TEI XML response | Already present; XPath for `listBibl/biblStruct` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| celery[redis] | 5.4.0 (present) | Chain/group canvas primitives | Router (03-04) dispatches chains and groups |
| tempfile (stdlib) | — | Temp dirs for tar extraction | Use `tempfile.mkdtemp()` + try/finally cleanup |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| magic-pdf[full] | mineru (2.0.4) | `mineru` is the new REST-based repackage; `magic-pdf` is the direct Python API — use `magic-pdf` for in-process Celery integration |
| httpx sync client | requests | Both work; httpx is already a dependency, shares connection pool |
| lxml XPath for TEI | `grobid-tei-xml` PyPI | `grobid-tei-xml` is cleaner but adds a dependency; lxml already present and sufficient |

**Installation additions needed:**

```bash
# In Dockerfile (MUST add before pip install):
RUN apt-get update && apt-get install -y --no-install-recommends \
    tralics \
    texlive-extra-utils \
    && rm -rf /var/lib/apt/lists/*

# In pyproject.toml dependencies:
"magic-pdf[full]>=1.3.12",
"PyMuPDF>=1.27.0",
"s2orc-doc2json @ git+https://github.com/allenai/s2orc-doc2json@71c022ed4bed3ffc71d22c2ac5cdbc133ad04e3c",
```

**Version verification (run before locking):**

```bash
pip show magic-pdf | grep Version   # expect 1.3.12
pip show PyMuPDF | grep Version     # expect 1.27.x
```

**Tralics availability warning:** Tralics was removed from Debian testing in January 2022 and re-added to unstable in August 2023. Availability in `python:3.11-slim` (Debian bookworm base) should be verified during plan 03-01 implementation. If `apt install tralics` fails, the fallback is to compile from source or use an older Debian backport. This is HIGH risk for plan 03-01.

---

## Architecture Patterns

### Recommended Project Structure

No new directories needed — all code goes into existing `app/tasks/parse.py` plus a new helper module:

```
app/
├── tasks/
│   ├── parse.py          # 4 Celery tasks (replace stubs)
│   └── router.py         # NEW: smart router + batch dispatcher (03-04)
├── parsers/
│   └── grobid.py         # NEW: GROBID httpx client (used by router chain)
```

### Pattern 1: TEX2JSON via process_tex_stream

**What:** `process_tex_stream(fname, stream)` takes the filename and raw bytes of a `.tar.gz`/`.gz` file, writes to temp, calls `process_tex_file`, and returns the S2ORC JSON dict.

**When to use:** `paper_sources.source_type == 'arxiv_tar'` (or similar asset type for tar archives).

```python
# Source: https://raw.githubusercontent.com/allenai/s2orc-doc2json/main/doc2json/tex2json/process_tex.py
from doc2json.tex2json.process_tex import process_tex_stream

def _run_tex2json(asset_path: str, temp_dir: str) -> dict | None:
    with open(asset_path, "rb") as f:
        raw = f.read()
    fname = os.path.basename(asset_path)  # e.g. "2401.12345.tar.gz"
    result = process_tex_stream(fname, raw, temp_dir=temp_dir)
    # Returns dict on success, [] on failure (check type)
    if isinstance(result, dict) and result:
        return result
    return None
```

**Critical note:** `process_tex_stream` returns `[]` (empty list) if `process_tex_file` produces no output file. Check `isinstance(result, dict)` before using.

**TEX file detection inside tar:** `process_tex_stream` handles the extraction and heuristic detection internally using `doc2json/tex2json/tex_to_xml.py`. The `\documentclass` heuristic in CONTEXT.md (D-01, D-02) aligns with what s2orc-doc2json already does — no need to re-implement detection; trust the library. However, the filename-arXiv-ID match (D-01) may NOT be in the library — verify during implementation.

### Pattern 2: JATS2JSON via process_jats_stream

**What:** `process_jats_stream(fname, stream)` — same pattern as tex stream. Calls `process_jats_file` internally, reads JSON from output file, returns dict.

**When to use:** `paper_sources.source_type == 'pmc_jats'` or similar.

```python
# Source: inferred from process_jats_file source code (same pattern as tex)
from doc2json.jats2json.process_jats import process_jats_stream

def _run_jats2json(asset_path: str, temp_dir: str) -> dict | None:
    with open(asset_path, "rb") as f:
        raw = f.read()
    fname = os.path.basename(asset_path)
    result = process_jats_stream(fname, raw, temp_dir=temp_dir)
    if isinstance(result, dict) and result:
        return result
    return None
```

**JATS DOCTYPE normalization:** s2orc-doc2json does NOT perform NLM 2.x DTD normalization internally — it uses BeautifulSoup with lxml and relies on the XML being well-formed. For old NLM 2.x files, the `<!DOCTYPE>` declaration may reference a DTD URL that causes lxml to attempt an external network fetch and fail. **The normalization step must strip or replace the DOCTYPE declaration before passing to process_jats_stream.** Use a regex replace on the raw bytes before writing:

```python
import re

def _strip_doctype(raw: bytes) -> bytes:
    # Remove DOCTYPE declaration to prevent lxml external DTD fetch
    return re.sub(rb'<!DOCTYPE[^>]*>', b'', raw, count=1)
```

Detection: Check `raw[:500]` for `b'NLM//DTD Journal Archiving'` (NLM 2.x) vs `b'NLM//DTD JATS'` (JATS 1.x).

### Pattern 3: MinerU via PymuDocDataset (magic-pdf 1.x)

**What:** In-process GPU-based PDF parsing. Classifies as OCR or text-based, then routes to `pipe_ocr_mode` or `pipe_txt_mode`. Output is `content_list.json` — a flat list of dicts with `type`, `text`, `text_level`, `bbox`, `page_idx`.

**When to use:** `paper_sources.source_type == 'arxiv_pdf'` (PDF-only papers), after pymupdf pre-check passes.

```python
# Source: https://github.com/opendatalab/MinerU/issues/1584 (verified against 1.x API)
import os
from magic_pdf.data.data_reader_writer import FileBasedDataWriter, FileBasedDataReader
from magic_pdf.data.dataset import PymuDocDataset
from magic_pdf.model.doc_analyze_by_custom_model import doc_analyze
from magic_pdf.config.enums import SupportedPdfParseMethod
import json

def _run_mineru(asset_path: str, output_dir: str) -> list | None:
    image_dir = os.path.join(output_dir, "images")
    os.makedirs(image_dir, exist_ok=True)

    image_writer = FileBasedDataWriter(image_dir)
    output_writer = FileBasedDataWriter(output_dir)
    reader = FileBasedDataReader("")
    pdf_bytes = reader.read(asset_path)

    ds = PymuDocDataset(pdf_bytes)
    if ds.classify() == SupportedPdfParseMethod.OCR:
        infer_result = ds.apply(doc_analyze, ocr=True)
        pipe_result = infer_result.pipe_ocr_mode(image_writer)
    else:
        infer_result = ds.apply(doc_analyze, ocr=False)
        pipe_result = infer_result.pipe_txt_mode(image_writer)

    pipe_result.dump_content_list(output_writer, "content_list.json", "images")
    content_list_path = os.path.join(output_dir, "content_list.json")
    with open(content_list_path) as f:
        return json.load(f)
```

**CRITICAL known issue:** In magic-pdf open-source releases, `text_level` is ALWAYS 1 for all text blocks — heading detection does not work in the OSS version (only works on HuggingFace hosted demo). This means Phase 4 hierarchy reconstruction cannot use `text_level` from MinerU output. Phase 4 must use other signals (font size in `bbox`, block ordering, explicit markers). Document this for Phase 4 planner.

**GPU config:** MinerU reads `~/magic-pdf.json` for `device-mode`. In the Docker container this is `/root/magic-pdf.json`. The Dockerfile must either: (a) copy a pre-written `magic-pdf.json` with `{"device-mode": "cuda"}` into the container, or (b) the entrypoint script creates it on first run. Option (a) is simpler.

### Pattern 4: pymupdf Text Layer Pre-check

**What:** Before routing to MinerU, check if the PDF has a meaningful text layer. Scanned PDFs return minimal text from `get_text()`.

```python
# Source: pymupdf official docs, scanned PDF detection pattern
import pymupdf  # or: import fitz as pymupdf

def _has_text_layer(asset_path: str, threshold: int = 100) -> bool:
    """Return True if PDF has a meaningful text layer (not scanned)."""
    doc = pymupdf.open(asset_path)
    total_text = "".join(page.get_text() for page in doc)
    doc.close()
    return len(total_text.strip()) >= threshold
```

Threshold of 100 characters per ROADMAP success criteria: "scanned PDFs (text layer < 100 characters)". Scanned PDFs that fail this check get `parse_status=scanned_skip`.

**Table count for GROBID vs MinerU routing (D-03):** When no `\documentclass` is found in any `.tex` file, inspect the associated PDF. pymupdf page analysis can estimate table count by counting blocks or using heuristic bounding-box patterns, but this is imprecise. Recommended approach for D-03 threshold: use a word-count proxy instead — papers with short avg sentence length (≤3 words/sentence in extracted text) are likely heavily formatted (tables/equations); this is simpler than true table detection. Alternatively, use MinerU's own classify result as the gate. The exact heuristic is Claude's discretion per CONTEXT.md.

### Pattern 5: GROBID Reference Extraction

**What:** POST the paper's PDF to GROBID `/api/processReferences`, parse TEI XML response, extract `<biblStruct>` entries.

**Request format:** `multipart/form-data` with field `input` = PDF file bytes. Optional `includeRawCitations=1`.

```python
# Source: GROBID REST API docs (https://grobid.readthedocs.io/en/latest/Grobid-service/)
import httpx
from lxml import etree

GROBID_URL = "http://grobid:8070"  # Docker internal hostname from docker-compose.yml
TEI_NS = "http://www.tei-c.org/ns/1.0"

def _call_grobid_references(pdf_path: str, timeout: int = 30) -> list[dict]:
    """Returns list of citation dicts or [] on failure."""
    try:
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                f"{GROBID_URL}/api/processReferences",
                files={"input": ("paper.pdf", pdf_bytes, "application/pdf")},
                data={"includeRawCitations": "1"},
            )
        if resp.status_code != 200:
            return []
        return _parse_tei_references(resp.content)
    except Exception:
        return []  # Non-blocking: GROBID failure never fails the chain

def _parse_tei_references(tei_xml: bytes) -> list[dict]:
    root = etree.fromstring(tei_xml)
    citations = []
    for bibl in root.iter(f"{{{TEI_NS}}}biblStruct"):
        analytic = bibl.find(f"{{{TEI_NS}}}analytic")
        monogr = bibl.find(f"{{{TEI_NS}}}monogr")
        title_el = analytic.find(f"{{{TEI_NS}}}title") if analytic else None
        title = title_el.text if title_el is not None else None
        # Authors
        authors = []
        for author in (analytic or monogr or bibl).findall(f".//{{{TEI_NS}}}persName"):
            forename = author.findtext(f"{{{TEI_NS}}}forename", default="")
            surname = author.findtext(f"{{{TEI_NS}}}surname", default="")
            authors.append(f"{forename} {surname}".strip())
        # Year
        date = bibl.find(f".//{{{TEI_NS}}}date[@type='published']")
        year = date.get("when", "")[:4] if date is not None else None
        # DOI
        doi_el = bibl.find(f".//{{{TEI_NS}}}idno[@type='DOI']")
        doi = doi_el.text if doi_el is not None else None
        # Raw text
        raw_el = bibl.find(f"{{{TEI_NS}}}note[@type='raw_reference']")
        raw_text = raw_el.text if raw_el is not None else None
        citations.append({
            "title": title, "authors": authors,
            "year": int(year) if year and year.isdigit() else None,
            "doi": doi, "raw_text": raw_text,
        })
    return citations
```

### Pattern 6: Celery Chain and Group (Router — 03-04)

**What:** Smart router reads all `parse_status=pending` `paper_sources` rows, groups by asset type, dispatches chains and a `celery.group` for fan-out.

```python
# Source: Celery 5.4 canvas docs
from celery import chain, group

def dispatch_parse_batch():
    """Fan-out all pending papers in parallel."""
    from app.db import SessionLocal
    from app.models import PaperSource
    session = SessionLocal()
    try:
        pending = session.query(PaperSource).filter(
            PaperSource.parse_status == "pending"
        ).all()
    finally:
        session.close()

    latex_ids = [ps.canonical_id for ps in pending if ps.source_type == "arxiv_tar"]
    jats_ids  = [ps.canonical_id for ps in pending if ps.source_type == "pmc_jats"]
    pdf_ids   = [ps.canonical_id for ps in pending if ps.source_type == "arxiv_pdf"]

    # Chains: parse → grobid_refs → store (Phase 4 task)
    latex_tasks = [
        chain(
            parse_latex.si(str(cid)).set(queue="fast"),
            extract_grobid_refs.si(str(cid)).set(queue="fast"),
        )
        for cid in latex_ids
    ]
    pdf_tasks = [
        chain(
            parse_pdf_mineru.si(str(cid)).set(queue="slow"),
            extract_grobid_refs.si(str(cid)).set(queue="fast"),
        )
        for cid in pdf_ids
    ]

    # Dispatch as group (all tasks in parallel, queue-limited by worker concurrency)
    all_tasks = latex_tasks + jats_tasks + pdf_tasks
    if all_tasks:
        group(all_tasks).apply_async()
```

**Queue routing note:** `parse_latex` and `parse_jats` are already routed to `fast` queue by `task_routes` in `celery_app.py`. `parse_pdf_mineru` and `parse_pdf_grobid` route to `slow`. The `.set(queue=...)` in the chain is redundant for named tasks but explicit is better for clarity.

**Chain result passing:** When using `chain(taskA.si(...), taskB.si(...))`, the `si` (immutable signature) means taskB does NOT receive taskA's return value. Since 03-04 calls `extract_grobid_refs` separately (not as a callback of parse), using `.si()` for both is correct. Each task reads/writes DB state independently.

### Anti-Patterns to Avoid

- **Importing magic-pdf at module level:** `from magic_pdf.data.dataset import PymuDocDataset` at the top of `parse.py` will cause ImportError for all workers that don't have magic-pdf installed (fast workers). Use lazy import inside `parse_pdf_mineru` function body (same pattern as `ingest.py` lazy import of `pmc_oai`).
- **Using `chain(taskA.s(), taskB.s())` with mutable signatures across queues:** When task results are large dicts, passing through the chain serializes them via Redis. Use `.si()` (immutable) for parse→grobid→store chains where each task reads its own state from DB rather than receiving the prior task's full output.
- **Not cleaning temp dirs:** `process_tex_stream` writes to `temp_dir`. Use `tempfile.mkdtemp()` + `shutil.rmtree(temp_dir, ignore_errors=True)` in a `finally` block to avoid disk fill-up during 10k batch.
- **Calling GROBID with TEI XML input for processReferences:** This endpoint takes a PDF, NOT TEI XML. The s2orc-doc2json `grobid2json` path uses GROBID differently (full PDF parse). Phase 3 uses `/api/processReferences` which takes PDF bytes.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| LaTeX-to-structured-JSON conversion | Custom regex/AST parser | `process_tex_stream` from s2orc-doc2json | Handles `\input`, `\bibliography`, macro expansion via latexpand + tralics |
| JATS XML parsing | Custom XML walker | `process_jats_stream` from s2orc-doc2json | Handles FIGREF/TABREF/BIBREF normalization, figure/table extraction |
| PDF text extraction | Custom PDF reader | PyMuPDF `page.get_text()` | Handles encoding, multi-column, embedded fonts |
| ML PDF layout analysis | Custom model | MinerU `PymuDocDataset` + `doc_analyze` | Trained layout detection model; not replicable in project scope |
| TEI XML parsing | Custom XML parser | `lxml.etree` with XPath | Handles TEI namespaces correctly; regex on XML is fragile |
| Task fan-out for 10k batch | Sequential dispatch loop | `celery.group(tasks).apply_async()` | Groups saturate all available workers; loop would serialize dispatch |

**Key insight:** The parsers (s2orc-doc2json, MinerU) are the entire hard work of Phase 3 — all custom code is glue: reading files, calling library APIs, checking results, updating DB status.

---

## Common Pitfalls

### Pitfall 1: tralics System Binary Missing
**What goes wrong:** `process_tex_stream` calls `subprocess(['tralics', ...])` which raises `FileNotFoundError: [Errno 2] No such file or directory: 'tralics'` — this silently returns `[]` from the function, making all TEX2JSON calls appear to "fail" without a clear error.
**Why it happens:** `python:3.11-slim` Dockerfile has no system binaries; `tralics` is not a Python package.
**How to avoid:** Add `apt install tralics texlive-extra-utils` to Dockerfile in plan 03-01. Verify with `docker run ... tralics --version`.
**Warning signs:** All TEX2JSON tasks return `{"status": "failed"}` with no exception traceback; `process_tex_stream` returns `[]`.

### Pitfall 2: tralics Debian Package Availability
**What goes wrong:** `apt install tralics` may fail on Debian bookworm (the base of `python:3.11-slim`) because tralics was removed from Debian testing in January 2022 and re-added to unstable in August 2023.
**Why it happens:** Package availability varies by Debian release; unstable packages don't flow to stable automatically.
**How to avoid:** During plan 03-01, test `apt install tralics` in the container. If unavailable, options: (a) add `deb http://deb.debian.org/debian sid main` to sources for tralics only, (b) compile from source in Dockerfile, (c) use `apt install tralics` from bookworm-backports if available.
**Warning signs:** `E: Unable to locate package tralics` during `docker build`.

### Pitfall 3: magic-pdf Imports at Module Level
**What goes wrong:** `from magic_pdf.data.dataset import PymuDocDataset` at top of `parse.py` causes ImportError on fast-queue workers that don't have `magic-pdf[full]` or its GPU dependencies.
**Why it happens:** All workers load `parse.py` at startup; magic-pdf has heavy dependencies (torch, detectron2).
**How to avoid:** Lazy import inside `parse_pdf_mineru` function body only. Follow the pattern in `ingest.py` for lazy imports.
**Warning signs:** All Celery workers fail to start; `ImportError: No module named 'magic_pdf'`.

### Pitfall 4: MinerU magic-pdf.json Config Missing in Container
**What goes wrong:** MinerU raises `FileNotFoundError` or uses CPU mode silently when `~/magic-pdf.json` doesn't exist in the container.
**Why it happens:** magic-pdf looks for `~/.magic-pdf.json` (or `/root/magic-pdf.json` in Docker) and falls back to CPU if not found.
**How to avoid:** Either `COPY magic-pdf.json /root/magic-pdf.json` in Dockerfile, or create it via `RUN echo '{"device-mode":"cuda","models-dir":"/models"}' > /root/magic-pdf.json`.
**Warning signs:** MinerU runs without error but output is low quality; GPU utilization is 0% during MinerU tasks.

### Pitfall 5: MinerU text_level Always 1 in OSS Build
**What goes wrong:** Phase 4 normalizer uses `text_level` from MinerU `content_list.json` to identify section headings — finds everything is body text (`text_level=1`), no hierarchy.
**Why it happens:** Heading detection in magic-pdf OSS is disabled/broken in v1.3.x; only the HuggingFace hosted version works.
**How to avoid:** Phase 4 must NOT rely on `text_level` from MinerU output. Document this in Phase 3 task return metadata so Phase 4 planner is warned.
**Warning signs:** All MinerU output sections have `"text_level": 1`; no headings detected.

### Pitfall 6: JATS DOCTYPE Causing lxml Network Fetch
**What goes wrong:** Old NLM 2.x JATS files have `<!DOCTYPE article PUBLIC "-//NLM//DTD Journal Archiving..." "http://dtd.nlm.nih.gov/...">`. lxml attempts to fetch this URL; in an air-gapped Docker container with no internet, this hangs for 30+ seconds then raises an error.
**Why it happens:** lxml's XML parser follows `SYSTEM` DTD URLs by default.
**How to avoid:** Strip or replace the `<!DOCTYPE ...>` declaration from raw bytes before passing to `process_jats_stream`. Use `re.sub(rb'<!DOCTYPE[^>]*>', b'', raw, count=1)`. Detection: check for `b'NLM//DTD Journal Archiving'` in first 500 bytes.
**Warning signs:** JATS tasks hang for 30+ seconds then fail; lxml timeout errors in logs.

### Pitfall 7: Celery Chain With Mutable Signatures Passing Large Dicts
**What goes wrong:** Using `chain(parse_latex.s(cid), extract_grobid.s(cid))` with `.s()` (mutable) means `extract_grobid` receives the full S2ORC JSON dict as its first argument from `parse_latex`. S2ORC JSON for a full paper can be 500KB–2MB. With 10k papers this serializes TBs through Redis.
**Why it happens:** Mutable signatures pass return values forward in a chain.
**How to avoid:** Use `.si()` (immutable) signatures throughout the parse→grobid chain. Each task reads its own input from `paper_sources` via `canonical_id`. Return value is only status dicts.
**Warning signs:** Redis memory grows rapidly during batch; chain tasks receive unexpected large positional args.

### Pitfall 8: GROBID processReferences Takes PDF, Not TEI XML
**What goes wrong:** Sending TEI XML (or S2ORC JSON) to `/api/processReferences` instead of the original PDF bytes. Returns 415 or empty result.
**Why it happens:** Confusion between GROBID's primary parse endpoints (which accept PDF) and what the references endpoint expects.
**How to avoid:** Always send the original PDF file from `paper_sources.asset_path` to GROBID, not any intermediate output. GROBID re-extracts references directly from the PDF.

---

## S2ORC JSON Output Structure (Phase 4 Reference)

The dict returned by `process_tex_stream` and `process_jats_stream` has this top-level shape (from `doc2json/s2orc.py`):

```json
{
  "paper_id": "string",
  "pdf_hash": "string",
  "metadata": {
    "title": "string",
    "authors": [...],
    "year": 2024,
    "venue": "string",
    "doi": "string"
  },
  "abstract": [
    {
      "text": "...",
      "cite_spans": [...],
      "ref_spans": [...],
      "eq_spans": [...],
      "section": "Abstract",
      "sec_num": null
    }
  ],
  "body_text": [
    {
      "text": "...",
      "cite_spans": [...],
      "ref_spans": [...],
      "eq_spans": [...],
      "section": "Introduction",
      "sec_num": "1"
    }
  ],
  "back_matter": [...],
  "bib_entries": {
    "BIBREF0": {
      "ref_id": "BIBREF0",
      "title": "...",
      "authors": [...],
      "year": 2023,
      "venue": "...",
      "raw_text": "..."
    }
  },
  "ref_entries": {
    "FIGREF0": {"text": "Figure caption", "type_str": "figure"},
    "TABREF0": {"text": "Table caption", "type_str": "table", "content": "..."}
  }
}
```

**Key:** `body_text` is a FLAT list of paragraph-level dicts; section hierarchy must be reconstructed from `sec_num` strings (`"1"`, `"1.1"`, `"1.1.2"`) in Phase 4.

## MinerU content_list.json Output Structure

Flat list of content blocks:

```json
[
  {"type": "text", "text": "Introduction", "text_level": 1, "bbox": [...], "page_idx": 0},
  {"type": "text", "text": "In this paper...", "text_level": 1, "bbox": [...], "page_idx": 0},
  {"type": "table", "table_body": "...", "table_caption": "Table 1: ...", "page_idx": 1},
  {"type": "image", "img_path": "images/0.png", "img_caption": "Figure 1: ...", "page_idx": 2}
]
```

**Note:** `text_level` is always 1 in OSS release — do NOT use for heading detection. Phase 4 must use other heuristics (e.g., short text blocks with all-caps or sentence-end patterns as heading signals).

---

## Code Examples

### Post-parse backslash-token check (PARSE-01)

```python
# Source: REQUIREMENTS.md PARSE-01 — >2% raw backslash tokens → degraded
import re

def _check_backslash_ratio(s2orc_dict: dict) -> str:
    """Returns 'degraded' if >2% of tokens are raw backslash commands."""
    all_text = " ".join(
        p["text"] for p in s2orc_dict.get("body_text", [])
    )
    tokens = all_text.split()
    if not tokens:
        return "ok"
    backslash_tokens = sum(1 for t in tokens if t.startswith("\\"))
    ratio = backslash_tokens / len(tokens)
    return "degraded" if ratio > 0.02 else "ok"
```

### Average sentence length check (PARSE-05)

```python
# Source: REQUIREMENTS.md PARSE-05 — avg sentence length >80 tokens → multi-column degradation
import re

def _check_sentence_length(content_list: list) -> str:
    """Returns 'degraded' if avg sentence length >80 tokens (multi-column interleaving)."""
    texts = [b["text"] for b in content_list if b.get("type") == "text"]
    all_text = " ".join(texts)
    sentences = re.split(r'[.!?]+', all_text)
    sentences = [s.split() for s in sentences if s.strip()]
    if not sentences:
        return "ok"
    avg_len = sum(len(s) for s in sentences) / len(sentences)
    return "degraded" if avg_len > 80 else "ok"
```

### DB session update pattern (from ingest.py)

```python
# Source: app/tasks/ingest.py — established pattern for DB updates in Celery tasks
from app.db import SessionLocal
from app.models import PaperSource

def _update_parse_status(canonical_id: str, status: str, parse_source: str):
    session = SessionLocal()
    try:
        ps = session.query(PaperSource).filter(
            PaperSource.canonical_id == canonical_id
        ).first()
        if ps:
            ps.parse_status = status
            session.commit()
    finally:
        session.close()
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| grobid2json (s2orc-doc2json primary) | TEX2JSON + JATS2JSON as primary parsers, GROBID only for references | 2021 | Better structure preservation from source |
| magic-pdf 0.x (UNIPipe/TXTPipe pattern) | magic-pdf 1.x (PymuDocDataset + InferenceResult pattern) | 2024 v1.0 | API changed substantially; old `pipe_classify()` + `pipe_parse()` pattern no longer the primary interface |
| Nougat for scanned PDFs | MinerU with OCR mode via PaddleOCR | 2024 | MinerU has GPU OCR; Nougat is out of scope per REQUIREMENTS.md |

**Deprecated patterns:**
- `UNIPipe/TXTPipe/OCRPipe` from magic-pdf 0.x — replaced by `PymuDocDataset` in 1.x; the old `pipe_classify()` + `pipe_parse()` + `pipe_mk_uni_format()` pattern may still work in 1.x but is not the documented primary API
- `process_pdf_stream` from s2orc-doc2json — this calls GROBID to do a full PDF parse; Phase 3 does NOT use this path (GROBID is reference-only per D-07)

---

## Open Questions

1. **tralics availability in python:3.11-slim (Debian bookworm)**
   - What we know: tralics was removed from Debian testing Jan 2022, re-added to unstable Aug 2023
   - What's unclear: whether `apt install tralics` works in bookworm during `docker build`
   - Recommendation: Plan 03-01 first action should be `docker run python:3.11-slim apt-cache show tralics`; if missing, add unstable repo for tralics only or compile from source

2. **Does process_tex_stream implement the filename-arXiv-ID match (D-01) or does Phase 3 need to implement it?**
   - What we know: `process_tex_stream` passes the gz file to `process_tex_file` which calls `tex_to_xml.py`; the extraction logic in `tex_to_xml.py` selects a main tex file internally
   - What's unclear: whether the library's selection heuristic matches D-01 (filename-arXiv-ID) or uses only `\documentclass` largest-file fallback
   - Recommendation: Inspect `doc2json/tex2json/tex_to_xml.py` extraction code during plan 03-01 implementation; if library doesn't do ID match, do it as a pre-processing step before calling `process_tex_stream`

3. **magic-pdf model download — where are models stored in Docker container?**
   - What we know: magic-pdf requires pre-downloaded model weights; the `magic-pdf.json` config has a `models-dir` key
   - What's unclear: whether model weights need to be pre-baked into the image or downloaded at container start (which adds 2–5 GB startup time)
   - Recommendation: Pre-bake models into a separate `worker-gpu` image stage, or mount a pre-downloaded `/models` volume via docker-compose

4. **process_jats_stream function existence**
   - What we know: `process_jats_file` definitely exists; `process_tex_stream` definitely exists; the jats equivalent is inferred from the parallel structure
   - What's unclear: whether `process_jats_stream` exists as a public function or must be implemented manually (write jats bytes to temp file, call `process_jats_file`, read result)
   - Recommendation: Check the jats module's `__init__.py` or `app.py` imports during plan 03-02 to verify; if missing, the manual pattern (write → call → read) is 5 lines of code

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (present in `[project.optional-dependencies] dev`) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` with `testpaths = ["tests"]` |
| Quick run command | `pytest tests/test_parse.py -x -q` |
| Full suite command | `pytest tests/ -x -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PARSE-01 | TEX2JSON produces S2ORC JSON with non-empty body_text | integration | `pytest tests/test_parse.py::test_parse_latex_returns_s2orc -x` | Wave 0 |
| PARSE-01 | Backslash ratio >2% sets parse_quality=degraded | unit | `pytest tests/test_parse.py::test_backslash_ratio_check -x` | Wave 0 |
| PARSE-02 | JATS2JSON produces S2ORC JSON from PMC JATS XML | integration | `pytest tests/test_parse.py::test_parse_jats_returns_s2orc -x` | Wave 0 |
| PARSE-02 | NLM 2.x DOCTYPE stripped before parse | unit | `pytest tests/test_parse.py::test_strip_doctype -x` | Wave 0 |
| PARSE-03 | pymupdf text-layer check flags scanned PDF | unit | `pytest tests/test_parse.py::test_scanned_pdf_detection -x` | Wave 0 |
| PARSE-03 | MinerU returns content_list with text blocks | integration (GPU required) | `pytest tests/test_parse.py::test_mineru_pdf -x -m gpu` | Wave 0 |
| PARSE-04 | GROBID call returns citation list or [] on failure | unit (mock httpx) | `pytest tests/test_parse.py::test_grobid_references -x` | Wave 0 |
| PARSE-05 | Router selects correct parser for each source_type | unit (mock tasks) | `pytest tests/test_parse.py::test_router_dispatch -x` | Wave 0 |
| PARSE-05 | Avg sentence length >80 sets parse_quality=degraded | unit | `pytest tests/test_parse.py::test_sentence_length_check -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_parse.py -x -q -m "not gpu"`
- **Per wave merge:** `pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_parse.py` — all PARSE-* test cases; needs fixture PDFs and sample JATS/tar.gz files
- [ ] `tests/fixtures/sample_arxiv.tar.gz` — minimal 1-page arXiv LaTeX paper for integration test
- [ ] `tests/fixtures/sample_pmc.xml` — minimal PMC JATS XML with NLM 2.x DOCTYPE
- [ ] `tests/fixtures/sample_scanned.pdf` — image-only PDF with no text layer
- [ ] GPU integration tests marked with `@pytest.mark.gpu` — skip on CI; run only on GPU worker

---

## Sources

### Primary (HIGH confidence)
- `https://raw.githubusercontent.com/allenai/s2orc-doc2json/main/doc2json/tex2json/process_tex.py` — `process_tex_stream` function signature and return value confirmed
- `https://raw.githubusercontent.com/allenai/s2orc-doc2json/main/doc2json/utils/latex_util.py` — `tralics` and `latexpand` subprocess calls confirmed
- `https://raw.githubusercontent.com/allenai/s2orc-doc2json/main/doc2json/jats2json/process_jats.py` — `process_jats_file` confirmed; stream function inferred from same pattern
- `https://github.com/allenai/s2orc-doc2json/blob/main/doc2json/s2orc.py` — S2ORC JSON output structure confirmed (paper_id, metadata, abstract, body_text, back_matter, bib_entries, ref_entries)
- `https://github.com/opendatalab/MinerU/issues/1584` — magic-pdf 1.x `PymuDocDataset` + `pipe_txt_mode`/`pipe_ocr_mode` API confirmed with working code example
- `app/tasks/ingest.py` — DB session pattern (SessionLocal, query → update → commit → close)
- `app/celery_app.py` — queue routing config: latex/jats → fast, mineru/grobid → slow
- `docker-compose.yml` — GROBID at `http://grobid:8070`; worker has `fast,slow` queues

### Secondary (MEDIUM confidence)
- PyPI `magic-pdf 1.3.12` — verified current version (May 2025)
- PyPI `PyMuPDF 1.27.x` — verified current version
- `git ls-remote` — s2orc-doc2json HEAD SHA `71c022ed4bed3ffc71d22c2ac5cdbc133ad04e3c` confirmed live
- GROBID docs search results — `/api/processReferences` multipart/form-data POST with `input` field; TEI XML response with `listBibl/biblStruct` structure

### Tertiary (LOW confidence — flag for validation)
- tralics Debian availability in bookworm — conflicting signals; was removed from testing, re-added to unstable; actual availability needs runtime verification
- MinerU `dump_content_list` method name — inferred from pattern; `pipe_mk_uni_format` confirmed for 0.x; 1.x method may differ
- process_jats_stream existence — inferred from parallel tex stream pattern; needs verification during plan 03-02

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — versions verified against PyPI; s2orc-doc2json SHA verified against live git
- Architecture patterns: MEDIUM-HIGH — core API calls verified against source code; tralics subprocess calls confirmed; MinerU 1.x API from issue tracker example (not official docs)
- Common pitfalls: HIGH — tralics availability confirmed as a real risk from Debian package tracker; text_level bug confirmed from issue tracker
- GROBID integration: MEDIUM — REST format confirmed from docs; TEI XML parsing pattern is standard lxml usage
- Celery patterns: HIGH — standard Celery 5.4 canvas (.si(), chain, group) confirmed

**Research date:** 2026-04-15
**Valid until:** 2026-05-15 (magic-pdf releases frequently; re-verify if >2 weeks pass)
