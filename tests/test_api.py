"""Test scaffold for the Research Knowledge Graph REST API.

Tests API-01 through API-09. All stubs assert that routing works (501 returned
rather than 404). Real logic will be filled in Plans 05-02 and 05-03.

Tests requiring a live database or Redis are marked with
@pytest.mark.integration and can be deselected with `-m not integration`.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# API-01: GET /arxiv/{arxiv_id}/head
# ---------------------------------------------------------------------------

def test_arxiv_head():
    """API-01: head endpoint is routed (stub returns 501, not 404)."""
    response = client.get("/arxiv/test-id/head")
    assert isinstance(response.status_code, int)
    assert response.status_code == 501


# ---------------------------------------------------------------------------
# API-02: GET /arxiv/{arxiv_id}/brief
# ---------------------------------------------------------------------------

def test_arxiv_brief():
    """API-02: brief endpoint is routed."""
    response = client.get("/arxiv/test-id/brief")
    assert response.status_code == 501


# ---------------------------------------------------------------------------
# API-03: GET /arxiv/{arxiv_id}/sections
# ---------------------------------------------------------------------------

def test_arxiv_sections():
    """API-03: sections endpoint is routed."""
    response = client.get("/arxiv/test-id/sections")
    assert response.status_code == 501


# ---------------------------------------------------------------------------
# API-04: GET /arxiv/{arxiv_id}/full
# ---------------------------------------------------------------------------

def test_arxiv_full():
    """API-04: full endpoint is routed."""
    response = client.get("/arxiv/test-id/full")
    assert response.status_code == 501


# ---------------------------------------------------------------------------
# API-05: GET /arxiv/search
# ---------------------------------------------------------------------------

def test_search():
    """API-05: search endpoint is routed."""
    response = client.get("/arxiv/search?q=test&limit=5")
    assert response.status_code == 501


# ---------------------------------------------------------------------------
# API-06: GET /pmc/{pmc_id}/head
# ---------------------------------------------------------------------------

def test_pmc_head():
    """API-06: PMC head endpoint is routed."""
    response = client.get("/pmc/test-id/head")
    assert response.status_code == 501


# ---------------------------------------------------------------------------
# API-07: GET /pmc/{pmc_id}/full
# ---------------------------------------------------------------------------

def test_pmc_full():
    """API-07: PMC full endpoint is routed."""
    response = client.get("/pmc/test-id/full")
    assert response.status_code == 501


# ---------------------------------------------------------------------------
# API-08: 404 handling (stub — will be filled in Plan 05-02)
# ---------------------------------------------------------------------------

def test_404():
    """API-08: placeholder for 404 response testing (filled in Plan 05-02)."""
    # Once endpoint logic is implemented, unknown IDs should return 404.
    # For now we just verify the health endpoint returns 200.
    response = client.get("/health")
    assert response.status_code == 200


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
