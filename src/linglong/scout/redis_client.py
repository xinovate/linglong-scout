"""Shared Redis client factory."""

import redis

from linglong.config import get_config


def get_redis() -> redis.Redis:
    """Get Redis client from config."""
    config = get_config()
    url = config.mcp.redis_url
    if not url:
        raise RuntimeError("redis_url not configured in .scout.yml (mcp.redis_url)")
    return redis.from_url(url, decode_responses=True)
