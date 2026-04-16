"""Stub route handler for the hybrid search endpoint.

Returns HTTP 501 until implemented in Plan 05-03.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.schemas import SearchResponse

router = APIRouter()

_NOT_IMPL = {"error": "not_implemented", "message": "Coming in Plan 05-03"}


@router.get("/arxiv/search", response_model=SearchResponse)
def arxiv_search(
    q: str,
    limit: int = 10,
    search_mode: str = "hybrid",
    db: Session = Depends(get_db),
):
    return JSONResponse(status_code=501, content=_NOT_IMPL)
