"""
Pytest configuration and shared fixtures for deepxiv-sdk tests.
Fixture field names match app/api/schemas.py exactly.
"""
import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: marks integration tests")


@pytest.fixture
def base_url():
    return "http://localhost:8000"


@pytest.fixture
def sample_arxiv_id():
    return "2401.00001"


@pytest.fixture
def sample_paper_head():
    return {
        "paper_id": "00000000-0000-0000-0000-000000000001",
        "arxiv_id": "2401.00001",
        "pmc_id": None,
        "doi": None,
        "title": "Test Paper on Attention Mechanisms",
        "abstract": "This paper studies attention. We find results.",
        "tldr": "This paper studies attention.",
        "authors": ["Author One", "Author Two"],
        "year": 2024,
        "venue": None,
        "src_url": "https://arxiv.org/abs/2401.00001",
        "token_count": 5120,
        "parse_source": "latex",
    }


@pytest.fixture
def sample_sections_response():
    return {
        "paper_id": "00000000-0000-0000-0000-000000000001",
        "title": "Test Paper on Attention Mechanisms",
        "sections": [
            {"heading": "Introduction", "sec_num": "1", "text": "We study attention.", "paragraphs": [], "token_count": 100},
            {"heading": "Methods", "sec_num": "2", "text": "Our method uses transformers.", "paragraphs": [], "token_count": 200},
        ],
        "token_count": 300,
    }


@pytest.fixture
def sample_full_response(sample_paper_head, sample_sections_response):
    return {
        **sample_paper_head,
        "sections": sample_sections_response["sections"],
        "citations": [{"ref_id": "b0", "title": "Cited Paper", "authors": ["Cited Author"], "year": 2023, "venue": "NeurIPS", "doi": None, "arxiv_id": "2301.00001", "raw_text": "As shown in [1]..."}],
        "ref_entries": {},
        "back_matter": [],
    }


@pytest.fixture
def sample_search_response(sample_paper_head):
    return {
        "total": 1,
        "results": [{k: v for k, v in sample_paper_head.items() if k in ("paper_id", "arxiv_id", "pmc_id", "title", "abstract", "tldr", "authors", "year", "src_url", "token_count")}],
    }


@pytest.fixture
def sample_references_response():
    return {
        "paper_id": "00000000-0000-0000-0000-000000000001",
        "references": [
            {"target_arxiv_id": "2301.00001", "target_doi": None, "context_text": "As shown in [1]", "in_corpus": True, "paper_id": "00000000-0000-0000-0000-000000000002", "title": "Cited Paper", "abstract": "A cited paper.", "authors": ["Cited Author"], "year": 2023, "arxiv_id": "2301.00001", "pmc_id": None, "doi": None, "tldr": "A cited paper.", "token_count": 3000},
        ],
    }


@pytest.fixture
def sample_cited_by_response():
    return {
        "paper_id": "00000000-0000-0000-0000-000000000001",
        "cited_by": [
            {"paper_id": "00000000-0000-0000-0000-000000000003", "arxiv_id": "2402.00001", "pmc_id": None, "title": "Citing Paper", "abstract": "We cite the test paper.", "authors": ["Citing Author"], "year": 2024, "tldr": "We cite.", "token_count": 4000, "context_text": "Building on [1]"},
        ],
    }
