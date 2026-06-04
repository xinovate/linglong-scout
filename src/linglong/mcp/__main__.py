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
        from linglong.mcp.token import generate_token

        config.mcp.auth_token = generate_token("auto")
        logger.warning(
            "No auth_token configured. Auto-generated: %s",
            config.mcp.auth_token,
        )
        logger.warning(
            "Set LL_MCP_AUTH_TOKEN in .env or run 'linglong-scout init' to persist.",
        )

    # Store token in Redis so the auth middleware can validate it
    if config.mcp.redis_url:
        try:
            import redis as redis_lib

            r = redis_lib.from_url(config.mcp.redis_url, decode_responses=True)
            r.set(config.mcp.auth_token, "active")
            r.close()
            logger.info("Auth token registered in Redis")
        except Exception:
            logger.warning("Failed to store token in Redis, will use static fallback")

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
