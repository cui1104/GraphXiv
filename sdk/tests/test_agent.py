"""Tests for citation-aware Agent tools (SDK-03, SDK-04)."""
from unittest.mock import patch, MagicMock
import pytest
from deepxiv_sdk import Reader
from deepxiv_sdk.agent.tools import ToolExecutor


@pytest.fixture
def reader():
    return Reader(base_url="http://localhost:8000")


@pytest.fixture
def tool_executor(reader):
    return ToolExecutor(reader, citation_depth=1)


@pytest.fixture
def mock_references_response():
    return {
        "paper_id": "uuid-1",
        "references": [
            {"target_arxiv_id": "2301.00001", "in_corpus": True, "arxiv_id": "2301.00001", "title": "Cited Paper A", "authors": ["Auth A"], "year": 2023},
            {"target_arxiv_id": "2302.00002", "in_corpus": False, "arxiv_id": None, "title": "External Paper", "authors": [], "year": 2023},
            {"target_arxiv_id": "2303.00003", "in_corpus": True, "arxiv_id": "2303.00003", "title": "Cited Paper B", "authors": ["Auth B"], "year": 2023},
        ],
    }


@pytest.fixture
def mock_cited_by_response():
    return {
        "paper_id": "uuid-1",
        "cited_by": [
            {"paper_id": "uuid-2", "arxiv_id": "2402.00001", "title": "Citing Paper", "authors": ["Auth C"], "year": 2024},
        ],
    }


@pytest.fixture
def mock_sections_response():
    return {
        "paper_id": "uuid-2",
        "title": "Cited Paper A",
        "sections": [
            {"heading": "Introduction", "text": "This paper introduces...", "sec_num": "1", "paragraphs": [], "token_count": 100},
        ],
        "token_count": 100,
    }


class TestToolExecutorInit:
    def test_default_citation_depth(self, reader):
        te = ToolExecutor(reader)
        assert te.citation_depth == 1

    def test_custom_citation_depth(self, reader):
        te = ToolExecutor(reader, citation_depth=3)
        assert te.citation_depth == 3


class TestGetReferencesTool:
    def test_returns_string(self, tool_executor, mock_references_response):
        with patch.object(tool_executor.reader, "references", return_value=mock_references_response):
            result = tool_executor.get_references("2401.00001")
        assert isinstance(result, str)
        assert "references" in result.lower()

    def test_shows_in_corpus_papers(self, tool_executor, mock_references_response):
        with patch.object(tool_executor.reader, "references", return_value=mock_references_response):
            result = tool_executor.get_references("2401.00001")
        assert "2301.00001" in result
        assert "Cited Paper A" in result

    def test_calls_reader_references(self, tool_executor, mock_references_response):
        with patch.object(tool_executor.reader, "references", return_value=mock_references_response) as mock_ref:
            tool_executor.get_references("2401.00001")
        mock_ref.assert_called_once_with("2401.00001")


class TestGetCitedByTool:
    def test_returns_string(self, tool_executor, mock_cited_by_response):
        with patch.object(tool_executor.reader, "cited_by", return_value=mock_cited_by_response):
            result = tool_executor.get_cited_by("2401.00001")
        assert isinstance(result, str)
        assert "cited by" in result.lower()

    def test_shows_citing_papers(self, tool_executor, mock_cited_by_response):
        with patch.object(tool_executor.reader, "cited_by", return_value=mock_cited_by_response):
            result = tool_executor.get_cited_by("2401.00001")
        assert "2402.00001" in result
        assert "Citing Paper" in result


class TestFetchCitedPaperSections:
    def test_fetches_in_corpus_only(self, tool_executor, mock_references_response, mock_sections_response):
        with patch.object(tool_executor.reader, "references", return_value=mock_references_response):
            with patch.object(tool_executor.reader, "sections", return_value=mock_sections_response):
                result = tool_executor.fetch_cited_paper_sections("2401.00001")
        assert isinstance(result, str)
        # Should contain content from in-corpus papers
        assert "Introduction" in result or "Cited Paper" in result

    def test_respects_citation_depth_cap(self, reader, mock_references_response, mock_sections_response):
        te = ToolExecutor(reader, citation_depth=1)
        # With depth=1, max_papers = 5, so 2 in-corpus refs should both be fetched
        with patch.object(te.reader, "references", return_value=mock_references_response):
            with patch.object(te.reader, "sections", return_value=mock_sections_response) as mock_sec:
                te.fetch_cited_paper_sections("2401.00001")
        # Should have called sections for the 2 in-corpus refs
        assert mock_sec.call_count == 2

    def test_handles_empty_references(self, tool_executor):
        empty_response = {"paper_id": "uuid-1", "references": []}
        with patch.object(tool_executor.reader, "references", return_value=empty_response):
            result = tool_executor.fetch_cited_paper_sections("2401.00001")
        assert "No in-corpus" in result or "0" in result

    def test_silently_skips_failed_fetches(self, tool_executor, mock_references_response):
        with patch.object(tool_executor.reader, "references", return_value=mock_references_response):
            with patch.object(tool_executor.reader, "sections", side_effect=Exception("Network error")):
                result = tool_executor.fetch_cited_paper_sections("2401.00001")
        # Should not raise, should return gracefully
        assert isinstance(result, str)


class TestToolDefinitions:
    def test_citation_tools_in_definitions(self, tool_executor):
        # get_tools_definition() returns list of dicts with {"type": "function", "function": {"name": ...}}
        tools = tool_executor.get_tools_definition()
        tool_names = [
            t["function"]["name"] if isinstance(t, dict) and "function" in t
            else t.get("name", "")
            for t in tools
        ]
        assert "get_references" in tool_names
        assert "get_cited_by" in tool_names
        assert "fetch_cited_paper_sections" in tool_names
