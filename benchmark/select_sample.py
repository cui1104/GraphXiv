"""Stratified 150-paper sample selection for Phase 7 benchmark.

Strategy (D-04, D-05, D-06, D-07):
1. Query DB for all successfully-parsed papers with an available PDF asset.
2. Classify each as single-column or two-column using:
   a) Paper.parse_quality == "degraded" (first filter, D-05a)
   b) benchmark.metrics.is_two_column(pdf_path) (second filter, D-05b)
   A paper is flagged two-column if BOTH signals agree OR parse_quality=degraded AND
   is_two_column returns True. (Conservative: both must confirm to avoid false positives.)
3. Stratify across source (arxiv/pmc) and subject (cs.LG/AI/CV/CL/stat.ML/pmc-dl).
4. Enforce exactly 150 total, >=30 two-column — abort if corpus can't satisfy.
5. Write benchmark/sample.json (UTF-8, indent=2).
"""

import argparse
import json
import os
import random
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import SessionLocal
from app.models import Paper, PaperSource

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data"))
SAMPLE_PATH = os.path.join(os.path.dirname(__file__), "sample.json")
TARGET_TOTAL = 150
MIN_TWO_COLUMN = 30
RANDOM_SEED = 42  # reproducibility


def _resolve_asset_path(asset_path: str) -> str:
    if os.path.isabs(asset_path):
        return asset_path
    return os.path.abspath(os.path.join(DATA_DIR, asset_path))


def _infer_subject(paper: Paper) -> str:
    """Derive subject tag from content metadata or default buckets.

    Paper.content may have categories from OAI metadata. Fallback by source_type.
    """
    content = paper.content or {}
    cats = content.get("categories") or content.get("subjects") or []
    if isinstance(cats, str):
        cats = [cats]
    priority = ["cs.LG", "cs.AI", "cs.CV", "cs.CL", "stat.ML"]
    for p in priority:
        for c in cats:
            if p in str(c):
                return p
    if paper.pmc_id:
        return "pmc-dl"
    return "other"


def _classify_column(paper: Paper, pdf_path: str) -> str:
    """Return 'two' if parse_quality=degraded AND is_two_column(pdf_path) True; else 'single'."""
    from benchmark.metrics import is_two_column  # type: ignore[import]
    quality_degraded = (paper.parse_quality == "degraded")
    try:
        pymupdf_two = is_two_column(pdf_path, sample_pages=3)
    except Exception:
        pymupdf_two = False
    # D-05: parse_quality flag FIRST, PyMuPDF confirms. Both must agree to classify two-column.
    if quality_degraded and pymupdf_two:
        return "two"
    # Also accept strong PyMuPDF signal alone (papers with parse_quality=ok can still be two-column
    # if parser handled layout — e.g. MinerU recovered despite layout).
    if pymupdf_two:
        return "two"
    return "single"


def _candidate_papers(session) -> list:
    """Return list of {paper, pdf_path, source_type} dicts for all candidate papers.

    Criteria (D-06): successfully parsed (PaperSource.parse_status=success) AND has a PDF asset.
    """
    q = (
        session.query(Paper, PaperSource)
        .join(PaperSource, PaperSource.canonical_id == Paper.canonical_id)
        .filter(PaperSource.parse_status == "success")
        .filter(PaperSource.source_type.in_([
            "arxiv_pdf", "pmc_pdf", "pdf", "arxiv_tar", "arxiv", "pmc_jats", "pmc",
        ]))
    )
    seen = set()
    candidates = []
    for paper, _ in q.yield_per(200):
        if paper.canonical_id in seen:
            continue
        seen.add(paper.canonical_id)
        # Need an actual PDF for is_two_column — find PDF source
        pdf_ps = (
            session.query(PaperSource)
            .filter(PaperSource.canonical_id == paper.canonical_id)
            .filter(PaperSource.source_type.in_(["arxiv_pdf", "pmc_pdf", "pdf"]))
            .first()
        )
        if not pdf_ps or not pdf_ps.asset_path:
            continue
        pdf_path = _resolve_asset_path(pdf_ps.asset_path)
        if not os.path.exists(pdf_path):
            continue
        source_type = "arxiv" if paper.arxiv_id else ("pmc" if paper.pmc_id else "other")
        candidates.append({
            "paper": paper,
            "pdf_path": pdf_path,
            "source_type": source_type,
            "pdf_source_type": pdf_ps.source_type,
        })
    return candidates


def _stratified_sample(
    candidates: list,
    target_total: int,
    min_two_column: int,
    rng: random.Random,
) -> list:
    """Stratify by source_type x subject x column_layout; enforce quotas."""
    classified = []
    for c in candidates:
        col = _classify_column(c["paper"], c["pdf_path"])
        subj = _infer_subject(c["paper"])
        classified.append({**c, "column_layout": col, "subject": subj})

    two_col = [c for c in classified if c["column_layout"] == "two"]
    single_col = [c for c in classified if c["column_layout"] == "single"]

    if len(two_col) < min_two_column:
        raise RuntimeError(
            f"Corpus has only {len(two_col)} two-column papers; need >={min_two_column}. "
            f"Abort per D-07."
        )

    # Step 1: sample exactly min_two_column two-column papers (proportional to subject)
    subj_counts_two = defaultdict(list)
    for c in two_col:
        subj_counts_two[c["subject"]].append(c)
    total_two = len(two_col)
    two_col_sample: list = []
    remaining_two = min_two_column
    for subj, group in sorted(subj_counts_two.items()):
        quota = max(1, round(min_two_column * len(group) / total_two)) if total_two else 0
        quota = min(quota, len(group), remaining_two)
        chosen = rng.sample(group, quota)
        two_col_sample.extend(chosen)
        remaining_two -= quota
    # Fill any shortfall from remaining two-column pool
    if remaining_two > 0:
        pool = [c for c in two_col if c not in two_col_sample]
        two_col_sample.extend(rng.sample(pool, min(remaining_two, len(pool))))

    # Step 2: sample single-column (and possibly extra two-column) to reach target_total
    remaining_slots = target_total - len(two_col_sample)
    if len(single_col) < remaining_slots:
        # Top up with extra two-column papers
        extra_two_pool = [c for c in two_col if c not in two_col_sample]
        shortfall = remaining_slots - len(single_col)
        if len(extra_two_pool) < shortfall:
            raise RuntimeError(
                f"Corpus has only {len(candidates)} papers; need >={target_total}. Abort."
            )
        extras = rng.sample(extra_two_pool, shortfall)
        single_sample = single_col + extras
    else:
        # Stratify single-column by source x subject
        key_fn = lambda c: (c["source_type"], c["subject"])
        buckets = defaultdict(list)
        for c in single_col:
            buckets[key_fn(c)].append(c)
        total_single = len(single_col)
        single_sample = []
        remaining_s = remaining_slots
        for _, group in sorted(buckets.items()):
            quota = max(1, round(remaining_slots * len(group) / total_single)) if total_single else 0
            quota = min(quota, len(group), remaining_s)
            single_sample.extend(rng.sample(group, quota))
            remaining_s -= quota
        if remaining_s > 0:
            pool = [c for c in single_col if c not in single_sample]
            single_sample.extend(rng.sample(pool, min(remaining_s, len(pool))))
        if len(single_sample) > remaining_slots:
            single_sample = single_sample[:remaining_slots]

    combined = two_col_sample + single_sample
    if len(combined) > target_total:
        combined = combined[:target_total]
    if len(combined) < target_total:
        raise RuntimeError(
            f"Stratification produced {len(combined)} papers; need {target_total}. Abort."
        )
    return combined


def _to_entry(c: dict) -> dict:
    paper = c["paper"]
    return {
        "paper_id": str(paper.canonical_id),
        "arxiv_id": paper.arxiv_id,
        "pmc_id": paper.pmc_id,
        "source_type": c["source_type"],
        "pdf_source_type": c["pdf_source_type"],
        "column_layout": c["column_layout"],
        "subject": c["subject"],
        "pdf_path": c["pdf_path"],
        "parse_source": paper.parse_source,
        "parse_quality": paper.parse_quality,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Stratified 150-paper benchmark sample selection.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None, help="Cap to N papers (smoke test)")
    parser.add_argument("--seed", type=int, default=RANDOM_SEED)
    args = parser.parse_args()

    target_total = args.limit or TARGET_TOTAL
    min_two = max(1, int(target_total * MIN_TWO_COLUMN / TARGET_TOTAL)) if args.limit else MIN_TWO_COLUMN

    rng = random.Random(args.seed)

    if args.dry_run:
        print(f"[select_sample] dry-run — no DB connection attempted")
        print(f"[select_sample] dry-run — target: {target_total} total, >={min_two} two-column")
        print(f"[select_sample] dry-run — sample.json will be written to {SAMPLE_PATH}")
        return 0

    session = SessionLocal()
    try:
        candidates = _candidate_papers(session)
        chosen = _stratified_sample(candidates, target_total, min_two, rng)
        entries = [_to_entry(c) for c in chosen]
        two_count = sum(1 for e in entries if e["column_layout"] == "two")
        if len(entries) != target_total:
            print(f"ERROR: got {len(entries)}, expected {target_total}", file=sys.stderr)
            return 1
        if two_count < min_two:
            print(f"ERROR: got {two_count} two-column, need >={min_two}", file=sys.stderr)
            return 1
        with open(SAMPLE_PATH, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, default=str)
        print(f"[select_sample] wrote {len(entries)} entries to {SAMPLE_PATH} ({two_count} two-column)")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
