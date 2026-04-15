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


# ---------------------------------------------------------------------------
# PMC crawler tests
# ---------------------------------------------------------------------------


def test_extract_pmc_id():
    """PMC ID is correctly extracted from the OAI identifier string."""
    from app.crawler.pmc_oai import _extract_pmc_id

    assert _extract_pmc_id("oai:pubmedcentral.nih.gov:PMC1234567") == "PMC1234567"
    assert _extract_pmc_id("oai:pubmedcentral.nih.gov:PMC99") == "PMC99"


def test_is_dl_paper_positive():
    """DL keyword filter matches deep learning / neural network titles and abstracts."""
    from app.crawler.pmc_oai import _is_dl_paper

    assert _is_dl_paper("Deep Learning for Medical Imaging", None) is True
    assert _is_dl_paper(None, "We use a transformer model to...") is True
    assert _is_dl_paper("A neural network approach", "Some abstract") is True


def test_is_dl_paper_negative():
    """DL keyword filter correctly rejects non-DL papers and None/None inputs."""
    from app.crawler.pmc_oai import _is_dl_paper

    assert _is_dl_paper("Clinical trial of aspirin", "Randomized controlled trial") is False
    assert _is_dl_paper(None, None) is False


def test_process_pmc_record_inserts():
    """process_pmc_record inserts a Paper + PaperSource row for a new DL paper."""
    from unittest.mock import MagicMock, patch
    from app.crawler.pmc_oai import process_pmc_record
    from app.models import Paper, PaperSource

    mock_session = MagicMock()

    # Mock pg_insert and is_already_ingested
    with (
        patch("app.crawler.pmc_oai.pg_insert") as mock_pg_insert,
        patch("app.crawler.pmc_oai.is_already_ingested", return_value=False),
    ):
        # Simulate the Paper row being returned after insert
        import uuid
        fake_uuid = uuid.uuid4()
        mock_session.execute.return_value.first.return_value = (fake_uuid,)

        # Set up mock_pg_insert chain: pg_insert(Paper).values(...).on_conflict_do_nothing(...)
        mock_stmt = MagicMock()
        mock_pg_insert.return_value.values.return_value.on_conflict_do_nothing.return_value = mock_stmt

        result = process_pmc_record(
            mock_session,
            "PMC1234567",
            "Deep Learning Paper",
            "Uses neural networks",
        )

        # pg_insert was called with Paper model
        mock_pg_insert.assert_called_with(Paper)
        # session.execute was called (i.e., the insert was attempted)
        assert mock_session.execute.called
        # Result is True (paper was inserted)
        assert result is True
        # PaperSource was added to session with source_type="pmc"
        add_calls = mock_session.add.call_args_list
        assert len(add_calls) == 1
        paper_source = add_calls[0].args[0]
        assert isinstance(paper_source, PaperSource)
        assert paper_source.source_type == "pmc"
        assert paper_source.canonical_id == fake_uuid


def test_process_pmc_record_skips_non_dl():
    """process_pmc_record returns False for papers that don't match DL keywords."""
    from unittest.mock import MagicMock, patch
    from app.crawler.pmc_oai import process_pmc_record

    mock_session = MagicMock()

    with patch("app.crawler.pmc_oai.is_already_ingested", return_value=False):
        result = process_pmc_record(
            mock_session,
            "PMC999",
            "Clinical trial results",
            "Aspirin study",
        )

    assert result is False


def test_pmc_constants():
    """PMC_OAI_BASE points at the new PMC OAI endpoint (not the old NLM URL)."""
    from app.crawler.utils import PMC_OAI_BASE

    assert PMC_OAI_BASE == "https://pmc.ncbi.nlm.nih.gov/api/oai/v1/mh/"
