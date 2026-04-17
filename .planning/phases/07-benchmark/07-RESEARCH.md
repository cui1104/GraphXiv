# Phase 7: Benchmark - Research

**Researched:** 2026-04-17
**Domain:** PDF parser benchmarking — Docling, GROBID full-text, MinerU, Claude vision GT
**Confidence:** HIGH (all key APIs verified against official sources)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** 150 papers on local Mac CPU. No VM or GPU.
- **D-02:** Self-contained `benchmark/` directory at project root.
- **D-03:** Four Python scripts: `select_sample.py`, `create_gt.py`, `run_benchmark.py`, `analyze_results.py`; plus `benchmark/results/benchmark.csv`, `benchmark/FINDINGS.md`, `benchmark/notebook/analysis.ipynb`.
- **D-04:** Stratified sample: arXiv/PMC ratio from DB; cs.LG/cs.AI/cs.CV/cs.CL/stat.ML proportional.
- **D-05:** Two-column detection: `parse_quality` degradation flags first, then PyMuPDF column-layout heuristic.
- **D-06:** Papers pulled from DB (already-parsed preferred); raw assets supplement if needed.
- **D-07:** Exactly 150 papers; ≥30 two-column IEEE/ACM format. Selection script aborts if corpus can't satisfy.
- **D-08:** Ground truth via Claude Opus vision API (`claude-opus-4-6`) for ALL 150 papers.
- **D-09:** `create_gt.py` renders each PDF page as image (PyMuPDF), sends to Claude Opus, stores JSON `{paper_id: [heading1, ...]}` in `benchmark/gt/`.
- **D-10:** Heading match: fuzzy token overlap ≥ 80%; normalize (lowercase, strip punctuation) before compare.
- **D-11:** Coherence: `_sentence_length_degraded()` (avg sentence > 80 tokens) AND non-ASCII/symbol ratio > 5% = garbled. Both must pass.
- **D-12:** Docling added to existing Docker image (CPU-only). Add `docling` to `pyproject.toml` extras or new `requirements-benchmark.txt`.
- **D-13:** Docling runs via Python API (`DocumentConverter`) in benchmark scripts.
- **D-14:** GROBID standalone uses existing GROBID Docker service.
- **D-15:** GROBID standalone calls `/api/processFulltextDocument`. New `extract_fulltext_document()` in `app/parsers/grobid.py` — **NOTE: `extract_fulltext()` already exists in `app/parsers/grobid.py` (added Phase 4). Benchmark uses it directly — no new function needed.**
- **D-16:** GROBID section extraction: parse `<div>` with `<head>` children from `<body>` element in TEI XML — **already implemented in `_parse_tei_fulltext_sections()` in `app/parsers/grobid.py`.**
- **D-17:** CSV columns: `paper_id`, `arxiv_id`, `source_type`, `column_layout`, `subject`, `condition`, `heading_count_gt`, `heading_count_parser`, `heading_match_rate`, `coherent_section_pct`, `table_presence`, `table_structural_completeness`, `error`.
- **D-18:** One row per (paper, condition) — 600 rows total.
- **D-19:** Table completeness: 1.0 = caption + headers + ≥1 data row; 0.5 = caption only; 0.0 = absent/empty.
- **D-20:** `FINDINGS.md` — methodology, sample composition, four-column comparison table, multi-column characterization, recommendation.
- **D-21:** `analysis.ipynb` — matplotlib bar charts (heading match, coherence), scatter (table quality), box plots.

### Claude's Discretion
- Exact PyPI version of Docling to install
- Dockerfile placement of docling dependency
- Exact Opus prompt for GT extraction
- Retry/timeout handling for Claude Opus API calls in `create_gt.py`
- How to handle papers where a parser crashes (record as error row, continue)

### Deferred Ideas (OUT OF SCOPE)
- Running benchmark on full 10,000-paper corpus (requires GPU VM)
- Nougat as fifth condition
- Automated benchmark re-runs as CI checks
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| BENCH-01 | Four conditions (MinerU standalone, GROBID standalone, Docling standalone, Router) on exactly 150 DL papers including ≥30 two-column; none crash | Docling API verified; GROBID `extract_fulltext()` already exists; MinerU pattern from `parse_pdf_mineru`; Router condition reuses pipeline |
| BENCH-02 | Section extraction accuracy (heading match rate, coherent body %) and table extraction quality (presence rate, structural completeness) for all four conditions; output to CSV | Fuzzy match algorithm research; `_sentence_length_degraded` reuse confirmed; Docling table API confirmed; CSV schema locked in D-17 |
| BENCH-03 | Findings report with four-column comparison table, sample methodology, multi-column failure characterization, parser recommendation | Standard benchmark report structure researched; notebook with matplotlib confirmed |
</phase_requirements>

---

## Summary

Phase 7 builds a standalone benchmark suite in `benchmark/` that runs four PDF parsers on 150 DL papers and produces a CSV + findings report. The three primary technical challenges are: (1) integrating Docling's CPU-only Python API, (2) calling the Claude Opus vision API to produce ground truth headings, and (3) computing fuzzy heading match rates and coherence scores consistently across conditions.

**Key discovery:** `extract_fulltext()` in `app/parsers/grobid.py` already implements GROBID full-text parsing with TEI XML section extraction (added Phase 4). The GROBID standalone benchmark condition just calls this existing function — no new code needed in the grobid module. Similarly, `_parse_tei_fulltext_sections()` is already implemented and correctly parses `<div>/<head>` elements.

**Ground truth cost:** At $5/MTok input for `claude-opus-4-6`, a typical academic PDF page image costs ~1,568 tokens (≈$0.008). With ~10 pages/paper × 150 papers = 1,500 API calls, total GT cost is approximately **$15–$25** depending on paper length. The Batch API cuts this to ~$8–$12. GT creation should be idempotent and cached.

**Primary recommendation:** Use Docling 2.90.0 with `AcceleratorDevice.CPU` forced. Call `result.document.texts` for `section_header`-labeled items. Call `result.document.tables` and use `export_to_dataframe()` for table presence/completeness scoring.

---

## Standard Stack

### Core (already in pyproject.toml)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `magic-pdf[full]` | ≥1.3.12 | MinerU standalone condition | Already installed; mirrors `parse_pdf_mineru` task |
| `lxml` | 6.0.4 | GROBID TEI XML parsing | Already in project; `_parse_tei_fulltext_sections()` uses it |
| `pymupdf` (fitz) | installed via magic-pdf | PDF page rendering for GT, column detection | Already available; `_has_text_layer()` and `_count_pdf_tables()` use it |
| `anthropic` | latest | Claude Opus GT vision API | New dependency |
| `httpx` | 0.28.1 | GROBID HTTP calls | Already installed |

### New Dependencies
| Library | Version | Purpose | Installation |
|---------|---------|---------|--------------|
| `docling` | 2.90.0 | Docling standalone condition | `pip install "docling>=2.90.0"` |
| `anthropic` | latest | Claude Opus vision API | `pip install anthropic` |
| `pandas` | latest | CSV output, table export | Likely already present via magic-pdf; confirm |
| `matplotlib` | latest | Notebook charts | Add to requirements-benchmark.txt |
| `notebook` / `jupyter` | latest | `analysis.ipynb` | Add to requirements-benchmark.txt |

### Version verified (2026-04-17):
- `docling`: 2.90.0 (released 2026-04-17 per PyPI) — requires Python ≥ 3.10; project uses Python 3.11 — **compatible**
- `claude-opus-4-6` model ID: `claude-opus-4-6` (confirmed via Anthropic models overview)

**Installation (requirements-benchmark.txt):**
```bash
docling>=2.90.0
anthropic>=0.40.0
pandas>=2.0.0
matplotlib>=3.8.0
notebook>=7.0.0
```

**Dockerfile addition** (append after existing pip install line):
```dockerfile
# Benchmark dependencies (CPU-only docling)
RUN pip install --no-cache-dir "docling>=2.90.0" anthropic pandas matplotlib
```

---

## Architecture Patterns

### Recommended Project Structure
```
benchmark/
├── select_sample.py          # stratified 150-paper selection, outputs sample.json
├── create_gt.py              # Claude Opus vision → benchmark/gt/{paper_id}.json
├── run_benchmark.py          # 4 conditions × 150 papers → benchmark/results/benchmark.csv
├── analyze_results.py        # CSV → comparison table + recommendation
├── sample.json               # reproducible paper ID manifest
├── gt/                       # ground truth cache: {paper_id}.json per paper
├── results/
│   └── benchmark.csv         # 600-row output
├── FINDINGS.md               # formal report
└── notebook/
    └── analysis.ipynb        # charts
```

### Pattern 1: Docling CPU-Only Document Conversion
**What:** Force CPU device to avoid GPU dependency; extract section_header items and tables.
**When to use:** Docling standalone condition in `run_benchmark.py`
**Example:**
```python
# Source: https://docling-project.github.io/docling/usage/advanced_options/
# Source: https://github.com/docling-project/docling/issues/2727
from docling.datamodel.base_models import InputFormat
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.datamodel.accelerator_options import AcceleratorOptions, AcceleratorDevice

pipeline_options = PdfPipelineOptions(
    do_table_structure=True,
)
pipeline_options.accelerator_options = AcceleratorOptions(
    device=AcceleratorDevice.CPU
)

converter = DocumentConverter(
    format_options={
        InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
    }
)

result = converter.convert(pdf_path)

# Section headings
headings = [
    item.text
    for item in result.document.texts
    if item.label == "section_header"
]

# Tables
tables = result.document.tables
for table in tables:
    df = table.export_to_dataframe(doc=result.document)
    # df.columns -> header names; len(df) -> row count
```

### Pattern 2: Claude Opus Vision for Ground Truth Extraction
**What:** Render each PDF page as PNG via PyMuPDF, send to Claude with a structured prompt, parse response as JSON list of headings.
**When to use:** `create_gt.py` — one call per paper, cache to `benchmark/gt/{paper_id}.json`
**Example:**
```python
# Source: https://platform.claude.com/docs/en/api/messages-examples
import base64
import anthropic
import pymupdf  # fitz

client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

def extract_gt_headings(pdf_path: str) -> list[str]:
    doc = pymupdf.open(pdf_path)
    # Render first N pages only to control cost
    content_blocks = []
    for page in doc[:10]:  # cap at 10 pages
        pix = page.get_pixmap(dpi=120)  # ~1000px width — keeps under 1568 token limit
        img_bytes = pix.tobytes("png")
        b64 = base64.standard_b64encode(img_bytes).decode("utf-8")
        content_blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": b64,
            }
        })
    content_blocks.append({
        "type": "text",
        "text": (
            "Extract all section headings from this academic paper in order. "
            "Return ONLY a JSON array of strings, e.g. [\"Introduction\", \"Methods\"]. "
            "Include numbered headings without the numbers. "
            "Do not include the paper title. Do not add commentary."
        )
    })
    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": content_blocks}]
    )
    import json
    text = response.content[0].text.strip()
    # Strip markdown fences if present
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)
```

### Pattern 3: Fuzzy Heading Match Rate
**What:** For each parser condition, compare extracted headings against GT list using token overlap ≥ 80%.
**When to use:** `run_benchmark.py` or `analyze_results.py` heading scoring step.
**Example:**
```python
import re
import string

def normalize_heading(h: str) -> set[str]:
    """Lowercase, strip punctuation, return set of tokens."""
    h = h.lower()
    h = h.translate(str.maketrans("", "", string.punctuation))
    return set(h.split())

def heading_matched(parser_heading: str, gt_headings: list[str], threshold: float = 0.8) -> bool:
    """True if any GT heading has token overlap >= threshold with parser_heading."""
    p_tokens = normalize_heading(parser_heading)
    if not p_tokens:
        return False
    for gt in gt_headings:
        g_tokens = normalize_heading(gt)
        if not g_tokens:
            continue
        overlap = len(p_tokens & g_tokens) / max(len(p_tokens), len(g_tokens))
        if overlap >= threshold:
            return True
    return False

def compute_heading_match_rate(parser_headings: list[str], gt_headings: list[str]) -> float:
    """Fraction of GT headings matched by at least one parser heading."""
    if not gt_headings:
        return 0.0
    matched = sum(
        1 for gt in gt_headings
        if heading_matched(gt, parser_headings)  # symmetric: GT vs parser
    )
    return matched / len(gt_headings)
```

### Pattern 4: Coherence Scoring (Reuse parse_helpers)
**What:** Apply both degradation signals to each section's body text; coherence_pct = fraction of sections passing both.
**When to use:** After extracting sections from each condition.
**Example:**
```python
import sys
sys.path.insert(0, "/path/to/project")  # benchmark scripts run from benchmark/
from app.tasks.parse_helpers import _sentence_length_degraded

def _non_ascii_ratio_degraded(text: str, threshold: float = 0.05) -> bool:
    tokens = text.split()
    if not tokens:
        return False
    non_ascii = sum(1 for t in tokens if not t.isascii() or not any(c.isalpha() for c in t))
    return non_ascii / len(tokens) > threshold

def section_is_coherent(text: str) -> bool:
    """True if BOTH signals are within threshold (D-11)."""
    return (
        not _sentence_length_degraded(text, threshold=80)
        and not _non_ascii_ratio_degraded(text, threshold=0.05)
    )

def coherent_section_pct(sections: list[dict]) -> float:
    texts = [s.get("text", "") for s in sections if s.get("text", "").strip()]
    if not texts:
        return 0.0
    return sum(1 for t in texts if section_is_coherent(t)) / len(texts)
```

### Pattern 5: MinerU Standalone (Mirror of parse_pdf_mineru)
**What:** Call `magic-pdf` Python API directly on raw PDF, extract content_list, filter for headings.
**When to use:** MinerU standalone condition. Do NOT use DB-cached content for standalone; re-parse the PDF directly.
**Example:**
```python
# Mirrors app/tasks/parse.py::parse_pdf_mineru — lazy imports mandatory
import json, os, shutil, tempfile

def run_mineru_standalone(pdf_path: str) -> tuple[list[dict], list[dict]]:
    """Returns (sections, tables) from MinerU on raw PDF."""
    from magic_pdf.config.enums import SupportedPdfParseMethod
    from magic_pdf.data.data_reader_writer import FileBasedDataWriter
    from magic_pdf.data.dataset import PymuDocDataset
    from magic_pdf.model.doc_analyze_by_custom_model import doc_analyze

    output_dir = tempfile.mkdtemp(prefix="bench_mineru_")
    try:
        image_dir = os.path.join(output_dir, "images")
        os.makedirs(image_dir, exist_ok=True)
        image_writer = FileBasedDataWriter(image_dir)
        output_writer = FileBasedDataWriter(output_dir)

        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()

        ds = PymuDocDataset(pdf_bytes)
        if ds.classify() == SupportedPdfParseMethod.OCR:
            pipe = ds.apply(doc_analyze, ocr=True).pipe_ocr_mode(image_writer)
        else:
            pipe = ds.apply(doc_analyze, ocr=False).pipe_txt_mode(image_writer)

        pipe.dump_content_list(output_writer, "content_list.json", "images")
        with open(os.path.join(output_dir, "content_list.json")) as f:
            content_list = json.load(f)

        # Extract headings: items with type "title" or level-specific markers
        sections = [
            {"heading": item.get("text", ""), "text": ""}
            for item in content_list
            if item.get("type") in ("title", "text_title")
        ]
        tables = [item for item in content_list if item.get("type") == "table"]
        return sections, tables
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)
```

**MinerU content_list item types for headings:** MinerU uses `type: "title"` for major headings and `type: "text_title"` for numbered section headings in its `content_list` JSON output. The `text_level` field is always 1 in OSS MinerU (noted in `parse_pdf_mineru` comment: `"text_level_broken": True`). Use `type` field for heading detection, not `text_level`.

### Pattern 6: Two-Column Detection (PyMuPDF)
**What:** After checking `parse_quality` flags, confirm via PyMuPDF text block x-coordinate bimodality.
**When to use:** `select_sample.py` to identify which papers count toward the ≥30 two-column requirement.
**Example:**
```python
import pymupdf

def is_two_column(pdf_path: str, sample_pages: int = 3) -> bool:
    """Heuristic: check if text block x0 values cluster in two groups (left/right columns)."""
    doc = pymupdf.open(pdf_path)
    try:
        page_width = doc[0].rect.width
        mid = page_width / 2
        left_blocks, right_blocks = 0, 0

        for page in list(doc)[:sample_pages]:
            blocks = page.get_text("dict")["blocks"]
            for block in blocks:
                if block.get("type") != 0:  # text blocks only
                    continue
                x0 = block["bbox"][0]
                x1 = block["bbox"][2]
                width = x1 - x0
                # A genuine two-column block is narrow (< 55% of page width)
                if width < page_width * 0.55:
                    if x0 < mid * 0.6:  # left column
                        left_blocks += 1
                    elif x0 > mid * 0.9:  # right column
                        right_blocks += 1

        # Two-column if both columns have substantial content
        return left_blocks >= 3 and right_blocks >= 3
    finally:
        doc.close()
```

### Pattern 7: Table Structural Completeness Score
**What:** Score 0.0 / 0.5 / 1.0 per D-19 based on whether table has caption, headers, and data rows.
**When to use:** Applied to each parser's table output.
**Example:**
```python
def table_completeness_docling(table_item, doc) -> float:
    """Score Docling TableItem per D-19."""
    try:
        df = table_item.export_to_dataframe(doc=doc)
        has_caption = bool(getattr(table_item, "caption", None))
        has_headers = len(df.columns) > 0 and not all(str(c).startswith("Unnamed") for c in df.columns)
        has_data_rows = len(df) >= 1
        if has_caption and has_headers and has_data_rows:
            return 1.0
        if has_caption:
            return 0.5
        return 0.0
    except Exception:
        return 0.0

def table_completeness_grobid(tei_xml_bytes: bytes) -> list[float]:
    """Extract table completeness scores from GROBID TEI XML."""
    # GROBID encodes tables as <figure type="table"> with <figDesc> for caption
    # and <table> child elements with <row>/<cell> structure
    from lxml import etree
    TEI_NS = "http://www.tei-c.org/ns/1.0"
    root = etree.fromstring(tei_xml_bytes)
    scores = []
    for fig in root.iter(f"{{{TEI_NS}}}figure"):
        if fig.get("type") != "table":
            continue
        has_caption = fig.find(f"{{{TEI_NS}}}figDesc") is not None
        table_el = fig.find(f"{{{TEI_NS}}}table")
        if table_el is None:
            scores.append(0.5 if has_caption else 0.0)
            continue
        rows = table_el.findall(f".//{{{TEI_NS}}}row")
        has_data_rows = len(rows) >= 2  # header row + at least 1 data row
        # Headers = first row cells
        header_cells = rows[0].findall(f"{{{TEI_NS}}}cell") if rows else []
        has_headers = len(header_cells) > 0
        if has_caption and has_headers and has_data_rows:
            scores.append(1.0)
        elif has_caption:
            scores.append(0.5)
        else:
            scores.append(0.0)
    return scores
```

### Pattern 8: Router Condition (Pipeline Output)
**What:** For Router condition, use the already-parsed content from the DB (Paper.content) rather than re-running parsers. The router result IS the normalized Paper.content.
**When to use:** Router condition row in `run_benchmark.py`.
**Example:**
```python
from app.db import SessionLocal
from app.models import Paper

def get_router_result(paper_id: str) -> tuple[list[dict], list[dict]]:
    """Read pre-computed pipeline output from DB."""
    session = SessionLocal()
    try:
        paper = session.query(Paper).filter(Paper.canonical_id == paper_id).first()
        if not paper or not paper.content:
            return [], []
        content = paper.content
        # Normalized schema: sections list
        sections = content.get("sections", [])
        # Tables may be in ref_entries as TABREF keys
        tables = [v for k, v in content.get("ref_entries", {}).items() if k.startswith("TABREF")]
        return sections, tables
    finally:
        session.close()
```

### Anti-Patterns to Avoid
- **Using DB-cached MinerU output for standalone condition:** The standalone MinerU condition must re-run `magic-pdf` on the raw PDF. Using DB content would conflate MinerU-standalone with Router results.
- **Sending all pages to Claude Opus:** Cap at 10 pages per paper for GT. Most academic paper headings appear in the first 10 pages. Sending all 30+ pages adds cost without accuracy gain.
- **Blocking on first GT failure:** `create_gt.py` must continue on individual paper failures and record them; interrupt/resume via the cache directory.
- **Not forcing CPU in Docling:** Without `AcceleratorDevice.CPU`, Docling may attempt MPS (Apple Silicon) or CUDA and crash or silently fall back, giving unreproducible results.
- **Importing docling at module level:** Follow project pattern of lazy imports inside function bodies to avoid `ImportError` at CLI entry point on machines without Docling.
- **Using `text_level` from MinerU output for heading detection:** `text_level` is always 1 in OSS MinerU. Use `type` field (`"title"`, `"text_title"`) instead.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| PDF page rendering for GT | Custom PIL/matplotlib PDF renderer | `pymupdf.page.get_pixmap()` | Already in project; correct DPI control |
| Token overlap scoring | Custom edit-distance scorer | Simple set intersection / max-len formula (see Pattern 3) | Token overlap is lighter and more robust to abbreviation variation in headings |
| TEI XML parsing | Custom regex TEI parser | `lxml` + existing `_parse_tei_fulltext_sections()` in `app/parsers/grobid.py` | Already implemented; handles namespace correctly |
| GROBID full-text call | New HTTP client | `app.parsers.grobid.extract_fulltext()` | Already implemented (Phase 4) |
| MinerU pipeline orchestration | New ML pipeline code | `PymuDocDataset` + `doc_analyze` pattern from `parse_pdf_mineru` | Proven pattern; handles OCR/text classification |
| DB access in benchmark scripts | New ORM setup | `app.db.SessionLocal` + `app.models.Paper/PaperSource` | Already wired; works outside Celery |

**Key insight:** Most benchmark infrastructure already exists in `app/parsers/grobid.py` and `app/tasks/parse_helpers.py`. The benchmark scripts are thin orchestration wrappers that call existing functions, compute metrics, and write CSV rows.

---

## Common Pitfalls

### Pitfall 1: Docling Imports Are Heavy
**What goes wrong:** `from docling.document_converter import DocumentConverter` at module top triggers model loading; takes 30–60s and may OOM on first import.
**Why it happens:** Docling loads its layout and table detection models on import.
**How to avoid:** Lazy import inside the function that runs Docling, following the project's established pattern (see `parse_pdf_mineru` lazy imports).
**Warning signs:** Script hangs at startup; OOM kill before first paper processed.

### Pitfall 2: Docling CPU Mode Not Explicitly Set
**What goes wrong:** On Apple Silicon, Docling defaults to MPS acceleration; on Docker, may attempt CUDA. Both can fail silently or crash mid-run.
**Why it happens:** `AcceleratorDevice.AUTO` is the default and selects the first available device.
**How to avoid:** Always pass `AcceleratorOptions(device=AcceleratorDevice.CPU)` in benchmark context (D-01: Mac CPU only).

### Pitfall 3: Claude Opus API — JSON Parsing of GT Response
**What goes wrong:** Claude may wrap the JSON array in markdown code fences (` ```json ... ``` `) or add an explanation before the array.
**Why it happens:** Claude follows its instruction style even with explicit "return ONLY JSON" prompts.
**How to avoid:** Strip markdown fences before `json.loads()`. Add `prefill` assistant text `[` to force array start — but note: prefill is NOT supported on claude-opus-4-6 (returns 400 error per official docs). Use prompt engineering instead: "Your response must begin with `[` and end with `]`."
**Warning signs:** `json.JSONDecodeError` on Claude responses; responses starting with "Here are the headings:".

### Pitfall 4: Prefill Not Supported on claude-opus-4-6
**What goes wrong:** Sending a message with `role: assistant` as the last message before the model's turn (prefill) returns HTTP 400.
**Why it happens:** Prefilling is explicitly not supported on Claude Opus 4.6 (and 4.7, Sonnet 4.6) per official docs: "Prefilling is not supported on Claude Opus 4.7, Claude Opus 4.6, and Claude Sonnet 4.6."
**How to avoid:** Use prompt engineering only. Include "Start your response with `[`" in the prompt. Or use structured output-style instructions.

### Pitfall 5: PyMuPDF DPI and Token Cost Tradeoff
**What goes wrong:** Rendering PDF pages at high DPI (300+) produces images > 8000×8000px that exceed Claude API's max dimension (8000×8000px limit, and prefer < 1568px long edge). High DPI also inflates request size.
**Why it happens:** Standard academic PDFs at 300 DPI render to ~2480×3508px (A4), consuming ~4784 tokens on Opus 4.7 (high-res) or up to the 1568-token cap on Opus 4.6.
**How to avoid:** Use 120 DPI for GT extraction. This produces ~990×1400px images (~1848 tokens before cap, effectively ~1568 capped on Opus 4.6). Sufficient quality for heading extraction.

### Pitfall 6: GROBID Full-Text Timeout on Slow Papers
**What goes wrong:** GROBID `/api/processFulltextDocument` can take 30–90s for complex multi-section papers. 150 papers × 60s = 2.5 hours in the worst case.
**Why it happens:** GROBID's full-text model is computationally heavier than `processReferences`.
**How to avoid:** Set timeout=90 in `extract_fulltext()` call for benchmark context. Run GROBID condition sequentially (not parallel) to avoid overwhelming the single GROBID service. Expect ~60–120 minutes for GROBID standalone condition.

### Pitfall 7: MinerU Standalone vs DB Content Conflation
**What goes wrong:** Using `paper.content` from DB for the MinerU standalone condition produces Router-equivalent results, making the comparison meaningless.
**Why it happens:** DB content was produced by the full pipeline (MinerU + normalization), not raw MinerU output.
**How to avoid:** MinerU standalone must call `PymuDocDataset` → `doc_analyze` → `dump_content_list` on the raw PDF asset. The DB content is only used for the Router condition.

### Pitfall 8: Missing ANTHROPIC_API_KEY in Benchmark Context
**What goes wrong:** `create_gt.py` fails immediately with `anthropic.APIStatusError: Authentication` when run as a standalone script outside Docker.
**Why it happens:** Docker env_file injects variables for the app, but benchmark scripts run locally on Mac (D-01).
**How to avoid:** `create_gt.py` must check for `ANTHROPIC_API_KEY` env var at startup and print a clear error if missing. Document in `benchmark/README` (or docstring) that the key must be set before running.

### Pitfall 9: Docling table.export_to_dataframe() Signature
**What goes wrong:** Calling `table.export_to_dataframe()` without passing `doc=result.document` raises `TypeError` or returns empty DataFrame.
**Why it happens:** The method requires the parent document for cell text resolution.
**How to avoid:** Always call `table.export_to_dataframe(doc=result.document)`.

### Pitfall 10: Database Not Accessible from benchmark/ Scripts
**What goes wrong:** `from app.db import SessionLocal` fails with `ModuleNotFoundError` when `benchmark/select_sample.py` is run from the `benchmark/` directory.
**Why it happens:** `app/` is not on sys.path when running scripts from `benchmark/`.
**How to avoid:** Add `sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))` at the top of every benchmark script, before app imports. Or use `python -m benchmark.select_sample` from project root.

---

## Code Examples

### Verified Pattern: Anthropic Python SDK base64 image message
```python
# Source: https://platform.claude.com/docs/en/api/messages-examples (verified 2026-04-17)
import anthropic
import base64

client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

message = client.messages.create(
    model="claude-opus-4-6",
    max_tokens=1024,
    messages=[
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",   # or image/jpeg
                        "data": base64_encoded_string,
                    },
                },
                {"type": "text", "text": "Your prompt here"},
            ],
        }
    ],
)
text_response = message.content[0].text
```

### Verified Pattern: Docling section header extraction
```python
# Source: https://docling-project.github.io/docling/reference/document_converter/ (verified 2026-04-17)
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.datamodel.accelerator_options import AcceleratorOptions, AcceleratorDevice

pipeline_options = PdfPipelineOptions(do_table_structure=True)
pipeline_options.accelerator_options = AcceleratorOptions(device=AcceleratorDevice.CPU)

converter = DocumentConverter(
    format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
)
result = converter.convert(pdf_path)

# Status check
if result.status.name not in ("SUCCESS", "PARTIAL_SUCCESS"):
    raise RuntimeError(f"Docling failed: {result.status}")

headings = [item.text for item in result.document.texts if item.label == "section_header"]
tables = result.document.tables  # list of TableItem
```

### Verified Pattern: GROBID full-text (already exists in app/parsers/grobid.py)
```python
# Source: app/parsers/grobid.py::extract_fulltext() — implemented Phase 4
from app.parsers.grobid import extract_fulltext

sections, citations = extract_fulltext(pdf_path, timeout=90)
# sections: list[dict] with keys: heading, sec_num, text, paragraphs, token_count
# citations: list[dict] with keys: title, authors, year, doi, raw_text
```

### Verified Pattern: PyMuPDF page rendering
```python
# Source: PyMuPDF docs + existing _has_text_layer() pattern
import pymupdf

doc = pymupdf.open(pdf_path)
try:
    for page in doc[:10]:
        pix = page.get_pixmap(dpi=120)          # ~1000px width
        png_bytes = pix.tobytes("png")           # bytes for base64 encoding
        # OR: pix.save("page_001.png")
finally:
    doc.close()
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| GROBID-only PDF parsing | MinerU + GROBID + Docling tiered | 2023–2024 | MinerU better for complex layouts |
| Manual GT annotation | LLM vision API for GT | 2024 | Scalable, consistent across paper types |
| Single-page PDF rendering | Multi-page batch to vision API | 2024 | More complete heading capture |
| Docling GPU-only | Docling CPU mode via AcceleratorOptions | 2024 | Usable for local Mac benchmark |
| `text_level` for MinerU headings | `type: "title"/"text_title"` | 2024 | `text_level` always 1 in OSS MinerU |

**Current state (April 2026):**
- Docling 2.90.0 is the latest release (today). Python API is stable. `section_header` label and `tables` attribute are confirmed.
- `claude-opus-4-6` is available at $5/MTok input, $25/MTok output. Batch API offers 50% discount ($2.50/$12.50 MTok).
- Prefill NOT supported on claude-opus-4-6 — use prompt engineering for JSON output forcing.
- GROBID 0.8.0 already running in docker-compose. Full-text endpoint confirmed at `/api/processFulltextDocument`.
- `extract_fulltext()` already implemented in `app/parsers/grobid.py` (Phase 4 deliverable).

---

## Open Questions

1. **Docling `item.label` string value**
   - What we know: Official docs show `result.document.texts` contains `SectionHeaderItem` objects with `label` attribute
   - What's unclear: Whether `item.label` is a string `"section_header"` or an enum `DocItemLabel.SECTION_HEADER`
   - Recommendation: Add a guard at runtime: `str(item.label) in ("section_header", "DocItemLabel.section_header")` to handle both. Or `item.label.name == "SECTION_HEADER"` if enum.

2. **MinerU heading type names in v1.3.12**
   - What we know: Content list has typed items; headings are `"title"` or `"text_title"` based on community reports
   - What's unclear: Whether v1.3.12 uses exactly these strings or has renamed them
   - Recommendation: Wave 0 task: print unique `type` values from 1–2 test papers to confirm. Fallback: check content list for items that `magic_pdf` docs identify as headings.

3. **anthropic Python SDK version compatibility**
   - What we know: Latest `anthropic` SDK supports claude-opus-4-6 model ID
   - What's unclear: Exact minimum version required
   - Recommendation: `pip install "anthropic>=0.40.0"` is safe; run `pip show anthropic` to confirm installed.

4. **Router condition for LaTeX-sourced papers**
   - What we know: Router condition uses pre-computed DB content (Paper.content)
   - What's unclear: For LaTeX-sourced papers, `paper.content` is raw S2ORC JSON, not normalized. The normalized sections are in the `sections` key of the final normalized content.
   - Recommendation: Check `paper.parse_source` and normalize field access accordingly: S2ORC uses `body_text`, MinerU uses `content_list`, normalized uses `sections`.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (already in project: `pytest`, `pytest-timeout`) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` — testpaths = ["tests"] |
| Quick run command | `pytest tests/test_benchmark.py -x -q` |
| Full suite command | `pytest tests/ -x -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| BENCH-01 | `select_sample.py` selects exactly 150 papers with ≥30 two-column | unit (mock DB) | `pytest tests/test_benchmark.py::test_sample_selection_counts -x` | ❌ Wave 0 |
| BENCH-01 | All four conditions run without crash on 1 test paper | smoke | `pytest tests/test_benchmark.py::test_all_conditions_smoke -x` | ❌ Wave 0 |
| BENCH-01 | `sample.json` is written and reproducible | unit | `pytest tests/test_benchmark.py::test_sample_json_written -x` | ❌ Wave 0 |
| BENCH-02 | `heading_matched()` returns correct result for ≥80% overlap | unit | `pytest tests/test_benchmark.py::test_heading_match_rate -x` | ❌ Wave 0 |
| BENCH-02 | `heading_matched()` returns False for 0% overlap | unit | `pytest tests/test_benchmark.py::test_heading_match_no_overlap -x` | ❌ Wave 0 |
| BENCH-02 | `coherent_section_pct()` returns 1.0 for clean text | unit | `pytest tests/test_benchmark.py::test_coherence_clean_text -x` | ❌ Wave 0 |
| BENCH-02 | `coherent_section_pct()` returns 0.0 for garbled text | unit | `pytest tests/test_benchmark.py::test_coherence_garbled_text -x` | ❌ Wave 0 |
| BENCH-02 | `table_completeness_docling()` scores 1.0 / 0.5 / 0.0 correctly | unit (mock TableItem) | `pytest tests/test_benchmark.py::test_table_completeness_scoring -x` | ❌ Wave 0 |
| BENCH-02 | CSV output has exactly 600 rows and correct columns | integration (fixture) | `pytest tests/test_benchmark.py::test_csv_schema -x` | ❌ Wave 0 |
| BENCH-03 | `FINDINGS.md` contains required sections (methodology, comparison table, recommendation) | smoke (string search) | `pytest tests/test_benchmark.py::test_findings_md_sections -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_benchmark.py -x -q`
- **Per wave merge:** `pytest tests/ -x -q`
- **Phase gate:** All benchmark tests green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_benchmark.py` — covers all BENCH requirements above
- [ ] Fixture: `tests/fixtures/mini_pdf.pdf` — a tiny 2-page PDF for smoke tests (copy from existing test fixtures if available)
- [ ] Fixture: mock `sample.json` with 5 fake paper IDs for unit tests

*(No existing test infrastructure covers benchmark requirements — all test files are Wave 0 creates)*

---

## Cost Estimate

### Claude Opus GT Creation (D-08/D-09)
- 150 papers × ~10 pages/paper = 1,500 API calls
- Per page: ~1,568 tokens input (image at 120 DPI) + ~200 tokens text prompt = ~1,768 tokens
- GT response: ~150 tokens output per call
- **Standard pricing:** 1,500 × (1,768 × $5/1M + 150 × $25/1M) = 1,500 × ($0.00884 + $0.00375) = **~$18.90 total**
- **Batch API (50% off):** ~$9.45 total
- Recommendation: Use Batch API for GT creation if the 24-hour turnaround is acceptable; otherwise standard API with retry logic is fine for a one-time run.

### Runtime Estimates (CPU, local Mac)
| Condition | Per-paper time | 150-paper total |
|-----------|---------------|-----------------|
| MinerU standalone | 30–60s | 75–150 min |
| GROBID standalone | 30–90s | 75–225 min |
| Docling standalone | 60–120s (CPU) | 150–300 min |
| Router (DB read) | <1s | <5 min |
| GT creation (Opus) | 5–15s/call | 15–38 min (API latency) |

**Total benchmark runtime estimate:** 6–12 hours for all conditions. Plan for an overnight run or staggered execution.

---

## Sources

### Primary (HIGH confidence)
- [Anthropic Models Overview](https://platform.claude.com/docs/en/about-claude/models/overview) — claude-opus-4-6 API ID confirmed, pricing verified
- [Anthropic Pricing](https://platform.claude.com/docs/en/about-claude/pricing) — $5/$25 MTok, Batch API 50% discount confirmed
- [Anthropic Messages API Examples](https://platform.claude.com/docs/en/api/messages-examples) — base64 image content block format verified
- [Anthropic Vision Guide](https://platform.claude.com/docs/en/build-with-claude/vision) — image token calculation, 1568-token cap on Opus 4.6, prefill NOT supported on 4.6
- [Docling DocumentConverter Reference](https://docling-project.github.io/docling/reference/document_converter/) — `result.document.texts`, `result.document.tables`, labels
- [Docling Advanced Options](https://docling-project.github.io/docling/usage/advanced_options/) — `PdfPipelineOptions`, `AcceleratorOptions`
- [Docling PyPI](https://pypi.org/project/docling/) — version 2.90.0, Python ≥ 3.10 requirement verified
- [Docling Table Export](https://docling-project.github.io/docling/examples/export_tables/) — `export_to_dataframe(doc=...)` signature
- `app/parsers/grobid.py` — `extract_fulltext()` already implemented; `_parse_tei_fulltext_sections()` already handles TEI `<div>/<head>`
- `app/tasks/parse_helpers.py` — `_sentence_length_degraded()` confirmed for reuse

### Secondary (MEDIUM confidence)
- [Docling GPU issue #2727](https://github.com/docling-project/docling/issues/2727) — `AcceleratorDevice.CPU` confirmed for disabling GPU
- [Docling item label discussion #2058](https://github.com/docling-project/docling/issues/2058) — `section_header` label string confirmed
- [MinerU PyPI page](https://pypi.org/project/magic-pdf/) — v1.3.12 current; `type: "title"` for headings (MEDIUM — needs runtime verification)

### Tertiary (LOW confidence — verify at implementation)
- MinerU `content_list` item type strings (`"title"`, `"text_title"`) — sourced from community reports and parse.py comment `"text_level_broken": True`; verify by printing unique types from test paper
- Docling `item.label` as string vs enum — verify with `type(item.label)` on first run

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all packages verified on PyPI; Anthropic API verified on official docs
- Architecture: HIGH — all code patterns from existing project code or official docs
- Pitfalls: HIGH — most from reading existing code (grobid.py, parse.py) + official docs (prefill not supported)
- Cost estimates: MEDIUM — based on official pricing tables × estimated page counts

**Research date:** 2026-04-17
**Valid until:** 2026-05-17 (Docling releases frequently; re-verify version before install)
