"""Configuration management for Narrative Mirror."""

from dataclasses import dataclass
from pathlib import Path

import yaml


class ConfigError(Exception):
    """Exception raised for configuration errors."""
    pass


@dataclass
class LLMConfig:
    """Configuration for the LLM (chat) endpoint."""

    provider: str = "openai"
    model: str = "claude-3-5-sonnet-20241022"
    api_key: str = ""
    base_url: str = "https://api.anthropic.com/v1"
    max_workers: int = 8


@dataclass
class EmbeddingConfig:
    """Configuration for the embedding endpoint."""

    provider: str = "openai"
    model: str = "BAAI/bge-m3"
    api_key: str = ""
    base_url: str = ""


@dataclass
class RerankerConfig:
    """Configuration for the reranker endpoint."""

    model: str = "BAAI/bge-reranker-v2-m3"
    api_key: str = ""
    base_url: str = ""


@dataclass
class Config:
    """Top-level configuration."""

    llm: LLMConfig
    embedding: EmbeddingConfig
    reranker: RerankerConfig


def load_config(path: str = "config.yml") -> Config:
    """Load configuration from a YAML file.

    Args:
        path: Path to the config file.

    Returns:
        A Config object.

    Raises:
        FileNotFoundError: If the config file doesn't exist.
    """
    config_path = Path(path)

    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(config_path, "r") as f:
        data = yaml.safe_load(f)

    llm_data = data.get("llm", {})
    embedding_data = data.get("embedding", {})
    reranker_data = data.get("reranker")

    if reranker_data is None:
        raise ConfigError("Missing 'reranker' block in config.yml")

    return Config(
        llm=LLMConfig(
            provider=llm_data.get("provider", "openai"),
            model=llm_data.get("model", "claude-3-5-sonnet-20241022"),
            api_key=llm_data.get("api_key", ""),
            base_url=llm_data.get("base_url", "https://api.anthropic.com/v1"),
            max_workers=int(llm_data.get("max_workers", 8)),
        ),
        embedding=EmbeddingConfig(
            provider=embedding_data.get("provider", "openai"),
            model=embedding_data.get("model", "BAAI/bge-m3"),
            api_key=embedding_data.get("api_key", ""),
            base_url=embedding_data.get("base_url", ""),
        ),
        reranker=RerankerConfig(
            model=reranker_data.get("model", "BAAI/bge-reranker-v2-m3"),
            api_key=reranker_data.get("api_key", ""),
            base_url=reranker_data.get("base_url", ""),
        ),
    )
