"""Tests for Phase 3 parser tasks (PARSE-01 through PARSE-05, D-03).

Unit tests import from app.tasks.parse_helpers.
Integration tests are skipped until parser libraries are installed.

Run with:
    pytest tests/test_parse.py -x -q -m "not gpu"
"""

import pytest


# ---------------------------------------------------------------------------
# Unit tests (implement now with real assertions)
# ---------------------------------------------------------------------------


def test_backslash_ratio_check():
    """PARSE-01: >2% backslash tokens -> parse_quality=degraded"""
    from app.tasks.parse_helpers import _backslash_ratio_degraded

    # No backslashes -- clearly not degraded
    assert _backslash_ratio_degraded("hello world no backslash") is False

    # Empty string edge case
    assert _backslash_ratio_degraded("") is False

    # 3 out of 4 tokens start with backslash -- 75% > 2% -> degraded
    assert _backslash_ratio_degraded(r"\cmd1 \cmd2 \cmd3 word") is True

    # 5 backslash tokens + 100 plain words = 5/105 ~= 4.8% > 2% -> degraded
    text = r"\badcmd " * 5 + "word " * 100
    assert _backslash_ratio_degraded(text) is True

    # Exactly 2 backslash tokens + 98 plain words = 2/100 = 2% -- NOT > threshold -> False
    text_borderline = r"\cmd1 \cmd2 " + "word " * 98
    assert _backslash_ratio_degraded(text_borderline) is False


def test_strip_doctype():
    """PARSE-02: DOCTYPE stripped before JATS parsing"""
    from app.tasks.parse_helpers import _strip_jats_doctype

    raw = (
        b'<?xml version="1.0"?>'
        b'<!DOCTYPE article PUBLIC "-//NLM//DTD Journal Archiving and Interchange DTD v2.3 20070202//EN"'
        b' "http://dtd.nlm.nih.gov/archiving/2.3/archivearticle.dtd">'
        b"<article><body/></article>"
    )
    cleaned = _strip_jats_doctype(raw)
    assert b"<!DOCTYPE" not in cleaned
    assert b"<article>" in cleaned

    # Already clean XML -- should pass through unchanged
    clean_xml = b"<?xml version='1.0'?><article><body/></article>"
    assert _strip_jats_doctype(clean_xml) == clean_xml


def test_strip_doctype_with_internal_subset():
    """PARSE-02: DOCTYPE with internal subset [...] stripped (DOTALL regex)"""
    from app.tasks.parse_helpers import _strip_jats_doctype

    raw = b'<?xml version="1.0"?><!DOCTYPE article PUBLIC "-//NLM//DTD" "url" [\n<!ENTITY foo "bar">\n]><article/>'
    cleaned = _strip_jats_doctype(raw)
    assert b"<!DOCTYPE" not in cleaned
    assert b"<article/>" in cleaned


def test_scanned_pdf_detection():
    """PARSE-03: Scanned PDFs detected by text layer check"""
    pytest.importorskip("pymupdf", reason="Requires PyMuPDF installed")
    from app.tasks.parse_helpers import _has_text_layer

    scanned_path = "tests/fixtures/sample_scanned.pdf"
    result = _has_text_layer(scanned_path, threshold=100)
    assert result is False, (
        f"sample_scanned.pdf should have < 100 chars of text (got True), "
        "ensure the fixture is a minimal blank/image-only PDF"
    )


def test_sentence_length_check():
    """PARSE-05: avg sentence length >80 tokens -> degraded"""
    from app.tasks.parse_helpers import _sentence_length_degraded

    # Short sentences -- clearly not degraded
    short_text = "Short sentence. Another one. And more."
    assert _sentence_length_degraded(short_text) is False

    # One sentence with 100 words -- 100 > 80 -> degraded
    long_text = " ".join(["word"] * 100) + "."
    assert _sentence_length_degraded(long_text) is True

    # Two sentences each with 100 words -- avg 100 > 80 -> degraded
    two_long = " ".join(["word"] * 100) + ". " + " ".join(["word"] * 100) + "."
    assert _sentence_length_degraded(two_long) is True

    # Empty string edge case
    assert _sentence_length_degraded("") is False


def test_count_pdf_tables():
    """D-03: _count_pdf_tables counts tables in a PDF via pymupdf heuristic"""
    # Stub -- requires a PDF fixture with known table count
    pytest.skip("Requires PDF fixture with tables -- implement with real fixture")


# ---------------------------------------------------------------------------
# Integration tests (stubs -- depend on parser libraries being installed)
# ---------------------------------------------------------------------------


def test_parse_latex_returns_s2orc():
    """PARSE-01: parse_latex produces S2ORC JSON with title, abstract, body_text"""
    pytest.skip("Integration test -- requires s2orc-doc2json + tralics installed")


def test_parse_jats_returns_s2orc():
    """PARSE-02: parse_jats produces S2ORC JSON from JATS XML"""
    pytest.skip("Integration test -- requires s2orc-doc2json installed")


@pytest.mark.gpu
def test_mineru_pdf():
    """PARSE-03: MinerU parses born-digital PDF"""
    pytest.skip("GPU integration test -- requires magic-pdf[full] + GPU")


def test_grobid_references():
    """PARSE-04: GROBID processReferences returns citation list"""
    pytest.skip("Integration test -- requires GROBID service running")


def test_router_dispatch():
    """PARSE-05: Router dispatches correct parser chain by asset type"""
    pytest.skip("Integration test -- requires all parsers available")
