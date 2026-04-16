"""Stub route handlers for all arXiv endpoints.

All handlers return HTTP 501 until implemented in Plan 05-02.
Using sync `def` handlers (not async def) so FastAPI runs them in the
threadpool — recommended pattern for sync SQLAlchemy DB calls (Pitfall 5).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.schemas import (
    HeadResponse,
    SectionsResponse,
    FullResponse,
    ReferencesResponse,
    CitedByResponse,
    RelatedResponse,
)

router = APIRouter()

_NOT_IMPL = {"error": "not_implemented", "message": "Coming in Plan 05-02"}


@router.get("/arxiv/{arxiv_id}/head", response_model=HeadResponse)
def arxiv_head(arxiv_id: str, db: Session = Depends(get_db)):
    return JSONResponse(status_code=501, content=_NOT_IMPL)


@router.get("/arxiv/{arxiv_id}/brief", response_model=HeadResponse)
def arxiv_brief(arxiv_id: str, db: Session = Depends(get_db)):
    return JSONResponse(status_code=501, content=_NOT_IMPL)


@router.get("/arxiv/{arxiv_id}/sections", response_model=SectionsResponse)
def arxiv_sections(arxiv_id: str, db: Session = Depends(get_db)):
    return JSONResponse(status_code=501, content=_NOT_IMPL)


@router.get("/arxiv/{arxiv_id}/full", response_model=FullResponse)
def arxiv_full(arxiv_id: str, db: Session = Depends(get_db)):
    return JSONResponse(status_code=501, content=_NOT_IMPL)


@router.get("/arxiv/{arxiv_id}/references", response_model=ReferencesResponse)
def arxiv_references(arxiv_id: str, db: Session = Depends(get_db)):
    return JSONResponse(status_code=501, content=_NOT_IMPL)


@router.get("/arxiv/{arxiv_id}/cited_by", response_model=CitedByResponse)
def arxiv_cited_by(arxiv_id: str, db: Session = Depends(get_db)):
    return JSONResponse(status_code=501, content=_NOT_IMPL)


@router.get("/arxiv/{arxiv_id}/related", response_model=RelatedResponse)
def arxiv_related(arxiv_id: str, db: Session = Depends(get_db)):
    return JSONResponse(status_code=501, content=_NOT_IMPL)
