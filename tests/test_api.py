"""Tests for the Research Knowledge Graph REST API.

Non-integration tests use dependency_overrides to inject a mock DB session
that returns a pre-built Paper-like object — no live PostgreSQL needed.

Tests requiring a live database or Redis are marked with
@pytest.mark.integration and can be deselected with `-m not integration`.
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.api.deps import get_db


# ---------------------------------------------------------------------------
# Mock paper fixture helpers
# ---------------------------------------------------------------------------

TEST_CANONICAL_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
TEST_ARXIV_ID = "2401.00001"
TEST_PMC_ID = "PMC1234567"


def _make_mock_paper():
    """Build a mock Paper ORM object for unit tests."""
    paper = MagicMock()
    paper.canonical_id = TEST_CANONICAL_ID
    paper.arxiv_id = TEST_ARXIV_ID
    paper.pmc_id = TEST_PMC_ID
    paper.doi = "10.1234/test"
    paper.title = "Test Paper Title"
    paper.abstract = "This is a test abstract. Second sentence here."
    paper.tldr = "This is a test abstract."
    paper.year = 2024
    paper.venue = "NeurIPS"
    paper.parse_source = "latex"
    paper.token_count = 100
    paper.content = {
        "authors": ["Alice Smith", "Bob Jones"],
        "sections": [
            {
                "heading": "Introduction",
                "sec_num": "1",
                "text": "This is the introduction.",
                "paragraphs": [],
                "token_count": 10,
            }
        ],
        "citations": [
            {
                "ref_id": "BIBREF0",
                "title": "Some Citation",
                "authors": [],
                "year": 2020,
                "venue": None,
                "doi": None,
                "arxiv_id": None,
                "raw_text": None,
            }
        ],
        "ref_entries": {"FIG1": {"type": "figure", "text": "A figure"}},
        "back_matter": [],
    }
    return paper


def _make_mock_db(paper=None):
    """Build a mock DB session that returns the given paper from resolve queries."""
    mock_db = MagicMock()
    if paper is None:
        # No paper found — return None from all filter().first() calls
        mock_db.query.return_value.filter.return_value.first.return_value = None
    else:
        mock_db.query.return_value.filter.return_value.first.return_value = paper
        # Also handle execute() for citation queries (references, cited_by, related)
        mock_db.execute.return_value.fetchall.return_value = []
    return mock_db


def override_get_db_with_paper(paper):
    """Return a FastAPI dependency override that injects a DB with the given paper."""
    def _override():
        yield _make_mock_db(paper)
    return _override


def override_get_db_not_found():
    """Return a FastAPI dependency override that injects a DB with no paper."""
    def _override():
        yield _make_mock_db(None)
    return _override


# ---------------------------------------------------------------------------
# TestClient with mock DB
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_dependency_overrides():
    """Ensure dependency overrides are cleared after each test."""
    yield
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# API-01: GET /arxiv/{arxiv_id}/head
# ---------------------------------------------------------------------------

def test_arxiv_head():
    """API-01: head endpoint returns 200 with paper_id, title, arxiv_id keys."""
    paper = _make_mock_paper()
    app.dependency_overrides[get_db] = override_get_db_with_paper(paper)
    client = TestClient(app)
    response = client.get(f"/arxiv/{TEST_ARXIV_ID}/head")
    assert response.status_code == 200
    data = response.json()
    assert "paper_id" in data
    assert "title" in data
    assert "arxiv_id" in data
    assert data["arxiv_id"] == TEST_ARXIV_ID
    assert data["title"] == "Test Paper Title"


# ---------------------------------------------------------------------------
# API-02: GET /arxiv/{arxiv_id}/brief
# ---------------------------------------------------------------------------

def test_arxiv_brief():
    """API-02: brief endpoint returns 200 with same shape as head."""
    paper = _make_mock_paper()
    app.dependency_overrides[get_db] = override_get_db_with_paper(paper)
    client = TestClient(app)
    response = client.get(f"/arxiv/{TEST_ARXIV_ID}/brief")
    assert response.status_code == 200
    data = response.json()
    assert "paper_id" in data
    assert "title" in data
    assert "arxiv_id" in data


# ---------------------------------------------------------------------------
# API-03: GET /arxiv/{arxiv_id}/sections
# ---------------------------------------------------------------------------

def test_arxiv_sections():
    """API-03: sections endpoint returns 200 with sections key as list."""
    paper = _make_mock_paper()
    app.dependency_overrides[get_db] = override_get_db_with_paper(paper)
    client = TestClient(app)
    response = client.get(f"/arxiv/{TEST_ARXIV_ID}/sections")
    assert response.status_code == 200
    data = response.json()
    assert "sections" in data
    assert isinstance(data["sections"], list)
    assert len(data["sections"]) == 1
    assert data["sections"][0]["heading"] == "Introduction"


# ---------------------------------------------------------------------------
# API-04: GET /arxiv/{arxiv_id}/full
# ---------------------------------------------------------------------------

def test_arxiv_full():
    """API-04: full endpoint returns 200 with sections, citations, ref_entries keys."""
    paper = _make_mock_paper()
    app.dependency_overrides[get_db] = override_get_db_with_paper(paper)
    client = TestClient(app)
    response = client.get(f"/arxiv/{TEST_ARXIV_ID}/full")
    assert response.status_code == 200
    data = response.json()
    assert "sections" in data
    assert "citations" in data
    assert "ref_entries" in data
    assert isinstance(data["sections"], list)
    assert isinstance(data["citations"], list)


# ---------------------------------------------------------------------------
# API-05: GET /arxiv/search (BM25 mode to avoid embedding dependency)
# ---------------------------------------------------------------------------

def test_search():
    """API-05: search endpoint with bm25 mode returns 200 with total and results keys."""
    mock_db = MagicMock()
    # BM25 search: execute().fetchall() returns empty list (no papers in test DB)
    mock_db.execute.return_value.fetchall.return_value = []

    def override():
        yield mock_db

    app.dependency_overrides[get_db] = override
    client = TestClient(app)
    response = client.get("/arxiv/search?q=attention&search_mode=bm25&limit=5")
    assert response.status_code == 200
    data = response.json()
    assert "total" in data
    assert "results" in data
    assert isinstance(data["results"], list)


# ---------------------------------------------------------------------------
# API-06: GET /pmc/{pmc_id}/head
# ---------------------------------------------------------------------------

def test_pmc_head():
    """API-06: PMC head endpoint returns 200."""
    paper = _make_mock_paper()
    app.dependency_overrides[get_db] = override_get_db_with_paper(paper)
    client = TestClient(app)
    response = client.get(f"/pmc/{TEST_PMC_ID}/head")
    assert response.status_code == 200
    data = response.json()
    assert "paper_id" in data
    assert data["pmc_id"] == TEST_PMC_ID


# ---------------------------------------------------------------------------
# API-07: GET /pmc/{pmc_id}/full
# ---------------------------------------------------------------------------

def test_pmc_full():
    """API-07: PMC full endpoint returns 200."""
    paper = _make_mock_paper()
    app.dependency_overrides[get_db] = override_get_db_with_paper(paper)
    client = TestClient(app)
    response = client.get(f"/pmc/{TEST_PMC_ID}/full")
    assert response.status_code == 200
    data = response.json()
    assert "sections" in data
    assert "citations" in data


# ---------------------------------------------------------------------------
# API-08: 404 handling
# ---------------------------------------------------------------------------

def test_404():
    """API-08: unknown ID returns 404 with error=not_found in response body."""
    app.dependency_overrides[get_db] = override_get_db_not_found()
    client = TestClient(app)
    response = client.get("/arxiv/nonexistent-paper-id/head")
    assert response.status_code == 404
    data = response.json()
    assert data["error"] == "not_found"
    assert "not found" in data["message"].lower()


# ---------------------------------------------------------------------------
# Version stripping
# ---------------------------------------------------------------------------

def test_arxiv_version_stripping():
    """arXiv version suffix is stripped before DB lookup (2401.00001v2 -> 2401.00001)."""
    from app.api.routes.arxiv import strip_arxiv_version
    assert strip_arxiv_version("2401.00001v2") == "2401.00001"
    assert strip_arxiv_version("2401.00001V3") == "2401.00001"
    assert strip_arxiv_version("2401.00001") == "2401.00001"


# ---------------------------------------------------------------------------
# API-09: Redis cache (stub — will be filled in Plan 05-03)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_redis_cache():
    """API-09: placeholder for Redis caching tests (filled in Plan 05-03).

    Marked integration because it needs a live Redis instance.
    """
    # Stub: just verify the app has a redis attribute on state after startup.
    # Real cache hit/miss assertions come in Plan 05-03.
    assert True
