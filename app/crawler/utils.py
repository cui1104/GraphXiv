"""Shared utilities for all crawlers: ID normalization, crawl state persistence, dedup check."""

import logging
import re

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models import CrawlState, Paper

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ARXIV_OAI_BASE = "https://oaipmh.arxiv.org/oai"
ARXIV_EPRINT_BASE = "https://export.arxiv.org/e-print"
ARXIV_SETS = ["cs:cs:LG", "cs:cs:AI", "cs:cs:CV", "cs:cs:CL", "stat:stat:ML"]
PMC_OAI_BASE = "https://pmc.ncbi.nlm.nih.gov/api/oai/v1/mh/"
USER_AGENT = "DATS5990-ResearchKG/1.0 (mailto:hc1408@georgetown.edu)"
CONTENT_TYPE_TO_EXT = {
    "application/x-eprint-tar": ".tar.gz",
    "application/x-eprint": ".tar.gz",
    "application/pdf": ".pdf",
    "application/postscript": ".ps.gz",
}

# ---------------------------------------------------------------------------
# arXiv ID normalization
# ---------------------------------------------------------------------------

# New format (post April 2007): YYMM.NNNNN[vN]
_NEW_ID = re.compile(r"^(\d{4}\.\d{4,5})(v\d+)?$", re.IGNORECASE)
# Old format (pre April 2007): archive/YYMMNNNvN
_OLD_ID = re.compile(r"^([a-z\-]+/\d{7})(v\d+)?$", re.IGNORECASE)


def normalize_arxiv_id(raw_id: str) -> str:
    """Strip version suffix from an arXiv ID and return the canonical form.

    Handles:
    - New format: 2401.00001v2  -> 2401.00001
    - Old format: hep-th/9901001v1 -> hep-th/9901001
    - "arXiv:" prefix: arXiv:2401.00001v3 -> 2401.00001
    - No version: 2401.00001 -> 2401.00001 (unchanged)
    - Unknown format: returned as-is with a warning
    """
    raw_id = raw_id.strip()
    if raw_id.lower().startswith("arxiv:"):
        raw_id = raw_id[6:]
    m = _NEW_ID.match(raw_id) or _OLD_ID.match(raw_id)
    if m:
        return m.group(1)
    logger.warning("normalize_arxiv_id: unknown format %r — returning as-is", raw_id)
    return raw_id


# ---------------------------------------------------------------------------
# Crawl state persistence
# ---------------------------------------------------------------------------


def save_crawl_state(
    session,
    source: str,
    token: str | None,
    record_count: int = 0,
) -> None:
    """Upsert a row in crawl_state keyed by source.

    Uses PostgreSQL ON CONFLICT DO UPDATE so the call is idempotent and safe
    to invoke after every OAI-PMH page.
    """
    stmt = (
        pg_insert(CrawlState)
        .values(
            source=source,
            resumption_token=token,
            record_count=record_count,
            last_harvested_at=func.now(),
        )
        .on_conflict_do_update(
            index_elements=["source"],
            set_={
                "resumption_token": token,
                "record_count": CrawlState.record_count + record_count,
                "last_harvested_at": func.now(),
            },
        )
    )
    session.execute(stmt)
    session.commit()


def load_crawl_state(session, source: str) -> dict | None:
    """Return the persisted crawl state for *source*, or None if not found.

    Returns a dict with keys: resumption_token, record_count, last_harvested_at.
    """
    row = session.execute(
        select(CrawlState).where(CrawlState.source == source)
    ).scalar_one_or_none()
    if row is None:
        return None
    return {
        "resumption_token": row.resumption_token,
        "record_count": row.record_count,
        "last_harvested_at": row.last_harvested_at,
    }


# ---------------------------------------------------------------------------
# Deduplication check
# ---------------------------------------------------------------------------


def is_already_ingested(
    session,
    arxiv_id: str | None = None,
    pmc_id: str | None = None,
) -> bool:
    """Return True if a paper with the given identifier already exists in *papers*.

    At least one of arxiv_id or pmc_id must be supplied.
    """
    if arxiv_id is not None:
        exists = session.execute(
            select(Paper.canonical_id).where(Paper.arxiv_id == arxiv_id)
        ).first()
        return exists is not None
    if pmc_id is not None:
        exists = session.execute(
            select(Paper.canonical_id).where(Paper.pmc_id == pmc_id)
        ).first()
        return exists is not None
    return False
