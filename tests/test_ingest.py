"""Unit tests for ingestion utilities (app.crawler.utils).

Run with:
    pytest tests/test_ingest.py -x -q -k "not integration and not smoke and not 100_paper"
"""

import uuid
import pytest
from sqlalchemy import text

from app.crawler.utils import (
    ARXIV_OAI_BASE,
    ARXIV_SETS,
    CONTENT_TYPE_TO_EXT,
    is_already_ingested,
    normalize_arxiv_id,
)


# ---------------------------------------------------------------------------
# ID normalization tests
# ---------------------------------------------------------------------------


def test_normalize_arxiv_id_new_format():
    """New-format ID with version suffix should be stripped."""
    assert normalize_arxiv_id("2401.00001v2") == "2401.00001"


def test_normalize_arxiv_id_old_format():
    """Old-format (subject/YYMMNNN) with version suffix should be stripped."""
    assert normalize_arxiv_id("hep-th/9901001v1") == "hep-th/9901001"


def test_normalize_arxiv_id_no_version():
    """ID without version suffix should be returned unchanged."""
    assert normalize_arxiv_id("2401.00001") == "2401.00001"


def test_normalize_arxiv_id_strip_prefix():
    """'arXiv:' prefix should be removed before normalizing."""
    assert normalize_arxiv_id("arXiv:2401.00001v3") == "2401.00001"


def test_normalize_arxiv_id_five_digit():
    """Five-digit new format (post-2015) should be handled correctly."""
    assert normalize_arxiv_id("2401.12345v1") == "2401.12345"


# ---------------------------------------------------------------------------
# Content-Type routing test
# ---------------------------------------------------------------------------


def test_content_type_routing():
    """CONTENT_TYPE_TO_EXT maps known MIME types to correct file extensions."""
    assert CONTENT_TYPE_TO_EXT["application/x-eprint-tar"] == ".tar.gz"
    assert CONTENT_TYPE_TO_EXT["application/x-eprint"] == ".tar.gz"
    assert CONTENT_TYPE_TO_EXT["application/pdf"] == ".pdf"
    assert CONTENT_TYPE_TO_EXT["application/postscript"] == ".ps.gz"
    # All four expected keys must be present
    assert len(CONTENT_TYPE_TO_EXT) == 4


# ---------------------------------------------------------------------------
# Dedup check tests
# ---------------------------------------------------------------------------


def test_is_already_ingested_false(mock_db_session):
    """Empty DB returns False for an unknown arXiv ID."""
    assert is_already_ingested(mock_db_session, arxiv_id="9999.99999") is False


def test_is_already_ingested_true(mock_db_session):
    """Paper inserted with a known arxiv_id should be detected as already ingested."""
    # Use raw SQL to avoid JSONB/Vector type incompatibilities with SQLite
    mock_db_session.execute(
        text("INSERT INTO papers (canonical_id, arxiv_id) VALUES (:cid, :aid)"),
        {"cid": str(uuid.uuid4()), "aid": "2401.00001"},
    )
    mock_db_session.commit()

    assert is_already_ingested(mock_db_session, arxiv_id="2401.00001") is True


# ---------------------------------------------------------------------------
# Constants tests
# ---------------------------------------------------------------------------


def test_constants():
    """Verify key constants match the values from RESEARCH.md."""
    assert ARXIV_OAI_BASE == "https://oaipmh.arxiv.org/oai"
    assert len(ARXIV_SETS) == 5
    assert "cs:cs:LG" in ARXIV_SETS
    assert "cs:cs:AI" in ARXIV_SETS
    assert "cs:cs:CV" in ARXIV_SETS
    assert "cs:cs:CL" in ARXIV_SETS
    assert "stat:stat:ML" in ARXIV_SETS
