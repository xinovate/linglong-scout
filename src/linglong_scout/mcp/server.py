"""MCP Server for Linglong Scout."""

import logging

from starlette.applications import Starlette

from mcp.server.fastmcp import FastMCP

from linglong_scout.config import get_config
from linglong_scout.mcp.tools import (
    execute_package,
    fetch_rss,
    generate_brief,
    record_feedback,
    search_web,
)

logger = logging.getLogger(__name__)

_INGEST_TOOLS = [fetch_rss, generate_brief, execute_package, search_web, record_feedback]


def create_server() -> FastMCP:
    """Create a FastMCP server (stdio mode)."""
    config = get_config()
    server = FastMCP(
        "linglong-scout",
        host=config.mcp.host,
        port=config.mcp.port,
    )
    for tool in _INGEST_TOOLS:
        server.tool()(tool)
    logger.info("Registered %d scout tools (stdio mode)", len(_INGEST_TOOLS))
    return server


def create_http_app() -> Starlette:
    """Create a Starlette app with MCP route for scout tools."""
    config = get_config()

    allowed_hosts = []
    if config.mcp.allowed_hosts:
        allowed_hosts = config.mcp.allowed_hosts

    from mcp.server.fastmcp.server import TransportSecuritySettings

    server = FastMCP(
        "linglong-scout",
        streamable_http_path="/mcp/scout",
        transport_security=TransportSecuritySettings(
            allowed_hosts=allowed_hosts,
        ),
    )
    for tool in _INGEST_TOOLS:
        server.tool()(tool)
    logger.info("Registered %d scout tools at /mcp/scout", len(_INGEST_TOOLS))

    return server.streamable_http_app()
