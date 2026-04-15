"""Async arXiv e-print asset downloader.

Fetches e-print files from export.arxiv.org/e-print, routes by Content-Type
to the correct file extension and source_type classification.

Exports:
    download_eprint_asset — download one arXiv e-print and return (path, source_type)
"""

import logging
import os

import httpx
from aiolimiter import AsyncLimiter
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import get_settings
from app.crawler.utils import ARXIV_EPRINT_BASE, CONTENT_TYPE_TO_EXT, USER_AGENT

logger = logging.getLogger(__name__)
rate_limiter = AsyncLimiter(3, 1)


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=4, max=60),
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException)),
    reraise=True,
)
async def _fetch_asset(client: httpx.AsyncClient, url: str) -> httpx.Response:
    """Rate-limited, retried GET for an e-print asset."""
    async with rate_limiter:
        resp = await client.get(
            url,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            timeout=120.0,
        )
    resp.raise_for_status()
    return resp


async def download_eprint_asset(
    arxiv_id: str,
    client: httpx.AsyncClient | None = None,
) -> tuple[str, str]:
    """Download the e-print asset for *arxiv_id* and save it to disk.

    Args:
        arxiv_id:  Canonical arXiv ID (no version suffix), e.g. "2401.00001".
        client:    Optional existing httpx.AsyncClient; creates one if not provided.

    Returns:
        (asset_path, source_type) where source_type is one of:
        "latex" (for eprint tar/gz), "pdf" (for PDF), or "unknown" (fallback).
    """
    url = f"{ARXIV_EPRINT_BASE}/{arxiv_id}"
    settings = get_settings()

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()

    try:
        resp = await _fetch_asset(client, url)

        ct = resp.headers.get("content-type", "").split(";")[0].strip()
        ext = CONTENT_TYPE_TO_EXT.get(ct, ".bin")

        # Classify source type
        if "eprint" in ct:
            source_type = "latex"
        elif ct == "application/pdf":
            source_type = "pdf"
        else:
            source_type = "unknown"
            logger.warning(
                "download_eprint_asset: unexpected content-type %r for %s — saving as .bin",
                ct,
                arxiv_id,
            )

        # Build destination path and create parent dirs
        asset_dir = os.path.join(settings.data_dir, "assets", "arxiv")
        os.makedirs(asset_dir, exist_ok=True)
        asset_path = os.path.join(asset_dir, f"{arxiv_id}{ext}")

        with open(asset_path, "wb") as fh:
            fh.write(resp.content)

        logger.info(
            "Downloaded %s: %s -> %s (%s)",
            arxiv_id,
            ct,
            ext,
            source_type,
        )
        return asset_path, source_type

    finally:
        if own_client:
            await client.aclose()
