"""Integration tests for LLM adapters.

These tests are skipped in CI via pytest.mark.integration.
Run with: pytest -m integration tests/test_adapters_integration.py
"""

import pytest

from narrative_mirror.config import load_config, Config, LLMConfig, EmbeddingConfig
from narrative_mirror.llm import from_config, OpenAICompatibleNonCoTLLM, OpenAICompatibleCoTLLM


# Mark all tests in this file as integration tests
pytestmark = pytest.mark.integration


@pytest.fixture
def config():
    """Load config if available, skip if not."""
    try:
        return load_config("config.yml")
    except FileNotFoundError:
        pytest.skip("config.yml not found - skipping integration tests")


class TestOpenAICompatibleNonCoTLLM:
    """Integration tests for OpenAI-compatible NonCoT LLM."""

    def test_embed_returns_1024_dimensions(self, config):
        """Embed should return a 1024-dimensional vector."""
        noncot, _ = from_config(config)

        result = noncot.embed("测试文本")

        assert len(result) == 1024, f"Expected 1024 dimensions, got {len(result)}"

    def test_complete_returns_valid_json(self, config):
        """Complete should return valid JSON for structured prompts."""
        noncot, _ = from_config(config)

        system = "你是一个分类助手，返回JSON格式的结果。"
        prompt = '请返回: {"status": "ok"}'

        result = noncot.complete(system, prompt)

        # Should be valid JSON
        import json
        try:
            json.loads(result)
        except json.JSONDecodeError:
            pytest.fail(f"Expected valid JSON, got: {result}")


class TestOpenAICompatibleCoTLLM:
    """Integration tests for OpenAI-compatible CoT LLM."""

    def test_think_and_complete_returns_response(self, config):
        """Think and complete should return a response."""
        _, cot = from_config(config)

        system = "你是一个有帮助的助手。"
        prompt = "请说'测试成功'"

        result = cot.think_and_complete(system, prompt, max_tokens=100)

        assert len(result) > 0, "Expected non-empty response"


class TestFromConfig:
    """Tests for the from_config factory function."""

    def test_creates_both_adapters(self, config):
        """from_config should create both NonCoT and CoT adapters."""
        noncot, cot = from_config(config)

        assert noncot is not None
        assert cot is not None
