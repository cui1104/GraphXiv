"""Populate Paper.content["grobid_sections"] for all sample papers.

Calls GROBID extract_fulltext for each paper in sample.json that doesn't
already have grobid_sections in Paper.content. Stores results in DB.
Run this inside the Docker worker container before re-running --condition router.
"""

import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SAMPLE_PATH = os.path.join(os.path.dirname(__file__), "sample.json")
DATA_DIR = os.environ.get("DATA_DIR", "/data")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("populate_db_grobid")


def _remap_path(path: str) -> str:
    if not DATA_DIR or os.path.exists(path):
        return path
    marker = os.sep + "data" + os.sep
    idx = path.find(marker)
    if idx != -1:
        rel = path[idx + len(marker):]
        return os.path.join(DATA_DIR, rel)
    return path


def main() -> int:
    from app.db import SessionLocal
    from app.models import Paper
    from app.parsers.grobid import extract_fulltext

    with open(SAMPLE_PATH) as f:
        sample = json.load(f)

    session = SessionLocal()
    done, skipped, errored = 0, 0, 0
    try:
        for i, entry in enumerate(sample, 1):
            paper_id = entry["paper_id"]
            paper = session.query(Paper).filter(Paper.canonical_id == paper_id).first()
            if not paper:
                logger.warning("[%d/%d] %s — not found in DB", i, len(sample), paper_id)
                errored += 1
                continue

            content = paper.content or {}
            if content.get("grobid_sections"):  # non-empty list = already done
                logger.info("[%d/%d] %s — already has grobid_sections (%d), skip", i, len(sample), paper_id, len(content["grobid_sections"]))
                skipped += 1
                continue

            pdf_path = _remap_path(entry["pdf_path"])
            if not os.path.exists(pdf_path):
                logger.warning("[%d/%d] %s — pdf missing: %s", i, len(sample), paper_id, pdf_path)
                errored += 1
                continue

            try:
                from sqlalchemy.orm.attributes import flag_modified
                t0 = time.time()
                sections, _ = extract_fulltext(pdf_path, timeout=90)
                content["grobid_sections"] = sections
                paper.content = content
                flag_modified(paper, "content")
                paper.parse_source = paper.parse_source or "pdf_grobid"
                session.commit()
                done += 1
                logger.info(
                    "[%d/%d] %s — %d sections (%.1fs)",
                    i, len(sample), paper_id, len(sections), time.time() - t0,
                )
            except Exception as exc:
                session.rollback()
                errored += 1
                logger.warning("[%d/%d] %s — FAILED: %s", i, len(sample), paper_id, exc)
    finally:
        session.close()

    print(f"[populate_db_grobid] done={done} skipped={skipped} errored={errored} total={len(sample)}")
    return 0 if errored < len(sample) else 1


if __name__ == "__main__":
    sys.exit(main())
