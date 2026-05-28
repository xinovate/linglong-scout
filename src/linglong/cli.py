"""Linglong Scout CLI."""

import argparse
import logging
import sys


logger = logging.getLogger(__name__)


def cmd_ingest(args):
    """Run scout packages."""
    from linglong.scout.agent import IngestAgent
    from linglong.scout.brief_history import BriefHistory
    from linglong.scout.feedback import FeedbackStore
    from linglong.scout.package import SourcePackage
    from linglong.config import get_config
    from pathlib import Path

    config = get_config()
    if not config.ingest.packages:
        print("No packages configured in .scout.yml")
        sys.exit(1)

    import asyncio
    package = SourcePackage(**config.ingest.packages[0])
    feedback_store = FeedbackStore()
    history_dir = Path(config.ingest.brief_history_dir).expanduser()
    brief_history = BriefHistory(history_dir, config.ingest.dedup_windows)
    agent = IngestAgent(feedback_store=feedback_store, brief_history=brief_history)
    output = asyncio.run(agent.run(package))
    if output:
        print(output)


def cmd_serve(args):
    """Run MCP server."""
    from linglong.mcp import main as mcp_main
    mcp_main()


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(prog="linglong-scout", description="Linglong Scout — information collection agent")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    sub = parser.add_subparsers(dest="command")

    p_ingest = sub.add_parser("scout", help="Run scout packages")
    p_ingest.set_defaults(func=cmd_ingest)

    p_serve = sub.add_parser("serve", help="Run MCP server")
    p_serve.set_defaults(func=cmd_serve)

    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
