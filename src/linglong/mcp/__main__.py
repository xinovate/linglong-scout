"""Entry point for python -m linglong.mcp."""

import logging

from linglong.config import get_config, setup_logging
from linglong.mcp.server import create_http_app, create_server

setup_logging()
logger = logging.getLogger(__name__)


def main() -> None:
    """Run the MCP server."""
    config = get_config()
    transport = config.mcp.transport

    if transport == "stdio":
        server = create_server()
        logger.info("Starting MCP server (stdio)")
        server.run(transport="stdio")
    else:
        logger.info(
            "Starting MCP server (%s) on %s:%d",
            transport,
            config.mcp.host,
            config.mcp.port,
        )
        _run_http(config)


def _run_http(config) -> None:
    """Run HTTP server with mandatory auth and background scheduler."""
    import anyio

    if not config.mcp.auth_token:
        logger.error(
            "auth_token is required for HTTP mode. "
            "Run 'linglong-scout init' to generate one, "
            "or set LL_MCP_AUTH_TOKEN in .env"
        )
        raise SystemExit(1)

    async def _serve():
        import asyncio

        import uvicorn

        app = create_http_app()

        from linglong.mcp._auth import TokenAuthMiddleware

        app.add_middleware(
            TokenAuthMiddleware,
            expected_token=config.mcp.auth_token,
            redis_url=config.mcp.redis_url or "",
        )
        if config.mcp.redis_url:
            logger.info("Token auth enabled (Redis + static fallback)")
        else:
            logger.info("Token auth enabled (static only)")

        if config.ingest.collect_schedule:
            from linglong.scout.scheduler import collect_scheduler

            asyncio.create_task(collect_scheduler())

        uv_config = uvicorn.Config(
            app,
            host=config.mcp.host,
            port=config.mcp.port,
            log_level="info",
        )
        await uvicorn.Server(uv_config).serve()

    anyio.run(_serve)


if __name__ == "__main__":
    main()
