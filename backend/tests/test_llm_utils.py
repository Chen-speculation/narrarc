"""Tests for LLM utility functions."""

from narrative_mirror.llm import _normalize_chat_base_url, _strip_json_fences


class TestNormalizeChatBaseUrl:
    """Tests for _normalize_chat_base_url helper."""

    def test_strips_chat_completions_suffix(self):
        """Should strip /chat/completions suffix."""
        url = "https://host/api/gateway/v1/endpoints/chat/completions"
        result = _normalize_chat_base_url(url)
        assert result == "https://host/api/gateway/v1/endpoints"

    def test_strips_v1_chat_completions_suffix(self):
        """Should strip /v1/chat/completions suffix."""
        url = "https://host/api/v1/chat/completions"
        result = _normalize_chat_base_url(url)
        assert result == "https://host/api"

    def test_unchanged_when_no_suffix(self):
        """Should return unchanged URL when no suffix."""
        url = "https://api.siliconflow.cn/v1"
        result = _normalize_chat_base_url(url)
        assert result == "https://api.siliconflow.cn/v1"

    def test_strips_trailing_slash(self):
        """Should strip trailing slash before processing."""
        url = "https://host/v1/chat/completions/"
        result = _normalize_chat_base_url(url)
        assert result == "https://host/v1"

    def test_standard_openai_url(self):
        """Should work with standard OpenAI URL."""
        url = "https://api.openai.com/v1"
        result = _normalize_chat_base_url(url)
        assert result == "https://api.openai.com/v1"


class TestStripJsonFences:
    """Tests for _strip_json_fences helper."""

    def test_strips_json_code_fence(self):
        """Should strip ```json ... ``` fences."""
        text = '```json\n{"key": "value"}\n```'
        assert _strip_json_fences(text) == '{"key": "value"}'

    def test_strips_plain_code_fence(self):
        """Should strip ``` ... ``` fences without language tag."""
        text = '```\n{"key": "value"}\n```'
        assert _strip_json_fences(text) == '{"key": "value"}'

    def test_passthrough_plain_json(self):
        """Should leave plain JSON unchanged."""
        text = '{"key": "value"}'
        assert _strip_json_fences(text) == '{"key": "value"}'

    def test_strips_surrounding_whitespace(self):
        """Should strip surrounding whitespace."""
        text = '  \n```json\n{"a": 1}\n```\n  '
        assert _strip_json_fences(text) == '{"a": 1}'

    def test_case_insensitive_fence(self):
        """Should handle ```JSON (uppercase) fences."""
        text = '```JSON\n{"key": "value"}\n```'
        assert _strip_json_fences(text) == '{"key": "value"}'

    """Tests for _normalize_chat_base_url helper."""

    def test_strips_chat_completions_suffix(self):
        """Should strip /chat/completions suffix."""
        url = "https://host/api/gateway/v1/endpoints/chat/completions"
        result = _normalize_chat_base_url(url)
        assert result == "https://host/api/gateway/v1/endpoints"

    def test_strips_v1_chat_completions_suffix(self):
        """Should strip /v1/chat/completions suffix."""
        url = "https://host/api/v1/chat/completions"
        result = _normalize_chat_base_url(url)
        assert result == "https://host/api"

    def test_unchanged_when_no_suffix(self):
        """Should return unchanged URL when no suffix."""
        url = "https://api.siliconflow.cn/v1"
        result = _normalize_chat_base_url(url)
        assert result == "https://api.siliconflow.cn/v1"

    def test_strips_trailing_slash(self):
        """Should strip trailing slash before processing."""
        url = "https://host/v1/chat/completions/"
        result = _normalize_chat_base_url(url)
        assert result == "https://host/v1"

    def test_standard_openai_url(self):
        """Should work with standard OpenAI URL."""
        url = "https://api.openai.com/v1"
        result = _normalize_chat_base_url(url)
        assert result == "https://api.openai.com/v1"
