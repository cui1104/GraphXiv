"""
Unit tests for trending and social impact features.

NOTE: These tests were written for the upstream data.rag.ac.cn service.
trending() and social_impact() raise NotImplementedError in this SDK fork
because the local backend does not support them (upstream-only endpoints).
Tests are skipped automatically.
"""

import pytest
from deepxiv_sdk import Reader, AuthenticationError

# Skip entire module — trending/social_impact are upstream-only stubs in this fork
pytestmark = pytest.mark.skip(reason="trending() and social_impact() are upstream-only stubs in this SDK fork; local backend does not support them")


class TestTrending:
    """Test trending functionality"""

    def test_trending_valid_days(self):
        """Test trending with valid days parameter"""
        reader = Reader()

        # Test with days=7
        result = reader.trending(days=7, limit=5)
        assert isinstance(result, dict)
        assert "papers" in result
        assert "total" in result
        assert isinstance(result["papers"], list)

    def test_trending_all_valid_days(self):
        """Test trending with all valid day options"""
        reader = Reader()

        for days in [7, 14, 30]:
            result = reader.trending(days=days, limit=2)
            assert isinstance(result, dict)
            assert result.get("days") == days

    def test_trending_invalid_days(self):
        """Test trending with invalid days parameter"""
        reader = Reader()

        with pytest.raises(ValueError, match="days must be 7, 14, or 30"):
            reader.trending(days=15, limit=5)

        with pytest.raises(ValueError, match="days must be 7, 14, or 30"):
            reader.trending(days=1, limit=5)

    def test_trending_invalid_limit(self):
        """Test trending with invalid limit parameter"""
        reader = Reader()

        with pytest.raises(ValueError, match="limit must be between 1 and 100"):
            reader.trending(days=7, limit=0)

        with pytest.raises(ValueError, match="limit must be between 1 and 100"):
            reader.trending(days=7, limit=101)

    def test_trending_limit_respected(self):
        """Test that trending respects the limit parameter"""
        reader = Reader()

        result = reader.trending(days=7, limit=3)
        # API might return fewer results, but shouldn't exceed limit
        assert len(result.get("papers", [])) <= 3

    def test_trending_response_structure(self):
        """Test the structure of trending response"""
        reader = Reader()

        result = reader.trending(days=7, limit=5)

        # Check top-level fields
        assert "days" in result
        assert "total" in result
        assert "generated_at" in result
        assert "papers" in result

        # Check paper structure
        papers = result.get("papers", [])
        if papers:
            paper = papers[0]
            assert "arxiv_id" in paper
            assert "rank" in paper
            assert "stats" in paper


class TestSocialImpact:
    """Test social impact functionality"""

    def test_social_impact_requires_token(self):
        """Test that social_impact requires a token"""
        reader = Reader()  # No token

        with pytest.raises(
            AuthenticationError, match="Token is required"
        ):
            reader.social_impact("2409.05592")

    def test_social_impact_invalid_arxiv_id(self):
        """Test social_impact with empty arxiv_id"""
        reader = Reader(token="dummy_token")

        with pytest.raises(ValueError, match="arxiv_id cannot be empty"):
            reader.social_impact("")

        with pytest.raises(ValueError, match="arxiv_id cannot be empty"):
            reader.social_impact("   ")

    def test_social_impact_none_for_missing_data(self):
        """Test that social_impact returns None for papers without data"""
        reader = Reader(token="dummy_token")

        # This should return None or raise an error
        # The exact behavior depends on the API
        try:
            result = reader.social_impact("1106.0001")
            assert result is None or isinstance(result, dict)
        except Exception:
            # API might raise an error instead of returning None
            pass


class TestTrendingIntegration:
    """Integration tests for trending features"""

    def test_trending_returns_valid_arxiv_ids(self):
        """Test that trending returns valid arXiv IDs"""
        reader = Reader()

        result = reader.trending(days=7, limit=5)
        papers = result.get("papers", [])

        for paper in papers:
            arxiv_id = paper.get("arxiv_id")
            # Basic validation: arxiv_id should not be empty
            assert arxiv_id and len(arxiv_id) > 0

    def test_trending_default_parameters(self):
        """Test trending with default parameters"""
        reader = Reader()

        result = reader.trending()  # Uses default days=7, limit=30
        assert isinstance(result, dict)
        assert "papers" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
