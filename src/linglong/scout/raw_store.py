"""Structured raw data storage — hot (Redis) + cold (JSON file)."""

import json
import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import redis

from linglong.config import get_config

logger = logging.getLogger(__name__)

_RAW_PREFIX = "scout:raw:"
_RAW_TTL_DAYS = 14
_SOURCES = ("searxng", "rss", "github")


def _get_redis() -> redis.Redis:
    """Get Redis client from config."""
    config = get_config()
    url = config.mcp.redis_url
    if not url:
        raise RuntimeError("redis_url not configured in .scout.yml (mcp.redis_url)")
    return redis.from_url(url, decode_responses=True)


def _raw_dir() -> Path:
    """Get raw data directory from config, expanding ~."""
    config = get_config()
    return Path(config.ingest.raw_data_dir).expanduser()


def _now_iso() -> str:
    """Current UTC time as ISO string."""
    return datetime.now(UTC).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Normalize — convert source-specific items to unified schema
# ---------------------------------------------------------------------------


def _normalize_searxng(items: list[dict[str, str]], fetched_at: str) -> list[dict[str, Any]]:
    """Convert SearXNG items to normalized schema."""
    return [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": r.get("snippet", ""),
            "source": "searxng",
            "published": "",
            "fetched_at": fetched_at,
            "extra": {
                "query": r.get("query", ""),
            },
        }
        for r in items
    ]


def _normalize_github(items: list[dict[str, str]], fetched_at: str) -> list[dict[str, Any]]:
    """Convert GitHub items to normalized schema."""
    return [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": r.get("snippet", ""),
            "source": "github",
            "published": "",
            "fetched_at": fetched_at,
            "extra": {
                "stars": r.get("stars", ""),
                "growth": r.get("growth", ""),
                "period": r.get("period", ""),
            },
        }
        for r in items
    ]


def _normalize_rss(items: list[dict[str, str]], fetched_at: str) -> list[dict[str, Any]]:
    """Convert RSS items to normalized schema."""
    return [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": r.get("snippet", ""),
            "source": "rss",
            "published": "",
            "fetched_at": fetched_at,
            "extra": {
                "feed_name": r.get("source", ""),
            },
        }
        for r in items
    ]


# ---------------------------------------------------------------------------
# Store — write to Redis (hot) + JSON file (cold)
# ---------------------------------------------------------------------------


def store_raw(
    target_date: str | None = None,
    searxng: list[dict[str, str]] | None = None,
    github: list[dict[str, str]] | None = None,
    rss: list[dict[str, str]] | None = None,
    github_source: str = "",
) -> dict[str, int]:
    """Store raw data for all sources to Redis + JSON files.

    Returns {"searxng": N, "github": N, "rss": N} item counts.
    """
    d = target_date or date.today().isoformat()
    fetched_at = _now_iso()
    config = get_config()
    ttl = config.ingest.raw_redis_ttl_days * 86400

    counts: dict[str, int] = {}
    data_map: dict[str, list[dict[str, Any]]] = {}

    if searxng is not None:
        normalized = _normalize_searxng(searxng, fetched_at)
        data_map["searxng"] = normalized
        counts["searxng"] = len(normalized)

    if github is not None:
        normalized = _normalize_github(github, fetched_at)
        data_map["github"] = normalized
        counts["github"] = len(normalized)

    if rss is not None:
        normalized = _normalize_rss(rss, fetched_at)
        data_map["rss"] = normalized
        counts["rss"] = len(normalized)

    # Write Redis (hot)
    try:
        r = _get_redis()
        for source, data in data_map.items():
            key = f"{_RAW_PREFIX}{d}:{source}"
            r.setex(key, ttl, json.dumps(data, ensure_ascii=False))
    except Exception as e:
        logger.warning("Redis raw store failed: %s", e)

    # Write JSON files (cold)
    try:
        raw_dir = _raw_dir()
        raw_dir.mkdir(parents=True, exist_ok=True)
        for source, data in data_map.items():
            path = raw_dir / f"{d}_{source}.json"
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("File raw store failed: %s", e)

    # Write meta
    meta = {
        "fetched_at": fetched_at,
        "searxng_count": counts.get("searxng", 0),
        "rss_count": counts.get("rss", 0),
        "github_count": counts.get("github", 0),
        "github_source": github_source,
    }
    _store_meta(d, meta, ttl)

    logger.info(
        "Raw data stored for %s: %d searxng, %d github, %d rss",
        d, counts.get("searxng", 0), counts.get("github", 0), counts.get("rss", 0),
    )
    return counts


def _store_meta(date_key: str, meta: dict[str, Any], ttl: int) -> None:
    """Store meta hash to Redis + JSON file."""
    # Redis hash
    try:
        r = _get_redis()
        key = f"{_RAW_PREFIX}{date_key}:meta"
        str_meta = {k: str(v) for k, v in meta.items()}
        r.hset(key, mapping=str_meta)
        r.expire(key, ttl)
    except Exception as e:
        logger.warning("Redis meta store failed: %s", e)

    # File
    try:
        raw_dir = _raw_dir()
        raw_dir.mkdir(parents=True, exist_ok=True)
        path = raw_dir / f"{date_key}_meta.json"
        path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("File meta store failed: %s", e)


# ---------------------------------------------------------------------------
# Read — Redis first, fallback to file
# ---------------------------------------------------------------------------


def get_raw(
    target_date: str | None = None,
    source: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Read raw data for a date. Reads Redis first, falls back to file.

    Returns {"searxng": [...], "rss": [...], "github": [...]}.
    Missing sources have empty lists.
    """
    d = target_date or date.today().isoformat()
    sources = (source,) if source else _SOURCES
    result: dict[str, list[dict[str, Any]]] = {}

    for src in sources:
        data = _read_from_redis(d, src) or _read_from_file(d, src)
        result[src] = data or []

    return result


def _read_from_redis(date_key: str, source: str) -> list[dict[str, Any]] | None:
    """Read one source from Redis. Returns None if not found."""
    try:
        r = _get_redis()
        data = r.get(f"{_RAW_PREFIX}{date_key}:{source}")
        if data:
            return json.loads(data)
    except Exception as e:
        logger.warning("Redis raw read failed for %s/%s: %s", date_key, source, e)
    return None


def _read_from_file(date_key: str, source: str) -> list[dict[str, Any]] | None:
    """Read one source from JSON file. Returns None if not found."""
    path = _raw_dir() / f"{date_key}_{source}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("File raw read failed for %s: %s", path, e)
    return None


def has_raw(target_date: str | None = None) -> bool:
    """Check if raw data exists for a given date (in Redis or on disk)."""
    d = target_date or date.today().isoformat()
    for src in _SOURCES:
        try:
            r = _get_redis()
            if r.exists(f"{_RAW_PREFIX}{d}:{src}"):
                return True
        except Exception:
            pass
        if (_raw_dir() / f"{d}_{src}.json").exists():
            return True
    return False


def get_raw_meta(target_date: str | None = None) -> dict[str, Any]:
    """Read meta for a date. Returns {} if not found."""
    d = target_date or date.today().isoformat()

    # Try Redis hash first
    try:
        r = _get_redis()
        data = r.hgetall(f"{_RAW_PREFIX}{d}:meta")
        if data:
            return data
    except Exception as e:
        logger.warning("Redis meta read failed: %s", e)

    # Fallback to file
    path = _raw_dir() / f"{d}_meta.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("File meta read failed: %s", e)

    return {}


def cleanup_raw() -> int:
    """Remove raw data keys older than retention window. Returns count removed."""
    config = get_config()
    ttl_days = config.ingest.raw_redis_ttl_days
    try:
        r = _get_redis()
        cutoff = (date.today() - timedelta(days=ttl_days)).isoformat()
        removed = 0
        cursor = 0
        while True:
            cursor, keys = r.scan(cursor, match=f"{_RAW_PREFIX}*")
            for key in keys:
                # Extract date from key like scout:raw:2026-05-28:searxng
                parts = key.replace(_RAW_PREFIX, "").split(":")
                if parts and parts[0] < cutoff:
                    r.delete(key)
                    removed += 1
            if cursor == 0:
                break
        if removed:
            logger.info("Cleaned up %d old raw data keys", removed)
        return removed
    except Exception as e:
        logger.warning("Redis raw cleanup failed: %s", e)
        return 0
