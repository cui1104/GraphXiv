"""Tests for Phase 4 normalizer (NORM-01 through NORM-06).

Unit tests for pure normalization functions.
Integration tests are stubs requiring DB.

Run with:
    pytest tests/test_normalize.py -x -q -m "not integration"
"""

import pytest


# ---------------------------------------------------------------------------
# Shared fixture data (inline, no external files)
# ---------------------------------------------------------------------------

MINIMAL_S2ORC = {
    "title": "Test Paper",
    "abstract": "We study attention mechanisms. They improve transformers. Results are significant.",
    "authors": [{"first": "John", "middle": [], "last": "Doe", "suffix": ""}],
    "body_text": [
        {
            "section": "Introduction",
            "sec_num": "1",
            "text": "This paper introduces...",
            "cite_spans": [],
            "ref_spans": [],
        },
        {
            "section": "Introduction",
            "sec_num": "1",
            "text": "We build on prior work...",
            "cite_spans": [],
            "ref_spans": [],
        },
        {
            "section": "Methods",
            "sec_num": "2",
            "text": "Our approach uses transformers...",
            "cite_spans": [],
            "ref_spans": [],
        },
    ],
    "bib_entries": {
        "BIBREF0": {
            "title": "Attention Is All You Need",
            "authors": [{"first": "Ashish", "last": "Vaswani"}],
            "year": 2017,
            "venue": "NeurIPS",
            "doi": "10.5555/3295222.3295349",
            "arxiv_id": "1706.03762",
            "raw_text": "Vaswani et al. 2017",
        }
    },
}

MINIMAL_MINERU = {
    "content_list": [
        {"type": "title", "text": "Introduction", "sec_num": "1"},
        {"type": "text", "text": "This paper introduces attention."},
        {"type": "title", "text": "Methods", "sec_num": "2"},
        {"type": "text", "text": "We use transformers."},
    ],
    "parser": "mineru",
    "text_level_broken": True,
}

MINIMAL_TEI_XML = (
    b'<TEI xmlns="http://www.tei-c.org/ns/1.0">'
    b"<teiHeader/>"
    b"<text><body>"
    b'<div n="1"><head>Introduction</head>'
    b"<p>This paper introduces attention.</p></div>"
    b'<div n="2"><head>Methods</head>'
    b"<p>We use transformers.</p></div>"
    b"</body></text></TEI>"
)


# ---------------------------------------------------------------------------
# NORM-01: Parser output → unified sections
# ---------------------------------------------------------------------------


def test_normalize_s2orc():
    """NORM-01: S2ORC body_text grouped into sections with heading/sec_num/text/paragraphs/token_count"""
    from app.tasks.normalize import _normalize_s2orc

    result = _normalize_s2orc(MINIMAL_S2ORC)
    sections = result.get("sections", [])
    assert len(sections) >= 1, f"expected at least 1 section, got {len(sections)}"
    intro = next((s for s in sections if s.get("sec_num") == "1"), None)
    assert intro is not None, "expected section with sec_num='1'"
    assert intro.get("heading") == "Introduction"
    assert isinstance(intro.get("paragraphs"), list)
    assert len(intro["paragraphs"]) == 2, "Introduction has 2 body_text blocks"
    assert "token_count" in intro


def test_normalize_mineru():
    """NORM-01: MinerU content_list → sections via dot-count hierarchy"""
    from app.tasks.normalize import _normalize_mineru

    result = _normalize_mineru(MINIMAL_MINERU)
    sections = result.get("sections", [])
    assert len(sections) >= 1, f"expected at least 1 section, got {len(sections)}"
    headings = [s.get("heading") for s in sections]
    assert "Introduction" in headings
    assert "Methods" in headings


def test_parse_tei_sections():
    """NORM-01: GROBID TEI XML → sections with heading/sec_num/text"""
    from app.parsers.grobid import _parse_tei_fulltext_sections

    sections = _parse_tei_fulltext_sections(MINIMAL_TEI_XML)
    assert len(sections) == 2, f"expected 2 sections, got {len(sections)}"
    assert sections[0]["heading"] == "Introduction"
    assert sections[0]["sec_num"] == "1"
    assert "attention" in sections[0]["text"].lower()
    assert sections[1]["heading"] == "Methods"
    assert sections[1]["sec_num"] == "2"


# ---------------------------------------------------------------------------
# NORM-05: Section and citation shapes
# ---------------------------------------------------------------------------


def test_section_shape():
    """NORM-05: section dict has keys {heading, sec_num, text, paragraphs, token_count}"""
    from app.parsers.grobid import _parse_tei_fulltext_sections

    sections = _parse_tei_fulltext_sections(MINIMAL_TEI_XML)
    assert len(sections) >= 1
    sec = sections[0]
    required_keys = {"heading", "sec_num", "text", "paragraphs", "token_count"}
    assert required_keys.issubset(sec.keys()), (
        f"section missing keys: {required_keys - sec.keys()}"
    )
    assert isinstance(sec["paragraphs"], list)
    assert isinstance(sec["token_count"], int)


def test_citation_shape():
    """NORM-05: citation dict has keys {ref_id, title, authors, year, venue, doi, arxiv_id, raw_text}"""
    from app.tasks.normalize import _normalize_s2orc

    result = _normalize_s2orc(MINIMAL_S2ORC)
    citations = result.get("citations", [])
    assert len(citations) >= 1, "expected at least 1 citation from bib_entries"
    cit = citations[0]
    required_keys = {"ref_id", "title", "authors", "year", "venue", "doi", "arxiv_id", "raw_text"}
    assert required_keys.issubset(cit.keys()), (
        f"citation missing keys: {required_keys - cit.keys()}"
    )


# ---------------------------------------------------------------------------
# NORM-02: Token counting
# ---------------------------------------------------------------------------


def test_token_count():
    """NORM-02: token_count > 0 for paper with section text"""
    from app.tasks.normalize import _compute_token_count

    text = "This paper introduces attention mechanisms for transformers."
    count = _compute_token_count(text)
    assert isinstance(count, int)
    assert count > 0, f"expected token_count > 0, got {count}"


@pytest.mark.integration
def test_token_count_in_db():
    """NORM-02 (integration): token_count column populated in DB after normalize"""
    pytest.skip("integration test - requires DB")


# ---------------------------------------------------------------------------
# NORM-03: tldr always present
# ---------------------------------------------------------------------------


def test_tldr_always_present():
    """NORM-03: tldr key present (string or None, never missing)"""
    from app.tasks.normalize import _compute_tldr

    # With abstract
    result_with = _compute_tldr("We study attention. It works well. Results are good.")
    assert "tldr" in result_with, "tldr key must always be present"

    # With None abstract
    result_none = _compute_tldr(None)
    assert "tldr" in result_none, "tldr key must be present even when abstract is None"


def test_tldr_content():
    """NORM-03: tldr equals first 2-3 sentences of abstract"""
    from app.tasks.normalize import _compute_tldr

    abstract = "We study attention mechanisms. They improve transformers. Results are significant. More text here."
    result = _compute_tldr(abstract)
    tldr = result["tldr"]
    assert tldr is not None
    # tldr should contain first sentence
    assert "attention mechanisms" in tldr
    # tldr should NOT contain the 4th sentence
    assert "More text here" not in tldr


# ---------------------------------------------------------------------------
# NORM-06: parse_quality propagation
# ---------------------------------------------------------------------------


def test_parse_quality():
    """NORM-06: parse_quality propagated from parser to normalized content"""
    from app.tasks.normalize import _normalize_s2orc

    result = _normalize_s2orc(MINIMAL_S2ORC, parse_quality="degraded")
    assert result.get("parse_quality") == "degraded", (
        f"expected parse_quality='degraded', got {result.get('parse_quality')}"
    )


# ---------------------------------------------------------------------------
# NORM-04: Dedup fingerprint
# ---------------------------------------------------------------------------


def test_dedup_fingerprint():
    """NORM-04: SHA-256 of normalized title + first author last name + year"""
    from app.tasks.normalize import _compute_dedup_fingerprint

    fingerprint = _compute_dedup_fingerprint(
        title="Attention Is All You Need",
        first_author_last="Vaswani",
        year=2017,
    )
    assert fingerprint is not None
    assert len(fingerprint) == 64, f"SHA-256 hex digest should be 64 chars, got {len(fingerprint)}"
    # Deterministic
    fingerprint2 = _compute_dedup_fingerprint(
        title="Attention Is All You Need",
        first_author_last="Vaswani",
        year=2017,
    )
    assert fingerprint == fingerprint2, "fingerprint must be deterministic"

    # Different paper -> different fingerprint
    fp_other = _compute_dedup_fingerprint(
        title="BERT: Pre-training of Deep Bidirectional Transformers",
        first_author_last="Devlin",
        year=2018,
    )
    assert fp_other != fingerprint


@pytest.mark.integration
def test_cross_source_dedup():
    """NORM-04 (integration): cross-source dedup links papers via id_map in DB"""
    pytest.skip("integration test - requires DB")
