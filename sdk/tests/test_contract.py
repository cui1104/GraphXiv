"""Contract verification: every Reader method returns correctly shaped data.

These tests use mock.patch to verify Reader methods pass through and return
the expected shape without needing a live backend.

Run with: pytest tests/test_contract.py -v
"""
from unittest.mock import patch, MagicMock
import pytest
from deepxiv_sdk import Reader


@pytest.fixture
def reader():
    return Reader(base_url="http://localhost:8000")


class TestHeadContract:
    def test_head_returns_dict(self, reader, sample_paper_head):
        with patch.object(reader, "_make_request", return_value=sample_paper_head):
            result = reader.head("2401.00001")
        assert isinstance(result, dict)

    def test_head_has_required_fields(self, reader, sample_paper_head):
        with patch.object(reader, "_make_request", return_value=sample_paper_head):
            result = reader.head("2401.00001")
        for field in ["paper_id", "arxiv_id", "title", "abstract", "tldr", "authors", "year", "src_url", "token_count", "parse_source"]:
            assert field in result, f"Missing field: {field}"

    def test_head_title_not_none(self, reader, sample_paper_head):
        with patch.object(reader, "_make_request", return_value=sample_paper_head):
            result = reader.head("2401.00001")
        assert result["title"] is not None

    def test_head_authors_are_strings(self, reader, sample_paper_head):
        with patch.object(reader, "_make_request", return_value=sample_paper_head):
            result = reader.head("2401.00001")
        assert isinstance(result["authors"], list)
        assert all(isinstance(a, str) for a in result["authors"])

    def test_head_token_count_is_int(self, reader, sample_paper_head):
        with patch.object(reader, "_make_request", return_value=sample_paper_head):
            result = reader.head("2401.00001")
        assert isinstance(result["token_count"], int)
        assert result["token_count"] > 0

    def test_head_tldr_key_present(self, reader, sample_paper_head):
        """NORM-03: tldr key always present (value may be None)."""
        with patch.object(reader, "_make_request", return_value=sample_paper_head):
            result = reader.head("2401.00001")
        assert "tldr" in result

    def test_head_url_is_path_param_style(self, reader, sample_paper_head):
        """Verify Reader uses path-param URL style: /arxiv/{id}/head."""
        with patch.object(reader, "_make_request", return_value=sample_paper_head) as mock_req:
            reader.head("2401.00001")
        called_url = mock_req.call_args[0][0]
        assert "/arxiv/2401.00001/head" in called_url


class TestBriefContract:
    def test_brief_returns_dict(self, reader, sample_paper_head):
        with patch.object(reader, "_make_request", return_value=sample_paper_head):
            result = reader.brief("2401.00001")
        assert isinstance(result, dict)
        assert result["title"] is not None

    def test_brief_has_required_fields(self, reader, sample_paper_head):
        with patch.object(reader, "_make_request", return_value=sample_paper_head):
            result = reader.brief("2401.00001")
        for field in ["paper_id", "arxiv_id", "title", "abstract", "tldr", "authors", "year", "src_url", "token_count"]:
            assert field in result, f"Missing field: {field}"

    def test_brief_tldr_key_present(self, reader, sample_paper_head):
        """NORM-03: tldr key always present (value may be None)."""
        with patch.object(reader, "_make_request", return_value=sample_paper_head):
            result = reader.brief("2401.00001")
        assert "tldr" in result


class TestSectionsContract:
    def test_sections_returns_list(self, reader, sample_sections_response):
        with patch.object(reader, "_make_request", return_value=sample_sections_response):
            result = reader.sections("2401.00001")
        assert "sections" in result
        assert isinstance(result["sections"], list)
        assert len(result["sections"]) > 0

    def test_section_objects_have_required_fields(self, reader, sample_sections_response):
        with patch.object(reader, "_make_request", return_value=sample_sections_response):
            result = reader.sections("2401.00001")
        for sec in result["sections"]:
            for field in ["heading", "text", "token_count"]:
                assert field in sec, f"Section missing field: {field}"

    def test_sections_has_paper_id(self, reader, sample_sections_response):
        with patch.object(reader, "_make_request", return_value=sample_sections_response):
            result = reader.sections("2401.00001")
        assert "paper_id" in result

    def test_sections_title_present(self, reader, sample_sections_response):
        with patch.object(reader, "_make_request", return_value=sample_sections_response):
            result = reader.sections("2401.00001")
        assert "title" in result


class TestFullContract:
    def test_full_has_sections_and_citations(self, reader, sample_full_response):
        with patch.object(reader, "_make_request", return_value=sample_full_response):
            result = reader.full("2401.00001")
        assert "sections" in result
        assert "citations" in result
        assert isinstance(result["sections"], list)
        assert isinstance(result["citations"], list)

    def test_full_includes_head_fields(self, reader, sample_full_response):
        with patch.object(reader, "_make_request", return_value=sample_full_response):
            result = reader.full("2401.00001")
        for field in ["paper_id", "arxiv_id", "title", "abstract", "tldr", "authors", "year", "src_url", "token_count"]:
            assert field in result, f"FullResponse missing head field: {field}"

    def test_full_citation_objects_have_required_fields(self, reader, sample_full_response):
        with patch.object(reader, "_make_request", return_value=sample_full_response):
            result = reader.full("2401.00001")
        for cit in result["citations"]:
            for field in ["ref_id", "title", "authors", "year"]:
                assert field in cit, f"Citation missing field: {field}"

    def test_raw_alias_calls_full(self, reader, sample_full_response):
        """raw() is an alias for full() — same result."""
        with patch.object(reader, "_make_request", return_value=sample_full_response):
            result = reader.raw("2401.00001")
        assert "sections" in result
        assert "citations" in result

    def test_json_alias_calls_full(self, reader, sample_full_response):
        """json() is an alias for full() — same result."""
        with patch.object(reader, "_make_request", return_value=sample_full_response):
            result = reader.json("2401.00001")
        assert "sections" in result
        assert "citations" in result


class TestSearchContract:
    def test_search_returns_total_and_results(self, reader, sample_search_response):
        with patch.object(reader, "_make_request", return_value=sample_search_response):
            result = reader.search("attention")
        assert "total" in result
        assert "results" in result
        assert result["total"] >= 1
        assert len(result["results"]) >= 1

    def test_search_result_items_have_required_fields(self, reader, sample_search_response):
        with patch.object(reader, "_make_request", return_value=sample_search_response):
            result = reader.search("attention")
        for item in result["results"]:
            for field in ["paper_id", "arxiv_id", "title", "authors", "src_url", "token_count"]:
                assert field in item, f"SearchResultItem missing field: {field}"

    def test_search_empty_query_raises(self, reader):
        with pytest.raises(ValueError, match="Query cannot be empty"):
            reader.search("")

    def test_search_uses_size_param(self, reader, sample_search_response):
        """search() uses 'size' kwarg mapped to 'limit' query param."""
        with patch.object(reader, "_make_request", return_value=sample_search_response) as mock_req:
            reader.search("attention", size=5)
        called_params = mock_req.call_args[1].get("params") or mock_req.call_args[0][1]
        assert called_params.get("limit") == 5

    def test_search_result_title_not_none(self, reader, sample_search_response):
        with patch.object(reader, "_make_request", return_value=sample_search_response):
            result = reader.search("attention")
        for item in result["results"]:
            assert item.get("title") is not None, "SearchResultItem title should not be None"


class TestInputValidation:
    def test_head_empty_id_raises(self, reader):
        with pytest.raises(ValueError):
            reader.head("")

    def test_brief_empty_id_raises(self, reader):
        with pytest.raises(ValueError):
            reader.brief("")

    def test_sections_empty_id_raises(self, reader):
        with pytest.raises(ValueError):
            reader.sections("")

    def test_full_empty_id_raises(self, reader):
        with pytest.raises(ValueError):
            reader.full("")
