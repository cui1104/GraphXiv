"""
Unit tests for the Reader class (local backend fork).

All tests mock HTTP via unittest.mock.patch on Reader._make_request.
No live backend required. No imports from app.*.
"""
import pytest
from unittest.mock import patch, MagicMock
from deepxiv_sdk import Reader


# ---------------------------------------------------------------------------
# Initialization tests
# ---------------------------------------------------------------------------

def test_default_base_url():
    """Reader() default base_url is http://localhost:8000."""
    r = Reader()
    assert r.base_url == "http://localhost:8000"


def test_custom_base_url():
    """Reader(base_url=...) sets base_url correctly."""
    r = Reader(base_url="http://example.com")
    assert r.base_url == "http://example.com"


def test_custom_base_url_trailing_slash_stripped():
    """Trailing slash is stripped from base_url."""
    r = Reader(base_url="http://example.com/")
    assert r.base_url == "http://example.com"


# ---------------------------------------------------------------------------
# arXiv path-param URL construction tests
# ---------------------------------------------------------------------------

def test_head_uses_path_param(base_url, sample_paper_head):
    """reader.head('2401.00001') calls URL /arxiv/2401.00001/head."""
    r = Reader(base_url=base_url)
    with patch.object(r, "_make_request", return_value=sample_paper_head) as mock_req:
        result = r.head("2401.00001")
    mock_req.assert_called_once()
    called_url = mock_req.call_args[0][0]
    assert "/arxiv/2401.00001/head" in called_url
    assert result == sample_paper_head


def test_brief_uses_path_param(base_url, sample_paper_head):
    """reader.brief('2401.00001') calls URL /arxiv/2401.00001/brief."""
    r = Reader(base_url=base_url)
    with patch.object(r, "_make_request", return_value=sample_paper_head) as mock_req:
        result = r.brief("2401.00001")
    mock_req.assert_called_once()
    called_url = mock_req.call_args[0][0]
    assert "/arxiv/2401.00001/brief" in called_url


def test_sections_uses_path_param(base_url, sample_sections_response):
    """reader.sections('2401.00001') calls URL /arxiv/2401.00001/sections."""
    r = Reader(base_url=base_url)
    with patch.object(r, "_make_request", return_value=sample_sections_response) as mock_req:
        result = r.sections("2401.00001")
    mock_req.assert_called_once()
    called_url = mock_req.call_args[0][0]
    assert "/arxiv/2401.00001/sections" in called_url
    assert result == sample_sections_response


def test_section_single_filters_client_side(base_url, sample_sections_response):
    """reader.section('2401.00001', 'Introduction') returns text from Introduction section."""
    r = Reader(base_url=base_url)
    with patch.object(r, "_make_request", return_value=sample_sections_response):
        result = r.section("2401.00001", "Introduction")
    assert result == "We study attention."


def test_section_case_insensitive(base_url, sample_sections_response):
    """section() matching is case-insensitive."""
    r = Reader(base_url=base_url)
    with patch.object(r, "_make_request", return_value=sample_sections_response):
        result = r.section("2401.00001", "introduction")
    assert result == "We study attention."


def test_section_not_found_raises_value_error(base_url, sample_sections_response):
    """section() raises ValueError when section name is not found."""
    r = Reader(base_url=base_url)
    with patch.object(r, "_make_request", return_value=sample_sections_response):
        with pytest.raises(ValueError, match="not found"):
            r.section("2401.00001", "Conclusion")


def test_full_uses_path_param(base_url, sample_full_response):
    """reader.full('2401.00001') calls URL /arxiv/2401.00001/full."""
    r = Reader(base_url=base_url)
    with patch.object(r, "_make_request", return_value=sample_full_response) as mock_req:
        result = r.full("2401.00001")
    mock_req.assert_called_once()
    called_url = mock_req.call_args[0][0]
    assert "/arxiv/2401.00001/full" in called_url


def test_raw_delegates_to_full(base_url, sample_full_response):
    """reader.raw() is an alias for full()."""
    r = Reader(base_url=base_url)
    with patch.object(r, "_make_request", return_value=sample_full_response) as mock_req:
        result = r.raw("2401.00001")
    called_url = mock_req.call_args[0][0]
    assert "/arxiv/2401.00001/full" in called_url


def test_json_delegates_to_full(base_url, sample_full_response):
    """reader.json() is an alias for full()."""
    r = Reader(base_url=base_url)
    with patch.object(r, "_make_request", return_value=sample_full_response) as mock_req:
        result = r.json("2401.00001")
    called_url = mock_req.call_args[0][0]
    assert "/arxiv/2401.00001/full" in called_url


def test_search_uses_correct_url(base_url, sample_search_response):
    """reader.search() calls /arxiv/search with q, limit, search_mode params."""
    r = Reader(base_url=base_url)
    with patch.object(r, "_make_request", return_value=sample_search_response) as mock_req:
        result = r.search("attention mechanisms")
    mock_req.assert_called_once()
    called_url = mock_req.call_args[0][0]
    called_params = mock_req.call_args[1].get("params") or mock_req.call_args[0][1] if len(mock_req.call_args[0]) > 1 else mock_req.call_args[1].get("params", {})
    assert "/arxiv/search" in called_url
    assert result == sample_search_response


def test_search_params_correct(base_url, sample_search_response):
    """search() passes q=, limit=, search_mode= as query params."""
    r = Reader(base_url=base_url)
    with patch.object(r, "_make_request", return_value=sample_search_response) as mock_req:
        r.search("attention", size=5, search_mode="bm25")
    # Extract params argument
    call_args = mock_req.call_args
    # _make_request(url, params=...) - params is keyword arg
    params = call_args[1].get("params") if call_args[1] else None
    if params is None and len(call_args[0]) > 1:
        params = call_args[0][1]
    assert params is not None
    assert params["q"] == "attention"
    assert params["limit"] == 5
    assert params["search_mode"] == "bm25"


def test_references_method(base_url, sample_references_response):
    """reader.references('2401.00001') calls URL /arxiv/2401.00001/references."""
    r = Reader(base_url=base_url)
    with patch.object(r, "_make_request", return_value=sample_references_response) as mock_req:
        result = r.references("2401.00001")
    mock_req.assert_called_once()
    called_url = mock_req.call_args[0][0]
    assert "/arxiv/2401.00001/references" in called_url
    assert result == sample_references_response


def test_cited_by_method(base_url, sample_cited_by_response):
    """reader.cited_by('2401.00001') calls URL /arxiv/2401.00001/cited_by."""
    r = Reader(base_url=base_url)
    with patch.object(r, "_make_request", return_value=sample_cited_by_response) as mock_req:
        result = r.cited_by("2401.00001")
    mock_req.assert_called_once()
    called_url = mock_req.call_args[0][0]
    assert "/arxiv/2401.00001/cited_by" in called_url
    assert result == sample_cited_by_response


# ---------------------------------------------------------------------------
# PMC path-param URL construction tests
# ---------------------------------------------------------------------------

def test_pmc_head_uses_path_param(base_url, sample_paper_head):
    """reader.pmc_head('PMC123456') calls URL /pmc/PMC123456/head."""
    r = Reader(base_url=base_url)
    with patch.object(r, "_make_request", return_value=sample_paper_head) as mock_req:
        result = r.pmc_head("PMC123456")
    mock_req.assert_called_once()
    called_url = mock_req.call_args[0][0]
    assert "/pmc/PMC123456/head" in called_url


def test_pmc_full_uses_path_param(base_url, sample_full_response):
    """reader.pmc_full('PMC123456') calls URL /pmc/PMC123456/full."""
    r = Reader(base_url=base_url)
    with patch.object(r, "_make_request", return_value=sample_full_response) as mock_req:
        result = r.pmc_full("PMC123456")
    mock_req.assert_called_once()
    called_url = mock_req.call_args[0][0]
    assert "/pmc/PMC123456/full" in called_url


def test_pmc_json_alias(base_url, sample_full_response):
    """pmc_json() is an alias for pmc_full()."""
    r = Reader(base_url=base_url)
    with patch.object(r, "_make_request", return_value=sample_full_response) as mock_req:
        result = r.pmc_json("PMC123456")
    called_url = mock_req.call_args[0][0]
    assert "/pmc/PMC123456/full" in called_url


# ---------------------------------------------------------------------------
# NotImplementedError stub tests
# ---------------------------------------------------------------------------

def test_websearch_raises_not_implemented():
    """websearch() raises NotImplementedError."""
    r = Reader()
    with pytest.raises(NotImplementedError):
        r.websearch("test query")


def test_trending_raises_not_implemented():
    """trending() raises NotImplementedError."""
    r = Reader()
    with pytest.raises(NotImplementedError):
        r.trending()


def test_semantic_scholar_raises_not_implemented():
    """semantic_scholar() raises NotImplementedError."""
    r = Reader()
    with pytest.raises(NotImplementedError):
        r.semantic_scholar("258001")


def test_biomed_search_raises_not_implemented():
    """biomed_search() raises NotImplementedError."""
    r = Reader()
    with pytest.raises(NotImplementedError):
        r.biomed_search("test")


def test_biomed_data_raises_not_implemented():
    """biomed_data() raises NotImplementedError."""
    r = Reader()
    with pytest.raises(NotImplementedError):
        r.biomed_data("10.1101/2021.02.26.433129")


def test_social_impact_raises_not_implemented():
    """social_impact() raises NotImplementedError."""
    r = Reader()
    with pytest.raises(NotImplementedError):
        r.social_impact("2401.00001")


def test_markdown_raises_not_implemented():
    """markdown() raises NotImplementedError."""
    r = Reader()
    with pytest.raises(NotImplementedError):
        r.markdown("2401.00001")


def test_preview_raises_not_implemented():
    """preview() raises NotImplementedError."""
    r = Reader()
    with pytest.raises(NotImplementedError):
        r.preview("2401.00001")


# ---------------------------------------------------------------------------
# Input validation tests
# ---------------------------------------------------------------------------

def test_head_empty_id_raises():
    """head('') raises ValueError."""
    r = Reader()
    with pytest.raises(ValueError):
        r.head("")


def test_brief_empty_id_raises():
    """brief('') raises ValueError."""
    r = Reader()
    with pytest.raises(ValueError):
        r.brief("")


def test_sections_empty_id_raises():
    """sections('') raises ValueError."""
    r = Reader()
    with pytest.raises(ValueError):
        r.sections("")


def test_section_empty_id_raises():
    """section('', 'Introduction') raises ValueError."""
    r = Reader()
    with pytest.raises(ValueError):
        r.section("", "Introduction")


def test_section_empty_name_raises():
    """section('2401.00001', '') raises ValueError."""
    r = Reader()
    with pytest.raises(ValueError):
        r.section("2401.00001", "")


def test_search_empty_query_raises():
    """search('') raises ValueError."""
    r = Reader()
    with pytest.raises(ValueError):
        r.search("")


def test_search_size_too_small_raises():
    """search('q', size=0) raises ValueError."""
    r = Reader()
    with pytest.raises(ValueError):
        r.search("attention", size=0)


def test_search_size_too_large_raises():
    """search('q', size=101) raises ValueError."""
    r = Reader()
    with pytest.raises(ValueError):
        r.search("attention", size=101)


def test_search_negative_offset_raises():
    """search('q', offset=-1) raises ValueError."""
    r = Reader()
    with pytest.raises(ValueError):
        r.search("attention", offset=-1)


# ---------------------------------------------------------------------------
# HTTP error handling tests
# ---------------------------------------------------------------------------

def test_make_request_handles_401():
    """_make_request raises AuthenticationError on 401."""
    from deepxiv_sdk import AuthenticationError
    import requests
    r = Reader()
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "Unauthorized"
    with patch("requests.get", return_value=mock_resp):
        with pytest.raises(AuthenticationError):
            r._make_request("http://localhost:8000/arxiv/2401.00001/head")


def test_make_request_handles_404():
    """_make_request raises NotFoundError on 404."""
    from deepxiv_sdk import NotFoundError
    r = Reader()
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.text = "Not Found"
    with patch("requests.get", return_value=mock_resp):
        with pytest.raises(NotFoundError):
            r._make_request("http://localhost:8000/arxiv/9999.99999/head")


def test_make_request_handles_empty_body():
    """_make_request returns {} on empty response body."""
    r = Reader()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b""
    mock_resp.raise_for_status.return_value = None
    with patch("requests.get", return_value=mock_resp):
        result = r._make_request("http://localhost:8000/arxiv/2401.00001/head")
    assert result == {}
