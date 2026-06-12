"""MCP Server for Linglong Scout."""

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from mcp.server.fastmcp import FastMCP

from linglong.config import get_config
from linglong.mcp.tools import (
    execute_package,
    fetch_github_trending,
    fetch_raw,
    fetch_rss,
    generate_brief,
    init_stores,
    record_feedback,
)

logger = logging.getLogger(__name__)

_INGEST_TOOLS = [fetch_raw, fetch_rss, fetch_github_trending, generate_brief, execute_package, record_feedback]


class HealthMiddleware(BaseHTTPMiddleware):
    """Return health status without touching the MCP handler."""

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path == "/health":
            return JSONResponse({"status": "ok"})
        return await call_next(request)


def create_server() -> FastMCP:
    """Create a FastMCP server (stdio mode)."""
    config = get_config()
    server = FastMCP(
        "linglong-scout",
        host=config.mcp.host,
        port=config.mcp.port,
    )
    init_stores()
    for tool in _INGEST_TOOLS:
        server.tool()(tool)
    logger.info("Registered %d scout tools (stdio mode)", len(_INGEST_TOOLS))
    return server


def create_http_app():
    """Create an ASGI app with /health and MCP route for scout tools."""
    config = get_config()

    from mcp.server.fastmcp.server import TransportSecuritySettings

    # Empty allowed_hosts means "no restriction" — pass None to disable
    # DNS rebinding protection rather than rejecting all requests.
    security = None
    if config.mcp.allowed_hosts:
        security = TransportSecuritySettings(
            allowed_hosts=config.mcp.allowed_hosts,
        )

    server = FastMCP(
        "linglong-scout",
        streamable_http_path="/mcp/scout",
        transport_security=security,
    )
    init_stores()
    for tool in _INGEST_TOOLS:
        server.tool()(tool)
    logger.info("Registered %d scout tools at /mcp/scout", len(_INGEST_TOOLS))

    app = server.streamable_http_app()
    # HealthMiddleware is innermost — runs after auth, before MCP handler.
    # This avoids wrapping the MCP app (which breaks its lifespan/task-group).
    app.add_middleware(HealthMiddleware)
    return app
