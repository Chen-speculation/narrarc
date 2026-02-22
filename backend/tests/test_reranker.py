"""Tests for Reranker implementations."""

import pytest
from unittest.mock import patch, MagicMock

from narrative_mirror.llm import StubReranker, OpenAICompatibleReranker
from narrative_mirror.config import RerankerConfig


class TestStubReranker:
    """Tests for StubReranker test double."""

    def test_returns_fixed_score(self):
        """Should return 0.8 for all pairs by default."""
        reranker = StubReranker()
        scores = reranker.rerank([("q1", "d1"), ("q2", "d2")])
        assert scores == [0.8, 0.8]

    def test_returns_custom_score(self):
        """Should return custom score when configured."""
        reranker = StubReranker(score=0.5)
        scores = reranker.rerank([("q1", "d1")])
        assert scores == [0.5]

    def test_empty_input(self):
        """Should return empty list for empty input."""
        reranker = StubReranker()
        scores = reranker.rerank([])
        assert scores == []

    def test_score_list_length_matches_input(self):
        """Output length should match input length."""
        reranker = StubReranker()
        pairs = [("q1", "d1"), ("q2", "d2"), ("q3", "d3")]
        scores = reranker.rerank(pairs)
        assert len(scores) == len(pairs)


class TestOpenAICompatibleReranker:
    """Tests for OpenAICompatibleReranker."""

    def test_request_body_format(self):
        """Should send correct request body format."""
        cfg = RerankerConfig(
            model="BAAI/bge-reranker-v2-m3",
            api_key="test-key",
            base_url="https://api.example.com/v1",
        )
        reranker = OpenAICompatibleReranker(cfg)

        with patch.object(reranker._client, "post") as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {"results": [{"relevance_score": 0.73}]}
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_response

            scores = reranker.rerank([("query text", "doc text")])

            # Verify request was made with correct body
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert call_args[1]["json"]["model"] == "BAAI/bge-reranker-v2-m3"
            assert call_args[1]["json"]["query"] == "query text"
            assert call_args[1]["json"]["documents"] == ["doc text"]

    def test_score_extraction_from_response(self):
        """Should extract relevance_score from response."""
        cfg = RerankerConfig(
            model="test-model",
            api_key="test-key",
            base_url="https://api.example.com/v1",
        )
        reranker = OpenAICompatibleReranker(cfg)

        with patch.object(reranker._client, "post") as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "results": [{"relevance_score": 0.73}]
            }
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_response

            scores = reranker.rerank([("q", "d")])
            assert scores == [0.73]

    def test_multiple_pairs_separate_requests(self):
        """Should make separate HTTP requests for each pair."""
        cfg = RerankerConfig(
            model="test-model",
            api_key="test-key",
            base_url="https://api.example.com/v1",
        )
        reranker = OpenAICompatibleReranker(cfg)

        with patch.object(reranker._client, "post") as mock_post:
            mock_response = MagicMock()
            # Return different scores for each call
            mock_response.json.side_effect = [
                {"results": [{"relevance_score": 0.8}]},
                {"results": [{"relevance_score": 0.5}]},
            ]
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_response

            scores = reranker.rerank([("q1", "d1"), ("q2", "d2")])

            assert scores == [0.8, 0.5]
            assert mock_post.call_count == 2

    def test_empty_results_returns_zero(self):
        """Should return 0.0 when results are empty."""
        cfg = RerankerConfig(
            model="test-model",
            api_key="test-key",
            base_url="https://api.example.com/v1",
        )
        reranker = OpenAICompatibleReranker(cfg)

        with patch.object(reranker._client, "post") as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {"results": []}
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_response

            scores = reranker.rerank([("q", "d")])
            assert scores == [0.0]

    def test_strips_trailing_slash_from_base_url(self):
        """Should strip trailing slash from base_url."""
        cfg = RerankerConfig(
            model="test-model",
            api_key="test-key",
            base_url="https://api.example.com/v1/",
        )
        reranker = OpenAICompatibleReranker(cfg)
        assert reranker.base_url == "https://api.example.com/v1"
