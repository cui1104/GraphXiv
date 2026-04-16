"""Route handlers for all arXiv endpoints.

Uses async def handlers with cache-aside pattern (D-14/D-15/D-17):
- Check Redis cache first; return cached JSON on hit.
- On miss: run sync DB query in asyncio.to_thread, cache result, return.

Sync SessionLocal DB calls are wrapped in asyncio.to_thread() so the event
loop remains free during DB I/O (per D-23 — no asyncpg/AsyncSession introduced).
ID resolution strips version suffix (e.g., 2401.00001v2 -> 2401.00001)
and falls back to id_map table lookup.
"""
from __future__ import annotations

import asyncio
import re

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.cache import (
    PAPER_TTL,
    get_cached,
    paper_cache_key,
    set_cache,
)
from app.api.deps import get_db, get_redis
from app.api.schemas import (
    HeadResponse,
    SectionsResponse,
    FullResponse,
    ReferencesResponse,
    ReferenceItem,
    CitedByResponse,
    CitedByItem,
    RelatedResponse,
    RelatedItem,
)
from app.models import Paper, IdMap, PaperCitation
from app.tasks.normalize import _build_src_url
from redis.asyncio import Redis

router = APIRouter()

# ---------------------------------------------------------------------------
# ID resolution helpers
# ---------------------------------------------------------------------------

ARXIV_VERSION_RE = re.compile(r"v\d+$", re.IGNORECASE)


def strip_arxiv_version(arxiv_id: str) -> str:
    """Strip version suffix from arXiv ID (e.g. 2401.00001v2 -> 2401.00001)."""
    return ARXIV_VERSION_RE.sub("", arxiv_id)


def resolve_arxiv_id(db: Session, arxiv_id: str) -> Paper | None:
    """Resolve arXiv ID to Paper, stripping version suffix and checking id_map."""
    clean_id = strip_arxiv_version(arxiv_id)
    paper = db.query(Paper).filter(Paper.arxiv_id == clean_id).first()
    if paper:
        return paper
    row = db.query(IdMap).filter(IdMap.arxiv_id == clean_id).first()
    if row:
        return db.query(Paper).filter(Paper.canonical_id == row.canonical_id).first()
    return None


# ---------------------------------------------------------------------------
# Paper-to-response helpers
# ---------------------------------------------------------------------------

def _paper_to_head(paper: Paper) -> dict:
    """Extract HeadResponse fields from Paper ORM object."""
    content = paper.content or {}
    return {
        "paper_id": str(paper.canonical_id),
        "arxiv_id": paper.arxiv_id,
        "pmc_id": paper.pmc_id,
        "doi": paper.doi,
        "title": paper.title,
        "abstract": paper.abstract,
        "tldr": paper.tldr,
        "authors": content.get("authors", []),
        "year": paper.year,
        "venue": paper.venue,
        "src_url": _build_src_url(paper),
        "token_count": paper.token_count or 0,
        "parse_source": paper.parse_source,
    }


# ---------------------------------------------------------------------------
# arXiv endpoints
# ---------------------------------------------------------------------------

@router.get("/arxiv/{arxiv_id}/head", response_model=HeadResponse)
async def arxiv_head(
    arxiv_id: str,
    db: Session = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    """API-01: Return metadata (head) for an arXiv paper."""
    paper = await asyncio.to_thread(resolve_arxiv_id, db, arxiv_id)
    if paper is None:
        return JSONResponse(
            status_code=404,
            content={"error": "not_found", "message": f"Paper {arxiv_id} not found"},
        )
    cache_key = paper_cache_key(str(paper.canonical_id), "head")
    cached = await get_cached(redis, cache_key)
    if cached is not None:
        return cached
    response_dict = _paper_to_head(paper)
    await set_cache(redis, cache_key, response_dict, PAPER_TTL)
    return HeadResponse(**response_dict)


@router.get("/arxiv/{arxiv_id}/brief", response_model=HeadResponse)
async def arxiv_brief(
    arxiv_id: str,
    db: Session = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    """API-02: Return brief metadata (same shape as head) for an arXiv paper."""
    paper = await asyncio.to_thread(resolve_arxiv_id, db, arxiv_id)
    if paper is None:
        return JSONResponse(
            status_code=404,
            content={"error": "not_found", "message": f"Paper {arxiv_id} not found"},
        )
    cache_key = paper_cache_key(str(paper.canonical_id), "brief")
    cached = await get_cached(redis, cache_key)
    if cached is not None:
        return cached
    response_dict = _paper_to_head(paper)
    await set_cache(redis, cache_key, response_dict, PAPER_TTL)
    return HeadResponse(**response_dict)


@router.get("/arxiv/{arxiv_id}/sections", response_model=SectionsResponse)
async def arxiv_sections(
    arxiv_id: str,
    db: Session = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    """API-03: Return sections array for an arXiv paper."""
    paper = await asyncio.to_thread(resolve_arxiv_id, db, arxiv_id)
    if paper is None:
        return JSONResponse(
            status_code=404,
            content={"error": "not_found", "message": f"Paper {arxiv_id} not found"},
        )
    cache_key = paper_cache_key(str(paper.canonical_id), "sections")
    cached = await get_cached(redis, cache_key)
    if cached is not None:
        return cached
    content = paper.content or {}
    sections = content.get("sections", [])
    response_dict = {
        "paper_id": str(paper.canonical_id),
        "title": paper.title,
        "sections": sections,
        "token_count": paper.token_count or 0,
    }
    await set_cache(redis, cache_key, response_dict, PAPER_TTL)
    return SectionsResponse(**response_dict)


@router.get("/arxiv/{arxiv_id}/full", response_model=FullResponse)
async def arxiv_full(
    arxiv_id: str,
    db: Session = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    """API-04: Return full paper data (head + sections + citations + ref_entries)."""
    paper = await asyncio.to_thread(resolve_arxiv_id, db, arxiv_id)
    if paper is None:
        return JSONResponse(
            status_code=404,
            content={"error": "not_found", "message": f"Paper {arxiv_id} not found"},
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


@router.get("/arxiv/{arxiv_id}/references", response_model=ReferencesResponse)
async def arxiv_references(
    arxiv_id: str,
    db: Session = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    """API-11: Return outgoing references (citations) for an arXiv paper."""
    paper = await asyncio.to_thread(resolve_arxiv_id, db, arxiv_id)
    if paper is None:
        return JSONResponse(
            status_code=404,
            content={"error": "not_found", "message": f"Paper {arxiv_id} not found"},
        )
    cid = paper.canonical_id
    cache_key = paper_cache_key(str(cid), "references")
    cached = await get_cached(redis, cache_key)
    if cached is not None:
        return cached

    def _fetch_references():
        sql = text("""
            SELECT pc.target_arxiv_id, pc.target_doi, pc.context_text,
                   p.canonical_id, p.title, p.abstract, p.year, p.arxiv_id,
                   p.pmc_id, p.doi, p.tldr, p.token_count
            FROM paper_citations pc
            LEFT JOIN papers p ON p.canonical_id = pc.target_paper_id
            WHERE pc.source_paper_id = :cid
        """)
        return db.execute(sql, {"cid": str(cid)}).fetchall()

    rows = await asyncio.to_thread(_fetch_references)
    references = [
        ReferenceItem(
            target_arxiv_id=row.target_arxiv_id,
            target_doi=row.target_doi,
            context_text=row.context_text,
            in_corpus=row.canonical_id is not None,
            paper_id=str(row.canonical_id) if row.canonical_id else None,
            title=row.title,
            abstract=row.abstract,
            year=row.year,
            arxiv_id=row.arxiv_id,
            pmc_id=row.pmc_id,
            doi=row.doi,
            tldr=row.tldr,
            token_count=row.token_count,
        )
        for row in rows
    ]
    response_dict = {
        "paper_id": str(cid),
        "references": [r.model_dump() for r in references],
    }
    await set_cache(redis, cache_key, response_dict, PAPER_TTL)
    return ReferencesResponse(paper_id=str(cid), references=references)


@router.get("/arxiv/{arxiv_id}/cited_by", response_model=CitedByResponse)
async def arxiv_cited_by(
    arxiv_id: str,
    db: Session = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    """API-12: Return papers that cite this arXiv paper."""
    paper = await asyncio.to_thread(resolve_arxiv_id, db, arxiv_id)
    if paper is None:
        return JSONResponse(
            status_code=404,
            content={"error": "not_found", "message": f"Paper {arxiv_id} not found"},
        )
    cid = paper.canonical_id
    cache_key = paper_cache_key(str(cid), "cited_by")
    cached = await get_cached(redis, cache_key)
    if cached is not None:
        return cached

    def _fetch_cited_by():
        sql = text("""
            SELECT p.canonical_id, p.title, p.abstract, p.arxiv_id, p.pmc_id,
                   p.doi, p.tldr, p.token_count, p.year, pc.context_text
            FROM paper_citations pc
            JOIN papers p ON p.canonical_id = pc.source_paper_id
            WHERE pc.target_paper_id = :cid
        """)
        return db.execute(sql, {"cid": str(cid)}).fetchall()

    rows = await asyncio.to_thread(_fetch_cited_by)
    cited_by = [
        CitedByItem(
            paper_id=str(row.canonical_id),
            arxiv_id=row.arxiv_id,
            pmc_id=row.pmc_id,
            title=row.title,
            abstract=row.abstract,
            year=row.year,
            tldr=row.tldr,
            token_count=row.token_count,
            context_text=row.context_text,
        )
        for row in rows
    ]
    response_dict = {
        "paper_id": str(cid),
        "cited_by": [c.model_dump() for c in cited_by],
    }
    await set_cache(redis, cache_key, response_dict, PAPER_TTL)
    return CitedByResponse(paper_id=str(cid), cited_by=cited_by)


@router.get("/arxiv/{arxiv_id}/related", response_model=RelatedResponse)
async def arxiv_related(
    arxiv_id: str,
    limit: int = 20,
    db: Session = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    """API-13: Return co-cited papers (related papers) ranked by co-citation count."""
    paper = await asyncio.to_thread(resolve_arxiv_id, db, arxiv_id)
    if paper is None:
        return JSONResponse(
            status_code=404,
            content={"error": "not_found", "message": f"Paper {arxiv_id} not found"},
        )
    cid = paper.canonical_id
    cache_key = paper_cache_key(str(cid), "related")
    cached = await get_cached(redis, cache_key)
    if cached is not None:
        return cached

    def _fetch_related():
        sql = text("""
            SELECT p.canonical_id, p.title, p.abstract, p.arxiv_id, p.pmc_id,
                   p.doi, p.tldr, p.token_count, p.year,
                   COUNT(*) AS co_citation_count
            FROM paper_citations pc1
            JOIN paper_citations pc2
                ON pc2.source_paper_id = pc1.source_paper_id
                AND pc2.target_paper_id != :cid
            JOIN papers p ON p.canonical_id = pc2.target_paper_id
            WHERE pc1.target_paper_id = :cid
              AND p.canonical_id IS NOT NULL
            GROUP BY p.canonical_id, p.title, p.abstract, p.arxiv_id, p.pmc_id,
                     p.doi, p.tldr, p.token_count, p.year
            ORDER BY co_citation_count DESC
            LIMIT :limit
        """)
        return db.execute(sql, {"cid": str(cid), "limit": limit}).fetchall()

    rows = await asyncio.to_thread(_fetch_related)
    related = [
        RelatedItem(
            paper_id=str(row.canonical_id),
            arxiv_id=row.arxiv_id,
            pmc_id=row.pmc_id,
            title=row.title,
            abstract=row.abstract,
            year=row.year,
            tldr=row.tldr,
            token_count=row.token_count,
            co_citation_count=row.co_citation_count,
        )
        for row in rows
    ]
    response_dict = {
        "paper_id": str(cid),
        "related": [r.model_dump() for r in related],
    }
    await set_cache(redis, cache_key, response_dict, PAPER_TTL)
    return RelatedResponse(paper_id=str(cid), related=related)
