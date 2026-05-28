"""Configuration management for Linglong Scout."""

import logging
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_YAML_SEARCH_PATHS = [
    Path(".linglong-scout.yaml"),
    _PROJECT_ROOT / ".linglong-scout.yaml",
    Path.home() / ".linglong-scout" / "config.yaml",
]


class LLMConfig(BaseSettings):
    """LLM configuration for Scout."""

    model_config = SettingsConfigDict(env_prefix="LL_SCOUT_LLM_")

    llm_api_key: str | None = Field(default=None, description="LLM API key")
    llm_base_url: str | None = Field(
        default="https://open.bigmodel.cn/api/anthropic",
        description="LLM base URL",
    )
    llm_model: str = Field(default="glm-5.1", description="LLM model name")
    llm_temperature: float = Field(default=0.3, description="LLM temperature")
    llm_max_tokens: int = Field(default=8000, description="LLM max output tokens")


class IngestConfig(BaseSettings):
    """Ingest module configuration."""

    model_config = SettingsConfigDict(env_prefix="LL_INGEST_")

    rss_sources: list[dict[str, str]] = Field(
        default_factory=list, description="RSS source configurations"
    )
    packages: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Inline package definitions",
    )
    searxng_url: str = Field(
        default="http://redacted-server-ip:8088",
        description="SearXNG instance URL for JSON API search",
    )
    search_timeout: float = Field(
        default=30.0, description="Search request timeout in seconds"
    )
    searxng_api_key: str | None = Field(
        default=None, description="SearXNG API key (Bearer Token via nginx auth)"
    )
    rsshub_access_key: str | None = Field(
        default=None, description="RSSHub ACCESS_KEY for authenticated requests"
    )

    llm_max_tokens: int = Field(
        default=8000, description="LLM max output tokens for brief generation"
    )
    llm_retries: int = Field(
        default=2, description="LLM call retry count on failure"
    )
    llm_timeout: int = Field(
        default=120, description="LLM request timeout in seconds"
    )

    github_trending_limits: dict[str, int] = Field(
        default_factory=lambda: {"daily": 5, "weekly": 3, "monthly": 3},
        description="GitHub trending repo counts per period",
    )
    github_search_fallback: dict[str, int] = Field(
        default_factory=lambda: {"since_days": 30, "min_stars": 500},
        description="GitHub Search API fallback parameters",
    )

    brief_history_dir: str = Field(
        default="~/linglong/brief_history",
        description="Directory for brief history JSON files (dedup)",
    )
    company_snapshot_path: str = Field(
        default="~/linglong/company_snapshot.json",
        description="Company funding/valuation snapshot for brief generation",
    )
    dedup_windows: dict[str, int] = Field(
        default_factory=lambda: {"关键人物": 14, "公司动态": 7, "政策动态": 14, "应用落地": 7},
        description="Per-dimension lookback days for dedup",
    )

    brief_output_dir: str = Field(
        default="~/linglong/briefs",
        description="Directory for cached daily briefs",
    )
    brief_schedule_time: str = Field(
        default="07:30",
        description="Daily brief schedule time (HH:MM), used for time range markers",
    )
    brief_cache_days: int = Field(
        default=14,
        description="Days to keep cached briefs",
    )


class MCPConfig(BaseModel):
    """MCP server configuration."""

    transport: str = Field(
        default="stdio",
        description="Transport protocol: stdio | sse | streamable-http",
    )
    host: str = Field(
        default="127.0.0.1",
        description="HTTP listen host (streamable-http / sse mode)",
    )
    port: int = Field(
        default=9900,
        description="HTTP listen port (streamable-http / sse mode)",
    )
    auth_token: str | None = Field(
        default=None,
        description="Bearer token for authentication (None = no auth)",
    )
    allowed_hosts: list[str] = Field(
        default_factory=list,
        description="Allowed Host header values for DNS rebinding protection (HTTP mode)",
    )
    redis_url: str = Field(
        default="",
        description="Redis URL for dynamic token auth (e.g. redis://:password@127.0.0.1:6379/0)",
    )


class ScoutConfig(BaseSettings):
    """Main Linglong Scout configuration."""

    model_config = SettingsConfigDict(
        env_prefix="LL_SCOUT_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    debug: bool = Field(default=False, description="Debug mode")
    log_level: str = Field(default="INFO", description="Logging level")
    data_dir: Path = Field(
        default=Path.home() / "linglong" / "data", description="Data directory"
    )

    llm: LLMConfig = Field(default_factory=LLMConfig)
    ingest: IngestConfig = Field(default_factory=IngestConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)

    def ensure_directories(self) -> None:
        """Ensure all required directories exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)


_config: ScoutConfig | None = None


def _find_yaml_config() -> Path | None:
    """Search for .linglong-scout.yaml config file, return first found path."""
    for p in _YAML_SEARCH_PATHS:
        if p.exists():
            return p
    return None


def _interpolate_env(data: Any) -> Any:
    """Recursively interpolate ${ENV_VAR} references in config values."""
    if isinstance(data, str):
        if data.startswith("${") and data.endswith("}"):
            env_var = data[2:-1]
            value = os.environ.get(env_var, "")
            if not value:
                logger.warning("Environment variable %s not set", env_var)
            return value
        return data
    if isinstance(data, dict):
        return {k: _interpolate_env(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_interpolate_env(v) for v in data]
    return data


def _load_yaml_to_config(yaml_path: Path) -> ScoutConfig:
    """Construct ScoutConfig from a YAML file."""
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    data = _interpolate_env(data)
    return ScoutConfig(**data)


def get_config() -> ScoutConfig:
    """Get or create global configuration."""
    global _config
    if _config is None:
        yaml_path = _find_yaml_config()
        if yaml_path:
            logger.info("Loading config from: %s", yaml_path)
            _config = _load_yaml_to_config(yaml_path)
        else:
            _config = ScoutConfig()
        _config.ensure_directories()
    return _config


def set_config(config: ScoutConfig) -> None:
    """Set global configuration (useful for testing)."""
    global _config
    _config = config
