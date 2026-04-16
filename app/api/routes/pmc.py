"""Route handlers for PMC endpoints.

Uses async def handlers with cache-aside pattern (D-14/D-15/D-17):
- Check Redis cache first; return cached JSON on hit.
- On miss: run sync DB query in asyncio.to_thread, cache result, return.

Sync SessionLocal DB calls are wrapped in asyncio.to_thread() so the event
loop remains free during DB I/O (per D-23 — no asyncpg/AsyncSession introduced).
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.cache import PAPER_TTL, get_cached, paper_cache_key, set_cache
from app.api.deps import get_db, get_redis
from app.api.schemas import HeadResponse, FullResponse
from app.api.routes.arxiv import _paper_to_head
from app.models import Paper, IdMap
from redis.asyncio import Redis

router = APIRouter()


# ---------------------------------------------------------------------------
# ID resolution helper
# ---------------------------------------------------------------------------

def resolve_pmc_id(db: Session, pmc_id: str) -> Paper | None:
    """Resolve PMC ID to Paper, checking id_map as fallback."""
    paper = db.query(Paper).filter(Paper.pmc_id == pmc_id).first()
    if paper:
        return paper
    row = db.query(IdMap).filter(IdMap.pmc_id == pmc_id).first()
    if row:
        return db.query(Paper).filter(Paper.canonical_id == row.canonical_id).first()
    return None


# ---------------------------------------------------------------------------
# PMC endpoints
# ---------------------------------------------------------------------------

@router.get("/pmc/{pmc_id}/head", response_model=HeadResponse)
async def pmc_head(
    pmc_id: str,
    db: Session = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    """API-06: Return metadata (head) for a PMC paper."""
    paper = await asyncio.to_thread(resolve_pmc_id, db, pmc_id)
    if paper is None:
        return JSONResponse(
            status_code=404,
            content={"error": "not_found", "message": f"Paper {pmc_id} not found"},
        )
    cache_key = paper_cache_key(str(paper.canonical_id), "head")
    cached = await get_cached(redis, cache_key)
    if cached is not None:
        return cached
    response_dict = _paper_to_head(paper)
    await set_cache(redis, cache_key, response_dict, PAPER_TTL)
    return HeadResponse(**response_dict)


@router.get("/pmc/{pmc_id}/full", response_model=FullResponse)
async def pmc_full(
    pmc_id: str,
    db: Session = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    """API-07: Return full paper data for a PMC paper."""
    paper = await asyncio.to_thread(resolve_pmc_id, db, pmc_id)
    if paper is None:
        return JSONResponse(
            status_code=404,
            content={"error": "not_found", "message": f"Paper {pmc_id} not found"},
        )
    cache_key = paper_cache_key(str(paper.canonical_id), "full")
    cached = await get_cached(redis, cache_key)
    if cached is not None:
        return cached
    content = paper.content or {}
    head = _paper_to_head(paper)
    response_dict = {
        **head,
        "sections": content.get("sections", []),
        "citations": content.get("citations", []),
        "ref_entries": content.get("ref_entries", {}),
        "back_matter": content.get("back_matter", []),
    }
    await set_cache(redis, cache_key, response_dict, PAPER_TTL)
    return FullResponse(**response_dict)
