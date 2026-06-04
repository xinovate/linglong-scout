"""MCP Server for Linglong Scout."""

import logging

from starlette.applications import Starlette

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


def create_http_app() -> Starlette:
    """Create a Starlette app with MCP route for scout tools."""
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

    return server.streamable_http_app()
