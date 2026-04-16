"""Stub route handlers for PMC endpoints.

All handlers return HTTP 501 until implemented in Plan 05-02.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.schemas import HeadResponse, FullResponse

router = APIRouter()

_NOT_IMPL = {"error": "not_implemented", "message": "Coming in Plan 05-02"}


@router.get("/pmc/{pmc_id}/head", response_model=HeadResponse)
def pmc_head(pmc_id: str, db: Session = Depends(get_db)):
    return JSONResponse(status_code=501, content=_NOT_IMPL)


@router.get("/pmc/{pmc_id}/full", response_model=FullResponse)
def pmc_full(pmc_id: str, db: Session = Depends(get_db)):
    return JSONResponse(status_code=501, content=_NOT_IMPL)
