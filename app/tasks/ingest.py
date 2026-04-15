"""Celery tasks for paper ingestion and asset download.

Tasks:
    ingest_paper   — trigger metadata harvest for an arXiv set or PMC date range
    download_asset — download e-print asset for one arXiv paper and update PaperSource
"""

import asyncio

from celery import shared_task

from app.crawler.arxiv_assets import download_eprint_asset
from app.crawler.arxiv_oai import harvest_arxiv_set
from app.db import SessionLocal
from app.models import Paper, PaperSource


@shared_task(
    bind=True,
    name="app.tasks.ingest.ingest_paper",
    max_retries=3,
    time_limit=300,
    soft_time_limit=280,
    default_retry_delay=30,
)
def ingest_paper(self, paper_id: str, source: str = "arxiv") -> dict:
    """Harvest metadata for one arXiv set or a PMC date range.

    Args:
        paper_id: For arXiv: the set name (e.g. "cs:cs:LG").
                  For PMC: the from_date (e.g. "2024-01-01").
        source:   "arxiv" or "pmc".

    Returns:
        Status dict with harvested record count.
    """
    try:
        if source == "arxiv":
            count = asyncio.run(harvest_arxiv_set(paper_id))
            return {"status": "success", "source": source, "set": paper_id, "records": count}
        elif source == "pmc":
            # Lazy import so pmc_oai.py can be created independently in 02-03
            # without causing an ImportError at module load time.
            from app.crawler.pmc_oai import harvest_pmc  # noqa: PLC0415
            count = harvest_pmc(from_date=paper_id)
            return {"status": "success", "source": source, "records": count}
        else:
            return {"status": "unknown_source", "source": source}
    except Exception as exc:
        self.retry(exc=exc)


@shared_task(
    bind=True,
    name="app.tasks.ingest.download_asset",
    max_retries=3,
    time_limit=120,
    soft_time_limit=110,
    default_retry_delay=15,
)
def download_asset(self, paper_id: str, source_type: str) -> dict:
    """Download e-print asset for *paper_id* and update PaperSource row.

    Args:
        paper_id:    Canonical arXiv ID (no version suffix).
        source_type: Currently only "arxiv" is handled; kept for future sources.

    Returns:
        Status dict with asset_path and detected source_type.
    """
    try:
        asset_path, detected_type = asyncio.run(download_eprint_asset(paper_id))

        session = SessionLocal()
        try:
            paper = session.query(Paper).filter(Paper.arxiv_id == paper_id).first()
            if paper:
                ps = (
                    session.query(PaperSource)
                    .filter(
                        PaperSource.canonical_id == paper.canonical_id,
                        PaperSource.source_type == "arxiv",
                    )
                    .first()
                )
                if ps:
                    ps.asset_path = asset_path
                    ps.source_type = detected_type
                    session.commit()
        finally:
            session.close()

        return {
            "status": "success",
            "paper_id": paper_id,
            "asset_path": asset_path,
            "source_type": detected_type,
        }
    except Exception as exc:
        self.retry(exc=exc)
