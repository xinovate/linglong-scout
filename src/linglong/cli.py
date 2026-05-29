"""Linglong Scout CLI."""

import argparse
import logging
import sys

logger = logging.getLogger(__name__)


def cmd_brief(args):
    """Generate morning brief and cache to Redis."""
    import asyncio
    import json
    from datetime import date

    from linglong.config import get_config
    from linglong.scout.agent import IngestAgent
    from linglong.scout.brief_history import BriefHistory
    from linglong.scout.cache import get_brief, set_brief
    from linglong.scout.feedback import FeedbackStore
    from linglong.scout.package import SourcePackage

    config = get_config()
    if not config.ingest.packages:
        print("No packages configured in .scout.yml", file=sys.stderr)
        sys.exit(1)

    today = date.today().isoformat()

    # Check cache
    cached = get_brief(today)
    if cached and not args.force:
        print(f" Brief for {today} already cached ({len(cached)} chars). Use --force to regenerate.")
        print(cached)
        return

    # Generate
    package = SourcePackage(**config.ingest.packages[0])
    feedback_store = FeedbackStore()
    brief_history = BriefHistory(dedup_windows=config.ingest.dedup_windows)
    agent = IngestAgent(feedback_store=feedback_store, brief_history=brief_history)

    from linglong.scout.raw_store import get_raw, get_raw_meta, has_raw

    print(f"Generating brief for {today}...", file=sys.stderr)

    if has_raw(today):
        raw_data = get_raw(today)
        meta = get_raw_meta(today)
        raw = {
            "searxng": raw_data.get("searxng", []),
            "github": raw_data.get("github", []),
            "github_source": meta.get("github_source", ""),
            "rss": raw_data.get("rss", []),
        }
        output = agent.run_from_raw(package, raw)
    else:
        output = asyncio.run(agent.run(package))

    if output:
        set_brief(output, today)
        print(output)
    else:
        print("Brief generation returned empty output", file=sys.stderr)
        sys.exit(1)


def cmd_ingest(args):
    """Run scout packages."""
    import asyncio
    from pathlib import Path

    from linglong.config import get_config
    from linglong.scout.agent import IngestAgent
    from linglong.scout.brief_history import BriefHistory
    from linglong.scout.feedback import FeedbackStore
    from linglong.scout.package import SourcePackage

    config = get_config()
    if not config.ingest.packages:
        print("No packages configured in .scout.yml")
        sys.exit(1)

    package = SourcePackage(**config.ingest.packages[0])
    feedback_store = FeedbackStore()
    brief_history = BriefHistory(dedup_windows=config.ingest.dedup_windows)
    agent = IngestAgent(feedback_store=feedback_store, brief_history=brief_history)
    output = asyncio.run(agent.run(package))
    if output:
        print(output)


def cmd_collect(args):
    """Collect raw data without generating brief."""
    import asyncio
    import json
    from datetime import date

    from linglong.config import get_config
    from linglong.scout.package import SourcePackage
    from linglong.scout.raw_store import store_raw

    config = get_config()
    if not config.ingest.packages:
        print("No packages configured in .scout.yml", file=sys.stderr)
        sys.exit(1)

    package = SourcePackage(**config.ingest.packages[0])
    from linglong.scout.collect import collect as collect_data
    raw = asyncio.run(collect_data(package))

    today = date.today().isoformat()
    counts = store_raw(
        target_date=today,
        searxng=raw["searxng"],
        github=raw["github"],
        rss=raw["rss"],
        github_source=raw["github_source"],
    )

    total = sum(counts.values())
    print(f"Collected {total} items for {today}: {json.dumps(counts)}")


def cmd_serve(args):
    """Run MCP server."""
    from linglong.mcp import main as mcp_main
    mcp_main()


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="linglong-scout",
        description="Linglong Scout — information collection agent",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    sub = parser.add_subparsers(dest="command")

    p_brief = sub.add_parser("brief", help="Generate morning brief (for cron)")
    p_brief.add_argument("--force", action="store_true", help="Regenerate even if cached")
    p_brief.set_defaults(func=cmd_brief)

    p_ingest = sub.add_parser("scout", help="Run scout packages")
    p_ingest.set_defaults(func=cmd_ingest)

    p_collect = sub.add_parser("collect", help="Collect raw data only (no LLM)")
    p_collect.set_defaults(func=cmd_collect)

    p_serve = sub.add_parser("serve", help="Run MCP server")
    p_serve.set_defaults(func=cmd_serve)

    args = parser.parse_args()

    from linglong.config import setup_logging
    setup_logging("DEBUG" if args.verbose else None)

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
