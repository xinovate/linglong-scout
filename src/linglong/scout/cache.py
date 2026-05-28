"""Redis-backed cache for briefs and dedup history."""

import json
import logging
from datetime import date, timedelta

import redis

from linglong.config import get_config

logger = logging.getLogger(__name__)

_BRIEF_PREFIX = "scout:brief:"
_HISTORY_PREFIX = "scout:history:"
_BRIEF_TTL = 25 * 3600  # 25 hours
_HISTORY_RETAIN_DAYS = 16


def _get_redis() -> redis.Redis:
    """Get Redis client from config."""
    config = get_config()
    url = config.mcp.redis_url
    if not url:
        raise RuntimeError("redis_url not configured in .scout.yml (mcp.redis_url)")
    return redis.from_url(url, decode_responses=True)


def get_brief(target_date: str | None = None) -> str | None:
    """Get cached brief for a date. Returns markdown or None."""
    d = target_date or date.today().isoformat()
    try:
        r = _get_redis()
        data = r.get(f"{_BRIEF_PREFIX}{d}")
        if data:
            logger.info("Brief cache hit for %s", d)
        return data
    except Exception as e:
        logger.warning("Redis brief get failed: %s", e)
        return None


def set_brief(content: str, target_date: str | None = None) -> None:
    """Cache brief for a date with TTL."""
    d = target_date or date.today().isoformat()
    try:
        r = _get_redis()
        r.setex(f"{_BRIEF_PREFIX}{d}", _BRIEF_TTL, content)
        logger.info("Brief cached for %s (%d chars)", d, len(content))
    except Exception as e:
        logger.warning("Redis brief set failed: %s", e)


def load_history(
    dedup_windows: dict[str, int], target_date: date | None = None,
) -> dict[str, str]:
    """Load recent history per dimension from Redis.

    Returns {dimension: combined_text_with_dates}.
    """
    today = target_date or date.today()
    try:
        r = _get_redis()
    except Exception as e:
        logger.warning("Redis unavailable for history load: %s", e)
        return {}

    result: dict[str, str] = {}
    for dim, window in dedup_windows.items():
        sections: list[str] = []
        for i in range(1, window + 1):
            d = today - timedelta(days=i)
            key = f"{_HISTORY_PREFIX}{d.isoformat()}"
            try:
                data = r.hget(key, dim)
                if data:
                    sections.append(f"【{d.isoformat()}】\n{data}")
            except Exception as e:
                logger.warning("Failed to read history %s/%s: %s", key, dim, e)
        if sections:
            result[dim] = "\n\n".join(sections)

    return result


def save_history(
    date_str: str, sections: dict[str, str], dedup_windows: dict[str, int],
) -> None:
    """Save per-dimension sections for a date as Redis hash."""
    try:
        r = _get_redis()
        key = f"{_HISTORY_PREFIX}{date_str}"
        if sections:
            r.hset(key, mapping=sections)
            r.expire(key, _HISTORY_RETAIN_DAYS * 86400)
        logger.info("History saved: %s (%d dimensions)", date_str, len(sections))
    except Exception as e:
        logger.warning("Redis history save failed: %s", e)


def cleanup_history() -> int:
    """Remove history keys older than retention window. Returns count removed."""
    try:
        r = _get_redis()
        cutoff = (date.today() - timedelta(days=_HISTORY_RETAIN_DAYS)).isoformat()
        removed = 0
        cursor = 0
        while True:
            cursor, keys = r.scan(cursor, match=f"{_HISTORY_PREFIX}*")
            for key in keys:
                date_part = key.replace(_HISTORY_PREFIX, "")
                if date_part < cutoff:
                    r.delete(key)
                    removed += 1
            if cursor == 0:
                break
        if removed:
            logger.info("Cleaned up %d old history keys", removed)
        return removed
    except Exception as e:
        logger.warning("Redis history cleanup failed: %s", e)
        return 0


def get_last_history() -> str | None:
    """Return most recent history content for fallback."""
    try:
        r = _get_redis()
        keys: list[str] = []
        cursor = 0
        while True:
            cursor, batch = r.scan(cursor, match=f"{_HISTORY_PREFIX}*")
            keys.extend(batch)
            if cursor == 0:
                break
        if not keys:
            return None
        keys.sort(reverse=True)
        data = r.hgetall(keys[0])
        if not data:
            return None
        return "\n\n".join(f"## {k}\n{v}" for k, v in data.items() if v)
    except Exception:
        return None
