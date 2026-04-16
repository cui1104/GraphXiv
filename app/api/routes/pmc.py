"""Route handlers for PMC endpoints.

Uses sync `def` handlers (not async def) so FastAPI runs them in the
threadpool — recommended pattern for sync SQLAlchemy DB calls.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.schemas import HeadResponse, FullResponse
from app.api.routes.arxiv import _paper_to_head
from app.models import Paper, IdMap

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
def pmc_head(pmc_id: str, db: Session = Depends(get_db)):
    """API-06: Return metadata (head) for a PMC paper."""
    paper = resolve_pmc_id(db, pmc_id)
    if paper is None:
        return JSONResponse(
            status_code=404,
            content={"error": "not_found", "message": f"Paper {pmc_id} not found"},
        )
    return HeadResponse(**_paper_to_head(paper))


@router.get("/pmc/{pmc_id}/full", response_model=FullResponse)
def pmc_full(pmc_id: str, db: Session = Depends(get_db)):
    """API-07: Return full paper data for a PMC paper."""
    paper = resolve_pmc_id(db, pmc_id)
    if paper is None:
        return JSONResponse(
            status_code=404,
            content={"error": "not_found", "message": f"Paper {pmc_id} not found"},
        )
    content = paper.content or {}
    head = _paper_to_head(paper)
    return FullResponse(
        **head,
        sections=content.get("sections", []),
        citations=content.get("citations", []),
        ref_entries=content.get("ref_entries", {}),
        back_matter=content.get("back_matter", []),
    )
