"""Four-condition benchmark runner — Phase 7.

Conditions (D-17): mineru, grobid, docling, router.
Input: benchmark/sample.json + benchmark/gt/{paper_id}.json
Output: benchmark/results/benchmark.csv (D-17 schema, 600 rows)

Each condition produces (sections, tables) from its own parse path; metrics are
computed via benchmark.metrics.* against the GT headings.

Errors per paper are recorded in the `error` column and do not abort the run.
"""

import argparse
import csv
import json
import logging
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmark.metrics import (  # type: ignore[import]
    compute_heading_match_rate,
    coherent_section_pct,
    table_completeness_docling,
    table_completeness_grobid,
    table_completeness_mineru,
)

SAMPLE_PATH = os.path.join(os.path.dirname(__file__), "sample.json")
GT_DIR = os.path.join(os.path.dirname(__file__), "gt")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
CSV_PATH = os.path.join(RESULTS_DIR, "benchmark.csv")

CSV_COLUMNS = [
    "paper_id", "arxiv_id", "source_type", "column_layout", "subject",
    "condition", "heading_count_gt", "heading_count_parser",
    "heading_match_rate", "coherent_section_pct",
    "table_presence", "table_structural_completeness", "sec_per_doc", "error",
]

CONDITIONS = ["mineru", "grobid", "docling", "router"]

GROBID_TIMEOUT_SECONDS = 90  # Pitfall 6

# Remap host-absolute pdf_path to container DATA_DIR if needed.
# sample.json stores host paths; inside Docker DATA_DIR=/data.
_DATA_DIR = os.environ.get("DATA_DIR", "")

def _remap_pdf_path(path: str) -> str:
    if not _DATA_DIR or os.path.exists(path):
        return path
    # Extract relative portion after any "data/" segment and join with DATA_DIR
    marker = os.sep + "data" + os.sep
    idx = path.find(marker)
    if idx != -1:
        rel = path[idx + len(marker):]
        return os.path.join(_DATA_DIR, rel)
    return path

logger = logging.getLogger("run_benchmark")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


# ============================================================
# Condition: MinerU standalone (Pattern 5; mirrors parse_pdf_mineru)
# ============================================================

def run_mineru_standalone(pdf_path: str) -> tuple:
    """Call magic-pdf on raw PDF, return (sections, content_list).

    Lazy imports per project convention (Pitfall 1).
    sections: list[{heading, text}]
    content_list: full MinerU output (for table_completeness_mineru)
    """
    from magic_pdf.config.enums import SupportedPdfParseMethod  # type: ignore[import-untyped]
    from magic_pdf.data.data_reader_writer import FileBasedDataWriter  # type: ignore[import-untyped]
    from magic_pdf.data.dataset import PymuDocDataset  # type: ignore[import-untyped]
    from magic_pdf.model.doc_analyze_by_custom_model import doc_analyze  # type: ignore[import-untyped]

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
        pipe.dump_md(output_writer, "output.md", "images")
        with open(os.path.join(output_dir, "content_list.json")) as f:
            content_list = json.load(f)

        # Primary: extract headings from content_list title/text_title types (Pitfall 5)
        sections = []
        current = None
        for item in content_list:
            t = item.get("type", "")
            if t in ("title", "text_title"):
                if current:
                    sections.append(current)
                current = {"heading": item.get("text", ""), "text": ""}
            elif t == "text" and current is not None:
                current["text"] = (current["text"] + " " + item.get("text", "")).strip()
        if current:
            sections.append(current)

        # Fallback: if no headings found via type, parse markdown # headers
        if not sections:
            md_path = os.path.join(output_dir, "output.md")
            if os.path.exists(md_path):
                with open(md_path) as f:
                    md_lines = f.readlines()
                current = None
                for line in md_lines:
                    stripped = line.rstrip()
                    if stripped.startswith("#"):
                        if current:
                            sections.append(current)
                        heading = stripped.lstrip("#").strip()
                        if heading:
                            current = {"heading": heading, "text": ""}
                    elif current is not None and stripped:
                        current["text"] = (current["text"] + " " + stripped).strip()
                if current:
                    sections.append(current)

        # Pass full content_list to table_completeness_mineru
        return sections, content_list
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)


# ============================================================
# Condition: GROBID standalone (reuse existing TEI parser)
# ============================================================

def run_grobid_standalone(pdf_path: str) -> tuple:
    """Call GROBID /api/processFulltextDocument. Return (sections, tei_bytes).

    We call GROBID directly to get TEI bytes for table_completeness_grobid.
    """
    import httpx  # lazy import
    GROBID_URL = os.environ.get("GROBID_URL", "http://grobid:8070")
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()
    with httpx.Client(timeout=GROBID_TIMEOUT_SECONDS) as client:
        resp = client.post(
            f"{GROBID_URL}/api/processFulltextDocument",
            files={"input": ("paper.pdf", pdf_bytes, "application/pdf")},
            data={"includeRawCitations": "1", "consolidateCitations": "0"},
        )
    if resp.status_code != 200:
        raise RuntimeError(f"GROBID status {resp.status_code}")
    tei_bytes = resp.content
    # Reuse existing section parser from app/parsers/grobid.py
    from app.parsers.grobid import _parse_tei_fulltext_sections  # lazy import
    sections = _parse_tei_fulltext_sections(tei_bytes)
    return sections, tei_bytes


# ============================================================
# Condition: Docling standalone (Pattern 1; Pitfalls 1, 2, 9)
# ============================================================

def run_docling_standalone(pdf_path: str) -> tuple:
    """Call Docling DocumentConverter on CUDA. Return (sections, tables, doc).

    Lazy imports (Pitfall 1). GPU device for fair comparison vs MinerU-GPU.
    """
    from docling.document_converter import DocumentConverter, PdfFormatOption  # type: ignore[import-untyped]
    from docling.datamodel.base_models import InputFormat  # type: ignore[import-untyped]
    from docling.datamodel.pipeline_options import PdfPipelineOptions  # type: ignore[import-untyped]
    from docling.datamodel.accelerator_options import AcceleratorOptions, AcceleratorDevice  # type: ignore[import-untyped]

    pipeline_options = PdfPipelineOptions(do_table_structure=True)
    pipeline_options.accelerator_options = AcceleratorOptions(device=AcceleratorDevice.CUDA)
    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
    )
    result = converter.convert(pdf_path)
    if result.status.name not in ("SUCCESS", "PARTIAL_SUCCESS"):
        raise RuntimeError(f"Docling status {result.status.name}")
    doc = result.document

    # Build sections by walking texts in document order. Each section starts at a section_header.
    sections = []
    current = None
    for item in doc.texts:
        label = str(getattr(item, "label", ""))
        # Handle both string "section_header" and enum "DocItemLabel.SECTION_HEADER" (Open Q 1)
        if "section_header" in label.lower():
            if current:
                sections.append(current)
            current = {"heading": item.text, "text": ""}
        elif current is not None:
            current["text"] = (current["text"] + " " + (item.text or "")).strip()
    if current:
        sections.append(current)

    return sections, list(doc.tables), doc


# ============================================================
# Condition: Router (D-03 logic: count PDF tables, route to GROBID or MinerU)
# ============================================================

TABLE_THRESHOLD = 3  # D-03: ≤3 tables → GROBID, >3 tables → MinerU

def _count_pdf_tables(pdf_path: str) -> int:
    """Count tables in PDF via pymupdf heuristic (number of detected table blocks)."""
    import pymupdf  # type: ignore[import-untyped]
    doc = pymupdf.open(pdf_path)
    table_count = 0
    try:
        for page in doc:
            tabs = page.find_tables()
            table_count += len(tabs.tables)
    finally:
        doc.close()
    return table_count


def run_router_standalone(pdf_path: str) -> tuple:
    """Route PDF to GROBID or MinerU per D-03: count tables, pick parser.

    ≤3 tables → GROBID (fast, sufficient for text-heavy papers)
    >3 tables → MinerU (heavy layout model for table/formula-rich papers)

    Returns (sections, tables, parser_used).
    """
    n_tables = _count_pdf_tables(pdf_path)
    if n_tables <= TABLE_THRESHOLD:
        sections, tei_bytes = run_grobid_standalone(pdf_path)
        table_scores = table_completeness_grobid(tei_bytes) if tei_bytes else []
        return sections, table_scores, "grobid"
    else:
        sections, content_list = run_mineru_standalone(pdf_path)
        table_scores = table_completeness_mineru(content_list)
        return sections, table_scores, "mineru"


# ============================================================
# GT loading
# ============================================================

def _load_gt(paper_id: str) -> list:
    path = os.path.join(GT_DIR, f"{paper_id}.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path) as f:
            data = json.load(f)
        return data.get("headings") or []
    except Exception:
        return []


# ============================================================
# Row builder per (paper, condition)
# ============================================================

def _build_row(entry: dict, condition: str) -> dict:
    """Run one condition on one paper, compute metrics, return CSV row dict."""
    paper_id = entry["paper_id"]
    row = {
        "paper_id": paper_id,
        "arxiv_id": entry.get("arxiv_id") or "",
        "source_type": entry.get("source_type") or "",
        "column_layout": entry.get("column_layout") or "",
        "subject": entry.get("subject") or "",
        "condition": condition,
        "heading_count_gt": 0,
        "heading_count_parser": 0,
        "heading_match_rate": 0.0,
        "coherent_section_pct": 0.0,
        "table_presence": 0,
        "table_structural_completeness": 0.0,
        "sec_per_doc": 0.0,
        "error": "",
    }
    gt_headings = _load_gt(paper_id)
    row["heading_count_gt"] = len(gt_headings)
    if not gt_headings:
        row["error"] = "gt_missing"
        return row

    pdf_path = _remap_pdf_path(entry.get("pdf_path") or "")
    _t0 = time.time()
    try:
        if condition == "mineru":
            if not pdf_path or not os.path.exists(pdf_path):
                raise RuntimeError(f"pdf_missing: {pdf_path}")
            sections, content_list = run_mineru_standalone(pdf_path)
            parser_headings = [s["heading"] for s in sections if s.get("heading")]
            row["heading_count_parser"] = len(parser_headings)
            row["heading_match_rate"] = compute_heading_match_rate(parser_headings, gt_headings)
            row["coherent_section_pct"] = coherent_section_pct(sections)
            table_scores = table_completeness_mineru(content_list)
            row["table_presence"] = 1 if table_scores else 0
            row["table_structural_completeness"] = (sum(table_scores) / len(table_scores)) if table_scores else 0.0

        elif condition == "grobid":
            if not pdf_path or not os.path.exists(pdf_path):
                raise RuntimeError(f"pdf_missing: {pdf_path}")
            try:
                sections, tei_bytes = run_grobid_standalone(pdf_path)
            except Exception as grobid_exc:
                # Fallback: read cached grobid_sections from DB (populated by populate_db_grobid.py)
                from app.db import SessionLocal as _SL  # type: ignore[import]
                from app.models import Paper as _P  # type: ignore[import]
                _session = _SL()
                try:
                    _paper = _session.query(_P).filter(_P.canonical_id == paper_id).first()
                    _content = (_paper.content or {}) if _paper else {}
                    sections = _content.get("grobid_sections") or []
                finally:
                    _session.close()
                if not sections:
                    raise RuntimeError(f"grobid_live_failed ({grobid_exc}) and no cached grobid_sections in DB")
                tei_bytes = b""  # no TEI for table scoring in fallback path
            parser_headings = [s["heading"] for s in sections if s.get("heading")]
            row["heading_count_parser"] = len(parser_headings)
            row["heading_match_rate"] = compute_heading_match_rate(parser_headings, gt_headings)
            row["coherent_section_pct"] = coherent_section_pct(sections)
            table_scores = table_completeness_grobid(tei_bytes) if tei_bytes else []
            row["table_presence"] = 1 if table_scores else 0
            row["table_structural_completeness"] = (sum(table_scores) / len(table_scores)) if table_scores else 0.0

        elif condition == "docling":
            if not pdf_path or not os.path.exists(pdf_path):
                raise RuntimeError(f"pdf_missing: {pdf_path}")
            sections, tables, doc = run_docling_standalone(pdf_path)
            parser_headings = [s["heading"] for s in sections if s.get("heading")]
            row["heading_count_parser"] = len(parser_headings)
            row["heading_match_rate"] = compute_heading_match_rate(parser_headings, gt_headings)
            row["coherent_section_pct"] = coherent_section_pct(sections)
            table_scores = [table_completeness_docling(t, doc) for t in tables]
            row["table_presence"] = 1 if tables else 0
            row["table_structural_completeness"] = (sum(table_scores) / len(table_scores)) if table_scores else 0.0

        elif condition == "router":
            if not pdf_path or not os.path.exists(pdf_path):
                raise RuntimeError(f"pdf_missing: {pdf_path}")
            sections, table_scores, parser_used = run_router_standalone(pdf_path)
            parser_headings = [s.get("heading", "") for s in sections if s.get("heading")]
            row["heading_count_parser"] = len(parser_headings)
            row["heading_match_rate"] = compute_heading_match_rate(parser_headings, gt_headings)
            row["coherent_section_pct"] = coherent_section_pct(sections)
            row["table_presence"] = 1 if table_scores else 0
            row["table_structural_completeness"] = (sum(table_scores) / len(table_scores)) if table_scores else 0.0
            logger.info("router picked %s (%d tables detected)", parser_used, _count_pdf_tables(pdf_path))

        else:
            raise ValueError(f"unknown condition: {condition}")

        row["sec_per_doc"] = round(time.time() - _t0, 2)

    except Exception as exc:
        row["sec_per_doc"] = round(time.time() - _t0, 2)
        row["error"] = str(exc)[:500]
        logger.warning("[%s/%s] FAILED: %s", paper_id, condition, exc)
    return row


# ============================================================
# CSV streaming + resume
# ============================================================

def _load_done_pairs() -> set:
    if not os.path.exists(CSV_PATH):
        return set()
    done = set()
    with open(CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("error"):
                continue  # re-try errored rows
            done.add((row["paper_id"], row["condition"]))
    return done


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None, help="Cap to N papers")
    parser.add_argument("--condition", choices=CONDITIONS, default=None, help="Only this condition")
    parser.add_argument("--resume", action="store_true", help="Skip (paper,condition) already in CSV")
    args = parser.parse_args()

    with open(SAMPLE_PATH) as f:
        sample = json.load(f)
    if args.limit:
        sample = sample[: args.limit]
    conditions = [args.condition] if args.condition else CONDITIONS

    total_rows = len(sample) * len(conditions)
    if args.dry_run:
        print(f"[run_benchmark] dry-run — would run {len(conditions)} conditions × {len(sample)} papers = {total_rows} rows")
        return 0

    os.makedirs(RESULTS_DIR, exist_ok=True)
    done_pairs = _load_done_pairs() if args.resume else set()

    existing_rows = []
    if args.resume and os.path.exists(CSV_PATH):
        with open(CSV_PATH, "r", encoding="utf-8") as f:
            existing_rows = list(csv.DictReader(f))

    # Write header + existing rows to a new temp file, then stream new rows.
    # When --condition is set, preserve ALL rows for other conditions (even errored),
    # so a targeted re-run doesn't destroy results from other conditions.
    tmp_path = CSV_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for r in existing_rows:
            row_cond = r.get("condition")
            # Always keep rows from conditions not being re-run (regardless of error status)
            if args.condition and row_cond and row_cond not in conditions:
                writer.writerow(r)
                f.flush()
            elif (r.get("paper_id"), r.get("condition")) in done_pairs:
                writer.writerow(r)
                f.flush()
        n = 0
        for entry in sample:
            for cond in conditions:
                if (entry["paper_id"], cond) in done_pairs:
                    continue
                t0 = time.time()
                row = _build_row(entry, cond)
                writer.writerow(row)
                f.flush()
                n += 1
                logger.info(
                    "[%d/%d] %s/%s headings=%d/%d match=%.2f coherence=%.2f tables=%d (%.1fs)",
                    n, total_rows, entry["paper_id"], cond,
                    row["heading_count_parser"], row["heading_count_gt"],
                    row["heading_match_rate"], row["coherent_section_pct"],
                    row["table_presence"], time.time() - t0,
                )
    os.replace(tmp_path, CSV_PATH)

    # Final row-count verification
    with open(CSV_PATH) as f:
        row_count = sum(1 for _ in csv.DictReader(f))
    print(f"[run_benchmark] wrote {row_count} rows to {CSV_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
