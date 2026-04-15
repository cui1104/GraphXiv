"""CLI entry point for running arXiv and PMC harvests.

Usage:
    python -m app.crawler.run_harvest --source arxiv --max-records 100
    python -m app.crawler.run_harvest --source pmc --max-records 100
    python -m app.crawler.run_harvest --source all --max-records 5000
    python -m app.crawler.run_harvest --status  # show crawl state
"""

import argparse
import asyncio
import logging
import sys

from sqlalchemy import func, select, text

from app.db import SessionLocal
from app.models import CrawlState, Paper, PaperSource

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def show_status() -> None:
    """Print current crawl state, paper counts, and source breakdown."""
    session = SessionLocal()
    try:
        # Total papers
        total_papers = session.execute(select(func.count()).select_from(Paper)).scalar_one()

        # Papers by source type
        arxiv_count = session.execute(
            select(func.count()).select_from(PaperSource).where(PaperSource.source_type == "arxiv")
        ).scalar_one()
        pmc_count = session.execute(
            select(func.count()).select_from(PaperSource).where(PaperSource.source_type == "pmc")
        ).scalar_one()

        # Papers pending parse
        pending_count = session.execute(
            select(func.count()).select_from(PaperSource).where(PaperSource.parse_status == "pending")
        ).scalar_one()

        print("=" * 60)
        print("HARVEST STATUS")
        print("=" * 60)
        print(f"Total papers:        {total_papers}")
        print(f"  arXiv sources:     {arxiv_count}")
        print(f"  PMC sources:       {pmc_count}")
        print(f"  Pending parse:     {pending_count}")
        print()

        # Crawl state rows
        crawl_rows = session.execute(select(CrawlState)).scalars().all()
        if crawl_rows:
            print(f"{'Source':<30} {'Records':>10} {'Token':>10} {'Last Harvested'}")
            print("-" * 80)
            for row in crawl_rows:
                token_indicator = "present" if row.resumption_token else "none"
                last_at = str(row.last_harvested_at)[:19] if row.last_harvested_at else "never"
                print(f"{row.source:<30} {row.record_count or 0:>10} {token_indicator:>10} {last_at}")
        else:
            print("No crawl state entries (harvest not yet started).")
        print("=" * 60)
    finally:
        session.close()


def run_arxiv(max_records: int, from_date: str) -> None:
    """Run the arXiv harvest (all 5 DL category sets sequentially)."""
    from app.crawler.arxiv_oai import harvest_all_arxiv

    logger.info(
        "Starting arXiv harvest: max_records=%d (applied per-page; full sets harvested), from_date=%s",
        max_records,
        from_date,
    )
    results = asyncio.run(harvest_all_arxiv(from_date=from_date))
    total = sum(results.values())
    print("arXiv harvest complete:")
    for set_name, count in results.items():
        print(f"  {set_name}: {count} new records")
    print(f"  Total new: {total}")


def run_pmc(max_records: int, from_date: str) -> None:
    """Run the PMC harvest."""
    from app.crawler.pmc_oai import harvest_pmc

    logger.info(
        "Starting PMC harvest: max_records=%d, from_date=%s",
        max_records,
        from_date,
    )
    count = harvest_pmc(from_date=from_date, max_records=max_records)
    print(f"PMC harvest complete: {count} new DL papers inserted")


def main() -> None:
    """Parse CLI arguments and dispatch to the appropriate harvest function."""
    parser = argparse.ArgumentParser(
        description="Run arXiv and/or PMC harvests for the Research Knowledge Graph pipeline.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--source",
        choices=["arxiv", "pmc", "all"],
        help="Which source(s) to harvest. Required unless --status is used.",
    )
    parser.add_argument(
        "--max-records",
        type=int,
        default=10000,
        help="Maximum number of records to harvest (passed to PMC; arXiv harvests full pages).",
    )
    parser.add_argument(
        "--from-date",
        default="2020-01-01",
        help="ISO date lower bound for harvest (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print current crawl state and DB stats, then exit.",
    )

    args = parser.parse_args()

    if args.status:
        show_status()
        return

    if not args.source:
        parser.error("--source is required unless --status is used.")

    if args.source == "arxiv":
        run_arxiv(max_records=args.max_records, from_date=args.from_date)
    elif args.source == "pmc":
        run_pmc(max_records=args.max_records, from_date=args.from_date)
    elif args.source == "all":
        run_arxiv(max_records=args.max_records, from_date=args.from_date)
        run_pmc(max_records=args.max_records, from_date=args.from_date)


if __name__ == "__main__":
    main()
