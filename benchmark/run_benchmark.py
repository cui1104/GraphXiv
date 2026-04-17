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

from benchmark.metrics import (
    compute_heading_match_rate,
    coherent_section_pct,
    table_completeness_docling,
    table_completeness_grobid,
    table_completeness_mineru,
    _table_completeness_score,
)

SAMPLE_PATH = os.path.join(os.path.dirname(__file__), "sample.json")
GT_DIR = os.path.join(os.path.dirname(__file__), "gt")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
CSV_PATH = os.path.join(RESULTS_DIR, "benchmark.csv")

CSV_COLUMNS = [
    "paper_id", "arxiv_id", "source_type", "column_layout", "subject",
    "condition", "heading_count_gt", "heading_count_parser",
    "heading_match_rate", "coherent_section_pct",
    "table_presence", "table_structural_completeness", "error",
]

CONDITIONS = ["mineru", "grobid", "docling", "router"]

GROBID_TIMEOUT_SECONDS = 90  # Pitfall 6

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
    from magic_pdf.config.enums import SupportedPdfParseMethod  # lazy import
    from magic_pdf.data.data_reader_writer import FileBasedDataWriter  # lazy import
    from magic_pdf.data.dataset import PymuDocDataset  # lazy import
    from magic_pdf.model.doc_analyze_by_custom_model import doc_analyze  # lazy import

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

        # Pitfall 5: use `type` not `text_level` (always 1 in OSS MinerU)
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
    GROBID_URL = os.environ.get("GROBID_URL", "http://localhost:8070")
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
    """Call Docling DocumentConverter on CPU. Return (sections, tables, doc).

    Lazy imports (Pitfall 1). CPU device forced (Pitfall 2).
    """
    from docling.document_converter import DocumentConverter, PdfFormatOption  # lazy import
    from docling.datamodel.base_models import InputFormat  # lazy import
    from docling.datamodel.pipeline_options import PdfPipelineOptions  # lazy import
    from docling.datamodel.accelerator_options import AcceleratorOptions, AcceleratorDevice  # lazy import

    pipeline_options = PdfPipelineOptions(do_table_structure=True)
    pipeline_options.accelerator_options = AcceleratorOptions(device=AcceleratorDevice.CPU)
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
# Condition: Router (read pre-computed DB content — Pattern 8)
# ============================================================

def run_router_from_db(paper_id: str) -> tuple:
    """Read normalized content from Paper.content in DB. Never re-parse (Pitfall 7)."""
    from app.db import SessionLocal  # lazy import
    from app.models import Paper  # lazy import
    session = SessionLocal()
    try:
        paper = session.query(Paper).filter(Paper.canonical_id == paper_id).first()
        if not paper or not paper.content:
            return [], []
        content = paper.content
        # Normalized schema stores sections as list under "sections" key.
        # For latex papers with only raw S2ORC, fall back to body_text.
        sections = content.get("sections") or []
        if not sections and "body_text" in content:
            # Convert s2orc body_text to minimal section shape
            sections = [{"heading": bt.get("section", ""), "text": bt.get("text", "")}
                        for bt in content.get("body_text", [])]
        # Tables may be in ref_entries as TABREF keys
        tables = [v for k, v in (content.get("ref_entries") or {}).items() if k.startswith("TABREF")]
        return sections, tables
    finally:
        session.close()


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
        "error": "",
    }
    gt_headings = _load_gt(paper_id)
    row["heading_count_gt"] = len(gt_headings)
    if not gt_headings:
        row["error"] = "gt_missing"
        return row

    pdf_path = entry.get("pdf_path") or ""
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
            sections, tei_bytes = run_grobid_standalone(pdf_path)
            parser_headings = [s["heading"] for s in sections if s.get("heading")]
            row["heading_count_parser"] = len(parser_headings)
            row["heading_match_rate"] = compute_heading_match_rate(parser_headings, gt_headings)
            row["coherent_section_pct"] = coherent_section_pct(sections)
            table_scores = table_completeness_grobid(tei_bytes)
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
            sections, tables = run_router_from_db(paper_id)
            parser_headings = [s.get("heading", "") for s in sections if s.get("heading")]
            row["heading_count_parser"] = len(parser_headings)
            row["heading_match_rate"] = compute_heading_match_rate(parser_headings, gt_headings)
            row["coherent_section_pct"] = coherent_section_pct(sections)
            # Router tables: score each via heuristic — presence of html/content + caption
            table_scores = []
            for tbl in tables:
                if isinstance(tbl, dict):
                    has_caption = bool(tbl.get("caption") or tbl.get("text"))
                    has_headers = bool(tbl.get("html") or tbl.get("content"))
                    has_rows = has_headers  # rough heuristic
                    table_scores.append(_table_completeness_score(has_caption, has_headers, has_rows))
            row["table_presence"] = 1 if tables else 0
            row["table_structural_completeness"] = (sum(table_scores) / len(table_scores)) if table_scores else 0.0

        else:
            raise ValueError(f"unknown condition: {condition}")

    except Exception as exc:
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

    # Write header + existing rows to a new temp file, then stream new rows
    tmp_path = CSV_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for r in existing_rows:
            if (r.get("paper_id"), r.get("condition")) in done_pairs:
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
