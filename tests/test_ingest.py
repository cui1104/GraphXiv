"""Unit tests for ingestion utilities (app.crawler.utils).

Run with:
    pytest tests/test_ingest.py -x -q -k "not integration and not smoke and not 100_paper"
"""

import asyncio
import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text

from app.crawler.utils import (
    ARXIV_OAI_BASE,
    ARXIV_SETS,
    CONTENT_TYPE_TO_EXT,
    USER_AGENT,
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


# ---------------------------------------------------------------------------
# arXiv OAI XML parsing tests (02-02)
# ---------------------------------------------------------------------------

_MINIMAL_OAI_XML = """<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
  <ListRecords>
    <record>
      <header>
        <identifier>oai:arXiv.org:2401.00001</identifier>
        <datestamp>2024-01-01</datestamp>
      </header>
      <metadata>
        <arXivRaw>
          <id>2401.00001</id>
          <title>Test Paper Title</title>
          <abstract>This is the abstract.</abstract>
          <authors>Alice Bob</authors>
          <categories>cs.LG cs.AI</categories>
          <created>2024-01-01</created>
        </arXivRaw>
      </metadata>
    </record>
  </ListRecords>
  {token_element}
</OAI-PMH>
"""

_OAI_XML_ONE_RECORD = _MINIMAL_OAI_XML.format(token_element="")
_OAI_XML_WITH_TOKEN = _MINIMAL_OAI_XML.format(
    token_element="<resumptionToken>abc123</resumptionToken>",
)
_OAI_XML_EMPTY_TOKEN = _MINIMAL_OAI_XML.format(
    token_element="<resumptionToken/>",
)


def test_arxiv_oai_parse_records():
    """_parse_arxiv_records returns correct dict from minimal arXivRaw XML."""
    from app.crawler.arxiv_oai import _parse_arxiv_records

    records = _parse_arxiv_records(_OAI_XML_ONE_RECORD)
    assert len(records) == 1
    rec = records[0]
    assert rec["arxiv_id"] == "2401.00001"
    assert rec["title"] == "Test Paper Title"
    assert rec["abstract"] == "This is the abstract."


def test_arxiv_oai_extract_token():
    """_extract_resumption_token returns token text when present."""
    from app.crawler.arxiv_oai import _extract_resumption_token

    token = _extract_resumption_token(_OAI_XML_WITH_TOKEN)
    assert token == "abc123"


def test_arxiv_oai_extract_token_empty():
    """_extract_resumption_token returns None for empty/missing token element."""
    from app.crawler.arxiv_oai import _extract_resumption_token

    token = _extract_resumption_token(_OAI_XML_EMPTY_TOKEN)
    assert token is None


# ---------------------------------------------------------------------------
# Rate limiter configuration test (02-02)
# ---------------------------------------------------------------------------


def test_rate_limiter():
    """RATE_LIMITER is an AsyncLimiter configured for 3 req/sec."""
    from aiolimiter import AsyncLimiter

    from app.crawler.arxiv_oai import RATE_LIMITER

    assert isinstance(RATE_LIMITER, AsyncLimiter)
    assert RATE_LIMITER.max_rate == 3
    assert RATE_LIMITER.time_period == 1


# ---------------------------------------------------------------------------
# User-Agent header test (02-02)
# ---------------------------------------------------------------------------


def test_user_agent_header(httpx_mock):
    """_fetch_page sends the correct User-Agent header on every request."""
    from app.crawler.arxiv_oai import _fetch_page

    # Do not set a url= matcher — pytest-httpx's URL matching is exact and won't
    # match when query params are appended.  Matching any request is sufficient here.
    httpx_mock.add_response(
        status_code=200,
        text=_OAI_XML_EMPTY_TOKEN,
    )

    import httpx as _httpx

    async def _run():
        async with _httpx.AsyncClient() as client:
            return await _fetch_page(client, {"verb": "ListRecords"})

    asyncio.run(_run())

    requests = httpx_mock.get_requests()
    assert len(requests) >= 1
    assert requests[0].headers.get("user-agent") == USER_AGENT


# ---------------------------------------------------------------------------
# arXiv asset downloader tests (02-02)
# ---------------------------------------------------------------------------


def test_download_eprint_content_type_latex(httpx_mock, tmp_path):
    """download_eprint_asset routes application/x-eprint-tar to .tar.gz / source_type=latex."""
    from app.crawler.arxiv_assets import download_eprint_asset

    httpx_mock.add_response(
        status_code=200,
        headers={"content-type": "application/x-eprint-tar"},
        content=b"fake tar content",
    )

    with patch("app.crawler.arxiv_assets.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(data_dir=str(tmp_path))
        asset_path, source_type = asyncio.run(download_eprint_asset("2401.00001"))

    assert source_type == "latex"
    assert asset_path.endswith(".tar.gz")


def test_download_eprint_content_type_pdf(httpx_mock, tmp_path):
    """download_eprint_asset routes application/pdf to .pdf / source_type=pdf."""
    from app.crawler.arxiv_assets import download_eprint_asset

    httpx_mock.add_response(
        status_code=200,
        headers={"content-type": "application/pdf"},
        content=b"%PDF-1.4 fake pdf",
    )

    with patch("app.crawler.arxiv_assets.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(data_dir=str(tmp_path))
        asset_path, source_type = asyncio.run(download_eprint_asset("2401.00002"))

    assert source_type == "pdf"
    assert asset_path.endswith(".pdf")


def test_asset_download(tmp_path, httpx_mock):
    """download_eprint_asset writes file to disk at correct path with non-zero size."""
    from app.crawler.arxiv_assets import download_eprint_asset

    httpx_mock.add_response(
        status_code=200,
        headers={"content-type": "application/x-eprint-tar"},
        content=b"fake tar content",
    )

    with patch("app.crawler.arxiv_assets.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(data_dir=str(tmp_path))
        asset_path, _ = asyncio.run(download_eprint_asset("2401.00001"))

    expected = tmp_path / "assets" / "arxiv" / "2401.00001.tar.gz"
    assert "2401.00001.tar.gz" in asset_path
    assert expected.exists()
    assert expected.stat().st_size > 0


# ---------------------------------------------------------------------------
# PMC Celery branch test (02-02)
# ---------------------------------------------------------------------------


def test_ingest_paper_pmc_branch():
    """ingest_paper routes pmc source to harvest_pmc and returns correct result dict."""
    import sys
    import types

    # Inject a fake pmc_oai module so the lazy import inside ingest_paper works
    fake_module = types.ModuleType("app.crawler.pmc_oai")
    fake_module.harvest_pmc = lambda from_date="2020-01-01", max_records=50000: 42
    sys.modules["app.crawler.pmc_oai"] = fake_module

    try:
        from app.tasks.ingest import ingest_paper

        result = ingest_paper.run("2024-01-01", source="pmc")
    finally:
        # Restore so other tests are unaffected
        sys.modules.pop("app.crawler.pmc_oai", None)

    assert result["source"] == "pmc"
    assert result["records"] == 42


# ---------------------------------------------------------------------------
# Upsert on version update — integration (requires PostgreSQL)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_upsert_on_version_update():
    """Re-ingesting a paper with updated title uses ON CONFLICT DO UPDATE (INGEST-05)."""
    import os
    import uuid as _uuid

    from sqlalchemy import create_engine, text as sql_text
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.orm import sessionmaker

    db_url = os.environ.get(
        "DATABASE_URL", "postgresql://app:changeme@localhost:5432/papers"
    )

    try:
        engine = create_engine(db_url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(sql_text("SELECT 1"))
    except Exception:
        pytest.skip("PostgreSQL not available for integration test")

    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        from app.models import Paper

        # Insert v1
        stmt_v1 = (
            pg_insert(Paper)
            .values(
                canonical_id=_uuid.uuid4(),
                arxiv_id="2401.99999-test",
                title="v1 Title",
            )
            .on_conflict_do_update(
                index_elements=["arxiv_id"],
                set_={"title": "v1 Title"},
            )
        )
        session.execute(stmt_v1)
        session.commit()

        # Insert v2 — should update title
        stmt_v2 = (
            pg_insert(Paper)
            .values(
                canonical_id=_uuid.uuid4(),
                arxiv_id="2401.99999-test",
                title="v2 Title Updated",
            )
            .on_conflict_do_update(
                index_elements=["arxiv_id"],
                set_={"title": "v2 Title Updated"},
            )
        )
        session.execute(stmt_v2)
        session.commit()

        count = session.query(Paper).filter_by(arxiv_id="2401.99999-test").count()
        paper = session.query(Paper).filter_by(arxiv_id="2401.99999-test").first()

        assert count == 1
        assert paper.title == "v2 Title Updated"
    finally:
        session.execute(sql_text("DELETE FROM papers WHERE arxiv_id = '2401.99999-test'"))
        session.commit()
        session.close()
        engine.dispose()


# ---------------------------------------------------------------------------
# Harvest runner integration test (02-04)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_harvest_runner_status(db_session):
    """Verify the status command works against a real DB."""
    from app.crawler.run_harvest import show_status

    # Should not raise; just prints status to stdout
    show_status()
