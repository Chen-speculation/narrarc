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


def apply_overrides(config: Config, overrides: dict) -> Config:
    """Apply partial overrides to a Config. Overrides are merged shallowly per section.

    Args:
        config: Base configuration.
        overrides: Dict with optional keys llm, embedding, reranker. Each value
            is a dict of field names to override (e.g. {"api_key": "x", "model": "y"}).

    Returns:
        A new Config with overrides applied.
    """
    llm_data = {
        "provider": config.llm.provider,
        "model": config.llm.model,
        "api_key": config.llm.api_key,
        "base_url": config.llm.base_url,
        "max_workers": config.llm.max_workers,
    }
    if overrides.get("llm"):
        llm_data.update({k: v for k, v in overrides["llm"].items() if v is not None})

    embedding_data = {
        "provider": config.embedding.provider,
        "model": config.embedding.model,
        "api_key": config.embedding.api_key,
        "base_url": config.embedding.base_url,
    }
    if overrides.get("embedding"):
        embedding_data.update({k: v for k, v in overrides["embedding"].items() if v is not None})

    reranker_data = {
        "model": config.reranker.model,
        "api_key": config.reranker.api_key,
        "base_url": config.reranker.base_url,
    }
    if overrides.get("reranker"):
        reranker_data.update({k: v for k, v in overrides["reranker"].items() if v is not None})

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


def config_to_dict(config: Config) -> dict:
    """Convert Config to a dict suitable for JSON (e.g. for frontend display)."""
    return {
        "llm": {
            "provider": config.llm.provider,
            "model": config.llm.model,
            "api_key": config.llm.api_key,
            "base_url": config.llm.base_url,
            "max_workers": config.llm.max_workers,
        },
        "embedding": {
            "provider": config.embedding.provider,
            "model": config.embedding.model,
            "api_key": config.embedding.api_key,
            "base_url": config.embedding.base_url,
        },
        "reranker": {
            "model": config.reranker.model,
            "api_key": config.reranker.api_key,
            "base_url": config.reranker.base_url,
        },
    }


def load_config(path: str = "config.yml") -> Config:
    """Load configuration from a YAML file.

    Accepts both config.yml and config.yaml: if the given path does not exist,
    the other extension is tried in the same directory.

    Args:
        path: Path to the config file (e.g. config.yml or config.yaml).

    Returns:
        A Config object.

    Raises:
        FileNotFoundError: If neither the config file nor the alternate exists.
    """
    config_path = Path(path)
    if not config_path.exists():
        # Try the other common extension in the same directory
        alt = config_path.with_suffix(".yaml" if config_path.suffix == ".yml" else ".yml")
        if alt.exists():
            config_path = alt
        else:
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
