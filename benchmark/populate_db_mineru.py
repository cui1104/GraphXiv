"""Populate Paper.content["sections"] with MinerU output for all sample papers.

Run this on RunPod after run_benchmark.py --condition mineru completes.
Reads MinerU sections from the benchmark CSV (already computed), writes them
into Paper.content["sections"] in the DB so the router condition reads MinerU output.

This simulates what the production router would store if MinerU models were
available at ingest time (arxiv PDF → MinerU → content["sections"]).
"""

import csv
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SAMPLE_PATH = os.path.join(os.path.dirname(__file__), "sample.json")
CSV_PATH = os.path.join(os.path.dirname(__file__), "results", "benchmark.csv")
DATA_DIR = os.environ.get("DATA_DIR", "/data")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("populate_db_mineru")


def main() -> int:
    from app.db import SessionLocal
    from app.models import Paper
    from sqlalchemy.orm.attributes import flag_modified
    sys.path.insert(0, os.path.dirname(__file__) + "/..")
    from benchmark.run_benchmark import _remap_pdf_path, run_mineru_standalone  # type: ignore[import]

    with open(SAMPLE_PATH) as f:
        sample = json.load(f)

    # Build map of paper_id -> sections from CSV (already-computed MinerU results)
    mineru_sections: dict = {}
    if os.path.exists(CSV_PATH):
        with open(CSV_PATH) as f:
            for row in csv.DictReader(f):
                if row["condition"] == "mineru" and not row["error"]:
                    mineru_sections[row["paper_id"]] = None  # placeholder — re-run below

    session = SessionLocal()
    done, skipped, errored = 0, 0, 0
    try:
        for i, entry in enumerate(sample, 1):
            paper_id = entry["paper_id"]
            paper = session.query(Paper).filter(Paper.canonical_id == paper_id).first()
            if not paper:
                logger.warning("[%d/%d] %s — not in DB", i, len(sample), paper_id)
                errored += 1
                continue

            content = paper.content or {}
            # Skip if already populated with MinerU output
            if content.get("sections") and content.get("parse_source_sections") == "mineru":
                logger.info("[%d/%d] %s — already has mineru sections, skip", i, len(sample), paper_id)
                skipped += 1
                continue

            pdf_path = _remap_pdf_path(entry["pdf_path"])
            if not os.path.exists(pdf_path):
                logger.warning("[%d/%d] %s — pdf missing: %s", i, len(sample), paper_id, pdf_path)
                errored += 1
                continue

            try:
                sections, _ = run_mineru_standalone(pdf_path)
                content["sections"] = sections
                content["parse_source_sections"] = "mineru"
                paper.content = content
                flag_modified(paper, "content")
                paper.parse_source = "mineru"
                session.commit()
                done += 1
                logger.info("[%d/%d] %s — %d sections", i, len(sample), paper_id, len(sections))
            except Exception as exc:
                session.rollback()
                errored += 1
                logger.warning("[%d/%d] %s — FAILED: %s", i, len(sample), paper_id, exc)
    finally:
        session.close()

    print(f"[populate_db_mineru] done={done} skipped={skipped} errored={errored} total={len(sample)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
