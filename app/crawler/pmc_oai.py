"""PMC OAI-PMH crawler using sickle.

Two-phase approach:
  Phase 1 — harvest_pmc_ids: collect PMC IDs quickly with pmc_fm (front-matter only),
             persisting the resumptionToken after every page boundary.
  Phase 2 — process_pmc_record: filter by DL keywords, dedup, insert Paper + PaperSource rows.
"""

import logging
import re
from sickle import Sickle
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.crawler.utils import (
    save_crawl_state,
    load_crawl_state,
    is_already_ingested,
    PMC_OAI_BASE,
)
from app.models import Paper, PaperSource
from app.db import SessionLocal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Deep-learning keyword filter
# ---------------------------------------------------------------------------

DL_KEYWORDS = re.compile(
    r"deep learning|neural network|transformer|convolutional|recurrent neural|"
    r"attention mechanism|generative adversarial|reinforcement learning|"
    r"language model|BERT|GPT|diffusion model|graph neural",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_pmc_id(identifier: str) -> str:
    """Extract the PMC ID from an OAI identifier string.

    Example:
        "oai:pubmedcentral.nih.gov:PMC1234567" -> "PMC1234567"
    """
    return identifier.split(":")[-1]


def _is_dl_paper(title: str | None, abstract: str | None) -> bool:
    """Return True if the paper title or abstract contains DL keywords."""
    if title is None and abstract is None:
        return False
    combined = " ".join(part for part in [title, abstract] if part)
    return bool(DL_KEYWORDS.search(combined))


def _get_metadata_field(metadata: dict, *keys: str) -> str | None:
    """Try multiple key names (different OAI metadata formats) and return the first non-empty value."""
    for key in keys:
        val = metadata.get(key)
        if val:
            # sickle returns lists for most fields
            if isinstance(val, list):
                return val[0] if val else None
            return val
    return None


# ---------------------------------------------------------------------------
# Phase 1: ID harvest
# ---------------------------------------------------------------------------


def harvest_pmc_ids(from_date: str = "2020-01-01", max_records: int = 50000) -> list[str]:
    """Harvest PMC IDs from the pmc-open set using pmc_fm (front matter only).

    Checkpoints the resumptionToken after every page boundary (10 records/page).
    Returns a list of PMC ID strings.
    """
    session = SessionLocal()
    try:
        state = load_crawl_state(session, "pmc")
        resumption_token = state.get("resumption_token") if state else None

        sickle = Sickle(PMC_OAI_BASE, timeout=60)
        sickle.class_mapping["ListRecords"] = sickle.class_mapping["ListRecords"]

        if resumption_token:
            logger.info("PMC harvest: resuming from token %s", resumption_token)
            records = sickle.ListRecords(resumptionToken=resumption_token)
        else:
            logger.info("PMC harvest: starting fresh from %s", from_date)
            records = sickle.ListRecords(
                metadataPrefix="pmc_fm",
                set="pmc-open",
                **{"from": from_date},
            )

        pmc_ids: list[str] = []
        count = 0

        for record in records:
            if count >= max_records:
                logger.info("PMC harvest: reached max_records limit of %d", max_records)
                break

            # Extract PMC ID from the OAI identifier
            header = record.header
            identifier = header.identifier if hasattr(header, "identifier") else str(header)
            pmc_id = _extract_pmc_id(identifier)
            pmc_ids.append(pmc_id)
            count += 1

            # After every 10 records (one page boundary), persist the token
            if count % 10 == 0:
                token = getattr(records, "resumption_token", None)
                if token:
                    token_str = token.token if hasattr(token, "token") else str(token)
                    save_crawl_state(session, "pmc", token_str, record_count=10)
                    logger.debug("PMC harvest: checkpointed token after %d records", count)

            if count % 100 == 0:
                logger.info("PMC harvest: %d IDs collected", count)

        logger.info("PMC harvest complete: %d IDs collected", len(pmc_ids))
        return pmc_ids

    finally:
        session.close()


# ---------------------------------------------------------------------------
# Phase 2: Record processing
# ---------------------------------------------------------------------------


def process_pmc_record(
    session,
    pmc_id: str,
    title: str | None = None,
    abstract: str | None = None,
) -> bool:
    """Insert a Paper + PaperSource row for a PMC paper.

    Returns True if the paper was inserted, False if skipped (already ingested
    or not a DL paper).
    """
    # Dedup check
    if is_already_ingested(session, pmc_id=pmc_id):
        return False

    # DL keyword filter — only applies when we have title/abstract
    if title is not None or abstract is not None:
        if not _is_dl_paper(title, abstract):
            return False

    # Insert Paper row with ON CONFLICT DO NOTHING for safety
    # parse_status lives on PaperSource, not on Paper
    paper_stmt = (
        pg_insert(Paper)
        .values(
            pmc_id=pmc_id,
            title=title,
            abstract=abstract,
        )
        .on_conflict_do_nothing(index_elements=["pmc_id"])
    )
    session.execute(paper_stmt)

    # Fetch the canonical_id for the PaperSource FK
    from sqlalchemy import select
    paper_row = session.execute(
        select(Paper.canonical_id).where(Paper.pmc_id == pmc_id)
    ).first()
    if paper_row is None:
        # Conflict — already existed; skip PaperSource creation
        return False

    canonical_id = paper_row[0]

    # Insert PaperSource row
    source = PaperSource(
        canonical_id=canonical_id,
        source_type="pmc",
        parse_status="pending",
    )
    session.add(source)
    return True


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def harvest_pmc(from_date: str = "2020-01-01", max_records: int = 50000) -> int:
    """Harvest PMC open-access papers and insert DL papers into the database.

    Two-phase:
      1. Collect all PMC IDs (fast, with token checkpointing).
      2. For each ID, fetch pmc_fm metadata and process if it's a DL paper.

    Returns the total number of papers inserted.
    """
    session = SessionLocal()
    inserted = 0

    try:
        sickle = Sickle(PMC_OAI_BASE, timeout=60)

        state = load_crawl_state(session, "pmc")
        resumption_token = state.get("resumption_token") if state else None

        if resumption_token:
            records = sickle.ListRecords(resumptionToken=resumption_token)
        else:
            records = sickle.ListRecords(
                metadataPrefix="pmc_fm",
                set="pmc-open",
                **{"from": from_date},
            )

        count = 0

        for record in records:
            if count >= max_records:
                break

            # Extract PMC ID
            header = record.header
            identifier = header.identifier if hasattr(header, "identifier") else str(header)
            pmc_id = _extract_pmc_id(identifier)

            # Extract title/abstract from pmc_fm metadata (if available)
            metadata = record.metadata if hasattr(record, "metadata") else {}
            title = _get_metadata_field(metadata, "article-title", "dc:title", "title")
            abstract = _get_metadata_field(metadata, "abstract", "dc:description", "description")

            # Process the record
            if process_pmc_record(session, pmc_id, title, abstract):
                inserted += 1

            count += 1

            # Checkpoint after every page (10 records)
            if count % 10 == 0:
                token = getattr(records, "resumption_token", None)
                if token:
                    token_str = token.token if hasattr(token, "token") else str(token)
                    save_crawl_state(session, "pmc", token_str, record_count=10)

            # Commit every 50 records
            if count % 50 == 0:
                session.commit()
                logger.info("PMC ingest: processed %d records, inserted %d DL papers", count, inserted)

        # Final commit
        session.commit()
        logger.info("PMC ingest complete: %d DL papers inserted from %d records", inserted, count)
        return inserted

    finally:
        session.close()
