"""Domain exceptions for Linglong Scout."""


class ScoutError(RuntimeError):
    """Base exception for Scout operations."""


class LLMError(ScoutError):
    """LLM API call failure."""


class SourceError(ScoutError):
    """External data source failure (SearXNG, RSS, GitHub)."""
