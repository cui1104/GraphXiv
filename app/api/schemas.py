"""Pydantic v2 response models for the Research Knowledge Graph API.

Field names match FEATURES.md unified JSON schema exactly so deepxiv_sdk
Reader compatibility is preserved.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Sub-objects
# ---------------------------------------------------------------------------

class SectionObject(BaseModel):
    heading: str
    sec_num: str | None = None
    text: str
    paragraphs: list[dict] = []
    token_count: int = 0


class CitationObject(BaseModel):
    ref_id: str | None = None
    title: str | None = None
    authors: list[str] = []
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    raw_text: str | None = None


# ---------------------------------------------------------------------------
# Paper response models
# ---------------------------------------------------------------------------

class HeadResponse(BaseModel):
    paper_id: str
    arxiv_id: str | None = None
    pmc_id: str | None = None
    doi: str | None = None
    title: str | None = None
    abstract: str | None = None
    tldr: str | None = None
    authors: list[str] = []
    year: int | None = None
    venue: str | None = None
    src_url: str = ""
    token_count: int = 0
    parse_source: str | None = None


# BriefResponse is an alias for HeadResponse (same schema, per API-02)
BriefResponse = HeadResponse


class SectionsResponse(BaseModel):
    paper_id: str
    title: str | None = None
    sections: list[SectionObject] = []
    token_count: int = 0


class FullResponse(BaseModel):
    # All HeadResponse fields
    paper_id: str
    arxiv_id: str | None = None
    pmc_id: str | None = None
    doi: str | None = None
    title: str | None = None
    abstract: str | None = None
    tldr: str | None = None
    authors: list[str] = []
    year: int | None = None
    venue: str | None = None
    src_url: str = ""
    token_count: int = 0
    parse_source: str | None = None
    # Full-paper extras
    sections: list[SectionObject] = []
    citations: list[CitationObject] = []
    ref_entries: dict[str, Any] = {}
    back_matter: list[dict] = []


# ---------------------------------------------------------------------------
# Search response models
# ---------------------------------------------------------------------------

class SearchResultItem(BaseModel):
    paper_id: str
    arxiv_id: str | None = None
    pmc_id: str | None = None
    title: str | None = None
    abstract: str | None = None
    tldr: str | None = None
    authors: list[str] = []
    year: int | None = None
    src_url: str = ""
    token_count: int = 0


class SearchResponse(BaseModel):
    total: int
    results: list[SearchResultItem]


# ---------------------------------------------------------------------------
# References / citations response models
# ---------------------------------------------------------------------------

class ReferenceItem(BaseModel):
    target_arxiv_id: str | None = None
    target_doi: str | None = None
    context_text: str | None = None
    in_corpus: bool = False
    paper_id: str | None = None
    title: str | None = None
    abstract: str | None = None
    authors: list[str] = []
    year: int | None = None
    arxiv_id: str | None = None
    pmc_id: str | None = None
    doi: str | None = None
    tldr: str | None = None
    token_count: int | None = None


class ReferencesResponse(BaseModel):
    paper_id: str
    references: list[ReferenceItem]


class CitedByItem(BaseModel):
    paper_id: str
    arxiv_id: str | None = None
    pmc_id: str | None = None
    title: str | None = None
    abstract: str | None = None
    authors: list[str] = []
    year: int | None = None
    tldr: str | None = None
    token_count: int | None = None
    context_text: str | None = None


class CitedByResponse(BaseModel):
    paper_id: str
    cited_by: list[CitedByItem]


class RelatedItem(BaseModel):
    paper_id: str
    arxiv_id: str | None = None
    pmc_id: str | None = None
    title: str | None = None
    abstract: str | None = None
    authors: list[str] = []
    year: int | None = None
    tldr: str | None = None
    token_count: int | None = None
    co_citation_count: int


class RelatedResponse(BaseModel):
    paper_id: str
    related: list[RelatedItem]


# ---------------------------------------------------------------------------
# Error response
# ---------------------------------------------------------------------------

class ErrorResponse(BaseModel):
    error: str
    message: str
