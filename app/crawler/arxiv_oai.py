"""Async arXiv OAI-PMH metadata harvester.

Exports:
    harvest_arxiv_set   — harvest one arXiv category set
    harvest_all_arxiv   — harvest all 5 DL category sets

Rate limited to 3 req/sec (arXiv TOS). Supports crash recovery via
resumptionToken persistence to crawl_state after every page.
"""

import logging
import uuid

import httpx
from aiolimiter import AsyncLimiter
from lxml import etree
from sqlalchemy.dialects.postgresql import insert as pg_insert
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.crawler.utils import (
    ARXIV_OAI_BASE,
    ARXIV_SETS,
    USER_AGENT,
    is_already_ingested,
    load_crawl_state,
    normalize_arxiv_id,
    save_crawl_state,
)
from app.db import SessionLocal
from app.models import Paper, PaperSource

logger = logging.getLogger(__name__)

RATE_LIMITER = AsyncLimiter(3, 1)  # 3 requests per 1 second

OAI_NS = {"oai": "http://www.openarchives.org/OAI/2.0/"}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=4, max=60),
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException)),
    reraise=True,
)
async def _fetch_page(client: httpx.AsyncClient, params: dict) -> httpx.Response:
    """Fetch one OAI-PMH page with rate limiting and retry."""
    async with RATE_LIMITER:
        resp = await client.get(
            ARXIV_OAI_BASE,
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=30.0,
            follow_redirects=True,
        )
    resp.raise_for_status()
    return resp


def _parse_arxiv_records(xml_text: str) -> list[dict]:
    """Parse arXivRaw XML and return a list of metadata dicts.

    arXivRaw metadata elements are NOT in the OAI namespace — they use either
    no namespace or the arXiv-specific namespace.  We fall back to tag-local
    name matching to be robust against namespace variation.
    """
    try:
        root = etree.fromstring(xml_text.encode())
    except etree.XMLSyntaxError as exc:
        logger.warning("_parse_arxiv_records: XML parse error: %s", exc)
        return []

    records = root.findall(".//oai:record", namespaces=OAI_NS)
    results = []
    for record in records:
        try:
            # arXivRaw metadata lives inside <metadata><arXivRaw>...</arXivRaw></metadata>
            # The inner element may be namespace-qualified or bare — use local-name xpath.
            meta_elem = record.find(".//{*}arXivRaw")
            if meta_elem is None:
                meta_elem = record.find(".//arXivRaw")

            def _text(tag: str, _meta: object = meta_elem) -> str | None:
                """Extract text of first child with matching local name."""
                if _meta is None:
                    return None
                # Try namespace-wildcard first (handles any namespace including OAI)
                el = _meta.find(f"{{*}}{tag}")
                if el is None:
                    el = _meta.find(tag)
                if el is not None and el.text:
                    return el.text.strip()
                return None

            raw_id = _text("id")
            if not raw_id:
                logger.debug("_parse_arxiv_records: skipping record with no id")
                continue

            arxiv_id = normalize_arxiv_id(raw_id)

            # Parse year from created date (first 4 chars of "YYYY-MM-DD")
            created_str = _text("created") or ""
            year: int | None = None
            if len(created_str) >= 4 and created_str[:4].isdigit():
                year = int(created_str[:4])

            results.append(
                {
                    "arxiv_id": arxiv_id,
                    "title": _text("title"),
                    "abstract": _text("abstract"),
                    "authors": _text("authors"),
                    "categories": _text("categories"),
                    "doi": _text("doi"),
                    "year": year,
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("_parse_arxiv_records: failed to parse record: %s", exc)
            continue

    return results


def _extract_resumption_token(xml_text: str) -> str | None:
    """Extract OAI-PMH resumptionToken text from a ListRecords response.

    Post-March 2025 arXiv tokens carry NO completeListSize or cursor attributes.
    Returns None when the token element is missing or empty (harvest complete).
    """
    try:
        root = etree.fromstring(xml_text.encode())
    except etree.XMLSyntaxError as exc:
        logger.warning("_extract_resumption_token: XML parse error: %s", exc)
        return None

    token_elem = root.find(".//oai:resumptionToken", namespaces=OAI_NS)
    if token_elem is not None and token_elem.text and token_elem.text.strip():
        return token_elem.text.strip()
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def harvest_arxiv_set(set_name: str, from_date: str = "2020-01-01") -> int:
    """Harvest one arXiv category set via OAI-PMH ListRecords.

    Resumes from the last saved resumptionToken if one exists in crawl_state.
    Enqueues a download_asset Celery task for each newly inserted paper.

    Args:
        set_name: arXiv set in colon format, e.g. "cs:cs:LG".
        from_date: ISO date lower bound for harvest (ignored when resuming).

    Returns:
        Total number of new papers inserted in this run.
    """
    session = SessionLocal()
    total_new = 0

    try:
        state_key = f"arxiv:{set_name}"
        crawl_state = load_crawl_state(session, state_key)
        existing_token = crawl_state.get("resumption_token") if crawl_state else None

        if existing_token:
            params: dict = {"verb": "ListRecords", "resumptionToken": existing_token}
            logger.info("harvest_arxiv_set: resuming %s from saved token", set_name)
        else:
            params = {
                "verb": "ListRecords",
                "set": set_name,
                "metadataPrefix": "arXivRaw",
                "from": from_date,
            }
            logger.info("harvest_arxiv_set: starting fresh harvest of %s from %s", set_name, from_date)

        async with httpx.AsyncClient() as client:
            while True:
                resp = await _fetch_page(client, params)
                xml_text = resp.text

                records = _parse_arxiv_records(xml_text)
                new_records: list[dict] = []

                for record in records:
                    arxiv_id = record["arxiv_id"]
                    if is_already_ingested(session, arxiv_id=arxiv_id):
                        continue

                    # Upsert Paper row — handles v2 re-ingestion (INGEST-05)
                    stmt = (
                        pg_insert(Paper)
                        .values(
                            canonical_id=uuid.uuid4(),
                            arxiv_id=arxiv_id,
                            title=record.get("title"),
                            abstract=record.get("abstract"),
                            year=record.get("year"),
                            doi=record.get("doi"),
                        )
                        .on_conflict_do_update(
                            index_elements=["arxiv_id"],
                            set_={
                                "title": record.get("title"),
                                "abstract": record.get("abstract"),
                            },
                        )
                        .returning(Paper.canonical_id)
                    )
                    result = session.execute(stmt)
                    row = result.fetchone()
                    canonical_id = row[0] if row else None

                    if canonical_id is not None:
                        paper_source = PaperSource(
                            canonical_id=canonical_id,
                            source_type="arxiv",
                            parse_status="pending",
                        )
                        session.add(paper_source)
                        session.flush()

                        # Enqueue asset download after each new paper insert (INGEST-02)
                        # Lazy import to avoid circular import at module level
                        from app.tasks.ingest import download_asset  # noqa: PLC0415
                        download_asset.apply_async(
                            args=[arxiv_id, "arxiv"],
                            queue="fast",
                        )

                        new_records.append(record)

                session.commit()
                total_new += len(new_records)

                token = _extract_resumption_token(xml_text)
                save_crawl_state(session, state_key, token, record_count=len(new_records))

                logger.info(
                    "Set %s: page done, %d new records, token=%s",
                    set_name,
                    len(new_records),
                    "present" if token else "none",
                )

                if token is None:
                    logger.info("harvest_arxiv_set: harvest complete for %s, total new=%d", set_name, total_new)
                    break

                params = {"verb": "ListRecords", "resumptionToken": token}

    finally:
        session.close()

    return total_new


async def harvest_all_arxiv(from_date: str = "2020-01-01") -> dict[str, int]:
    """Harvest all 5 DL category sets from arXiv OAI-PMH.

    Runs sets sequentially (not in parallel) to respect the rate limiter.

    Args:
        from_date: ISO date lower bound for all sets.

    Returns:
        Dict mapping set_name -> count of new records inserted.
    """
    results: dict[str, int] = {}
    for set_name in ARXIV_SETS:
        count = await harvest_arxiv_set(set_name, from_date=from_date)
        results[set_name] = count
        logger.info("harvest_all_arxiv: %s -> %d new records", set_name, count)
    return results
