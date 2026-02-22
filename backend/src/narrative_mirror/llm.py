"""LLM protocol definitions and test doubles."""

from typing import Protocol, TYPE_CHECKING
import random
import math
import time

import httpx
from openai import OpenAI

if TYPE_CHECKING:
    from .config import Config, LLMConfig, EmbeddingConfig, RerankerConfig


def _strip_json_fences(text: str) -> str:
    """Strip markdown code fences from LLM output.

    Some models wrap JSON output in ```json ... ``` even when response_format
    is set to json_object. This strips those fences so json.loads() can parse
    the result.

    Args:
        text: Raw LLM output.

    Returns:
        Text with markdown code fences removed.
    """
    import re
    text = text.strip()
    # Strip ```json ... ``` or ``` ... ```
    text = re.sub(r"^```(?:json)?\s*\n?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


def _normalize_chat_base_url(url: str) -> str:
    """Strip /chat/completions suffix from base_url if present.

    The OpenAI SDK appends '/chat/completions' itself, so passing a URL
    that already includes this suffix causes double-appending.

    Also strips the /v1 path segment when it appears as part of a custom
    gateway path (e.g. /api/v1/chat/completions → /api), but leaves /v1
    intact when it is the root API version (e.g. host/v1).

    Args:
        url: The base URL to normalize.

    Returns:
        The normalized URL without /chat/completions suffix.
    """
    from urllib.parse import urlparse

    url = url.rstrip("/")

    if url.endswith("/chat/completions"):
        url = url[:-len("/chat/completions")]

    # Strip /v1 only when it sits inside a non-trivial path (e.g. /api/v1).
    # When /v1 is the only path component (e.g. https://host/v1) it is the
    # standard API version prefix used by the OpenAI SDK and must be kept.
    if url.endswith("/v1"):
        base = url[:-len("/v1")]
        if urlparse(base).path.strip("/"):
            url = base

    return url


class NonCoTLLM(Protocol):
    """Fast completion without chain-of-thought. Used for bulk classification."""

    def complete(self, system: str, prompt: str, max_tokens: int = 1024, response_format: str | None = None) -> str:
        """Generate a completion without chain-of-thought reasoning.

        Args:
            system: System prompt for context.
            prompt: User prompt to respond to.
            max_tokens: Maximum tokens to generate.
            response_format: Optional response format. If "json_object", forces JSON output.

        Returns:
            The generated text.
        """
        ...

    def embed(self, text: str) -> list[float]:
        """Generate an embedding for the given text.

        Args:
            text: Text to embed.

        Returns:
            A fixed-dimension float vector (1024 dimensions for BAAI/bge-m3).
        """
        ...

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts in a single API call.

        Args:
            texts: List of texts to embed.

        Returns:
            List of float vectors in the same order as input.
        """
        ...


class CoTLLM(Protocol):
    """Slow reasoning with chain-of-thought. Used for intent parsing and narrative."""

    def think_and_complete(self, system: str, prompt: str, max_tokens: int = 4096) -> str:
        """Generate a completion with chain-of-thought reasoning.

        Args:
            system: System prompt for context.
            prompt: User prompt to respond to.
            max_tokens: Maximum tokens to generate.

        Returns:
            The generated text with reasoning.
        """
        ...


class Reranker(Protocol):
    """Reranker for scoring text pairs."""

    def rerank(self, pairs: list[tuple[str, str]]) -> list[float]:
        """Score each (query, passage) pair.

        Args:
            pairs: List of (query_text, passage_text) tuples.

        Returns:
            List of relevance scores (0.0 to 1.0) in the same order as input.
        """
        ...


class StubNonCoTLLM:
    """Test double for NonCoTLLM that returns hardcoded responses."""

    def __init__(self, embed_dim: int = 1024):
        self.embed_dim = embed_dim
        self._call_count = 0

    def complete(self, system: str, prompt: str, max_tokens: int = 1024, response_format: str | None = None) -> str:
        """Return a hardcoded valid JSON string for topic classification."""
        self._call_count += 1
        # Default: single-topic burst classification
        return '{"topic_name": "日常聊天", "segments": [{"topic_name": "日常聊天", "start_local_id": 1, "end_local_id": 10}]}'

    def embed(self, text: str) -> list[float]:
        """Return a random unit vector of fixed dimension."""
        # Generate random vector
        vec = [random.gauss(0, 1) for _ in range(self.embed_dim)]
        # Normalize to unit vector
        magnitude = math.sqrt(sum(x * x for x in vec))
        return [x / magnitude for x in vec]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Return random unit vectors for each text."""
        return [self.embed(t) for t in texts]


class StubCoTLLM:
    """Test double for CoTLLM that returns hardcoded responses."""

    def __init__(self):
        self._call_count = 0

    def think_and_complete(self, system: str, prompt: str, max_tokens: int = 4096, response_format: str | None = None) -> str:
        """Return hardcoded valid JSON matching expected Q1/Q4/Planner/Grader output shapes."""
        self._call_count += 1

        # Detect what kind of response is expected based on system/prompt content.
        # Check Planner/Grader/Generator first (system-based) before Q1 (prompt-based).
        sys_lower = system.lower()
        prompt_lower = prompt.lower()
        if "queries" in sys_lower or "语义检索" in system or "搜索查询" in system:
            # Planner: search_queries JSON
            return '{"queries": ["用户问题", "关系演变", "情感变化"]}'
        if "直接回答" in system or "查询助手" in system:
            # Factual generator: direct answer JSON
            return '{"answer": "根据聊天记录，相关事实如下。", "evidence_msg_ids": [1, 2, 3]}'
        if ("evaluation" in sys_lower or "信息充足性" in system) and "phases" not in sys_lower:
            # Grader: evaluation JSON (exclude Generator which has "phases")
            return '{"evaluation": "sufficient"}'
        if "phases" in sys_lower or "叙事阶段" in system or "叙事分析" in system:
            # Generator (agent): evidence_segments; Q4 (one-shot): evidence_msg_ids
            if "evidence_segments" in sys_lower or "对话片段" in system:
                return '''{
                    "phases": [
                        {
                            "phase_title": "热恋期",
                            "time_range": "2023-03",
                            "core_conclusion": "双方互动频繁，情感投入高",
                            "evidence_segments": [[1, 3]],
                            "reasoning_chain": "从消息频率和回复速度来看，这段时间双方关系密切",
                            "uncertainty_note": "样本较少，结论仅供参考"
                        }
                    ]
                }'''
            return '''{
                "phases": [
                    {
                        "phase_title": "热恋期",
                        "time_range": "2023-03",
                        "core_conclusion": "双方互动频繁，情感投入高",
                        "evidence_msg_ids": [1, 2, 3],
                        "reasoning_chain": "从消息频率和回复速度来看，这段时间双方关系密切",
                        "uncertainty_note": "样本较少，结论仅供参考"
                    }
                ]
            }'''
        if "query_type" in prompt_lower or "意图" in prompt_lower:
            # Q1 intent parsing response
            return '''{
                "query_type": "arc_narrative",
                "focus_dimensions": ["reply_delay", "conflict_intensity", "silence_event"],
                "time_range": null
            }'''
        elif "relevant" in sys_lower or "证据相关性" in system:
            # Reflection relevance check
            return '{"relevant": true}'
        elif "selected_ids" in sys_lower or "证据选择" in system:
            # Reflection re-selection
            return '{"selected_ids": [1, 2, 3]}'
        elif "linked" in prompt.lower() or "semantic" in prompt.lower():
            # Layer 2 Stage 2 arbitration response
            return '{"linked": true, "reason": "两个节点描述同一主题的演进过程"}'
        else:
            # Default response
            return '{"result": "ok"}'


class StubReranker:
    """Test double for Reranker that returns fixed scores."""

    def __init__(self, score: float = 0.8):
        """Initialize with a fixed score to return for all pairs.

        Args:
            score: The fixed score to return (default 0.8).
        """
        self._score = score

    def rerank(self, pairs: list[tuple[str, str]]) -> list[float]:
        """Return a fixed score for each pair.

        Args:
            pairs: List of (query_text, passage_text) tuples.

        Returns:
            List of fixed scores (0.8) for each pair.
        """
        return [self._score] * len(pairs)


class OpenAICompatibleNonCoTLLM:
    """NonCoTLLM implementation using OpenAI-compatible API."""

    def __init__(self, llm_cfg: "LLMConfig", embed_cfg: "EmbeddingConfig"):
        self.llm_client = OpenAI(
            api_key=llm_cfg.api_key,
            base_url=_normalize_chat_base_url(llm_cfg.base_url),
        )
        self.llm_model = llm_cfg.model
        self.max_workers: int = getattr(llm_cfg, "max_workers", 8)

        self.embed_client = OpenAI(
            api_key=embed_cfg.api_key,
            base_url=embed_cfg.base_url,
        )
        self.embed_model = embed_cfg.model

    def complete(self, system: str, prompt: str, max_tokens: int = 1024, response_format: str | None = None) -> str:
        """Generate a completion, retrying on rate-limit errors with exponential backoff."""
        from openai import RateLimitError
        request_params: dict = {
            "model": self.llm_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
        }
        if response_format == "json_object":
            request_params["response_format"] = {"type": "json_object"}

        for attempt in range(4):  # up to 3 retries
            try:
                response = self.llm_client.chat.completions.create(**request_params)
                content = response.choices[0].message.content or ""
                if response_format == "json_object":
                    content = _strip_json_fences(content)
                return content
            except RateLimitError:
                if attempt == 3:
                    raise
                time.sleep(5 * (2 ** attempt))  # 5s, 10s, 20s

        return ""  # unreachable

    def embed(self, text: str) -> list[float]:
        """Generate an embedding using the embeddings API."""
        response = self.embed_client.embeddings.create(
            model=self.embed_model,
            input=text,
        )
        return list(response.data[0].embedding)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts in a single API call."""
        response = self.embed_client.embeddings.create(
            model=self.embed_model,
            input=texts,
        )
        sorted_data = sorted(response.data, key=lambda x: x.index)
        return [list(item.embedding) for item in sorted_data]


class OpenAICompatibleCoTLLM:
    """CoTLLM implementation using OpenAI-compatible API with chain-of-thought."""

    COT_PREAMBLE = """请逐步思考后再回答。在给出最终答案之前，请先分析问题并展示你的推理过程。

输出格式要求：
- 如果需要输出JSON，请确保格式正确
- 可以在JSON之前或之后添加分析说明
- 最终答案必须是有效的JSON格式"""

    def __init__(self, llm_cfg: "LLMConfig"):
        self.client = OpenAI(
            api_key=llm_cfg.api_key,
            base_url=_normalize_chat_base_url(llm_cfg.base_url),
        )
        self.model = llm_cfg.model
        self.max_workers: int = getattr(llm_cfg, "max_workers", 8)

    def think_and_complete(self, system: str, prompt: str, max_tokens: int = 4096, response_format: str | None = None) -> str:
        """Generate a completion with chain-of-thought reasoning, retrying on rate-limit errors."""
        from openai import RateLimitError

        if response_format == "json_object":
            enhanced_system = f"请认真分析后，返回有效的JSON格式答案，不要输出任何非JSON内容。\n\n{system}"
        else:
            enhanced_system = f"{self.COT_PREAMBLE}\n\n{system}"

        request_params = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": enhanced_system},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
        }
        if response_format == "json_object":
            request_params["response_format"] = {"type": "json_object"}

        for attempt in range(4):
            try:
                response = self.client.chat.completions.create(**request_params)
                content = response.choices[0].message.content or ""
                if response_format == "json_object":
                    content = _strip_json_fences(content)
                return content
            except RateLimitError:
                if attempt == 3:
                    raise
                time.sleep(5 * (2 ** attempt))

        return ""  # unreachable


class OpenAICompatibleReranker:
    """Reranker implementation using HTTP API directly (not OpenAI SDK)."""

    def __init__(self, reranker_cfg: "RerankerConfig"):
        """Initialize with reranker configuration.

        Args:
            reranker_cfg: Configuration for the reranker endpoint.
        """
        self.model = reranker_cfg.model
        self.api_key = reranker_cfg.api_key
        self.base_url = reranker_cfg.base_url.rstrip("/")
        self._client = httpx.Client(timeout=30.0)

    def rerank(self, pairs: list[tuple[str, str]]) -> list[float]:
        """Score each (query, passage) pair via HTTP POST.

        Groups pairs by query to minimise HTTP requests, then executes
        per-query requests in parallel (I/O bound).

        Args:
            pairs: List of (query_text, passage_text) tuples.

        Returns:
            List of relevance scores (0.0 to 1.0) in the same order as input.
        """
        if not pairs:
            return []

        from collections import defaultdict
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # Group pairs by query for batching
        query_to_indices: dict[str, list[int]] = defaultdict(list)
        for i, (query, _) in enumerate(pairs):
            query_to_indices[query].append(i)

        scores = [0.0] * len(pairs)

        def fetch_group(query: str, idx_list: list[int]) -> list[tuple[int, float]]:
            documents = [pairs[i][1] for i in idx_list]
            for attempt in range(4):
                try:
                    response = self._client.post(
                        f"{self.base_url}/rerank",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                        json={"model": self.model, "query": query, "documents": documents},
                    )
                    if response.status_code == 429:
                        if attempt == 3:
                            response.raise_for_status()
                        time.sleep(5 * (2 ** attempt))
                        continue
                    response.raise_for_status()
                    break
                except httpx.HTTPStatusError:
                    if attempt == 3:
                        raise
                    time.sleep(5 * (2 ** attempt))
            data = response.json()
            results = []
            for result in data.get("results", []):
                doc_idx = result.get("index", 0)
                score = result.get("relevance_score", 0.0)
                if doc_idx < len(idx_list):
                    results.append((idx_list[doc_idx], score))
            return results

        max_workers = min(8, len(query_to_indices))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(fetch_group, query, idxs): query
                for query, idxs in query_to_indices.items()
            }
            for future in as_completed(futures):
                for orig_idx, score in future.result():
                    scores[orig_idx] = score

        return scores

    def __del__(self):
        """Clean up the HTTP client."""
        if hasattr(self, "_client"):
            self._client.close()


def from_config(config: "Config") -> tuple[NonCoTLLM, CoTLLM, Reranker]:
    """Create LLM instances from a Config object.

    Args:
        config: The configuration object.

    Returns:
        Tuple of (NonCoTLLM, CoTLLM, Reranker) instances.
    """
    noncot = OpenAICompatibleNonCoTLLM(config.llm, config.embedding)
    cot = OpenAICompatibleCoTLLM(config.llm)
    reranker = OpenAICompatibleReranker(config.reranker)
    return (noncot, cot, reranker)
