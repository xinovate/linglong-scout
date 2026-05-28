"""Token authentication middleware for MCP HTTP server."""

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


class TokenAuthMiddleware(BaseHTTPMiddleware):
    """Validate Bearer token against Redis store.

    Token format: linglong-{module}-{random}
    Redis key: same as token value, with value 'active'.
    If Redis is not configured, falls back to static token comparison.
    """

    def __init__(self, app, expected_token: str = "", redis_url: str = ""):
        super().__init__(app)
        self._static_token = expected_token
        self._redis_url = redis_url
        self._redis = None

    def _get_redis(self):
        if self._redis is not None:
            return self._redis
        if not self._redis_url:
            return None
        try:
            import redis as redis_lib

            self._redis = redis_lib.from_url(self._redis_url, decode_responses=True)
            return self._redis
        except Exception:
            logger.warning("Failed to connect to Redis, falling back to static token")
            return None

    def _validate_token(self, token: str) -> bool:
        # Try Redis first
        r = self._get_redis()
        if r is not None:
            try:
                return r.exists(token) == 1
            except Exception:
                logger.warning("Redis query failed, falling back to static token")

        # Fallback to static token
        if self._static_token:
            return token == self._static_token
        return False

    async def dispatch(self, request: Request, call_next):
        # Skip non-MCP paths
        if not request.url.path.startswith("/mcp/"):
            return await call_next(request)

        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})

        token = auth[7:]
        if not self._validate_token(token):
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        return await call_next(request)
