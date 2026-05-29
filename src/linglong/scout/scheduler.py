"""Background scheduler for daily raw data collection.

Runs inside the MCP server process as an asyncio task. Wakes up at the
configured time (default 06:55), collects data from all sources, and
stores to Redis + file. No external cron needed.
"""

import asyncio
import logging
from datetime import date, datetime, timedelta

from linglong.config import get_config
from linglong.scout.package import SourcePackage

logger = logging.getLogger(__name__)

_shutdown = asyncio.Event()


def stop_scheduler() -> None:
    """Signal the scheduler to stop after current operation completes."""
    _shutdown.set()
    logger.info("Scheduler shutdown requested")


def _seconds_until(time_str: str) -> float:
    """Seconds from now until the next occurrence of HH:MM (local time)."""
    now = datetime.now()
    parts = time_str.split(":")
    target_h, target_m = int(parts[0]), int(parts[1])
    target = now.replace(hour=target_h, minute=target_m, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def _interruptible_sleep(seconds: float) -> None:
    """Sleep that can be interrupted by shutdown signal. Checks every 60s."""
    remaining = seconds
    while remaining > 0 and not _shutdown.is_set():
        chunk = min(remaining, 60)
        try:
            await asyncio.wait_for(_shutdown.wait(), timeout=chunk)
            return  # shutdown was set
        except asyncio.TimeoutError:
            remaining -= chunk


async def _run_collect() -> None:
    """Execute one collection cycle."""
    from linglong.scout.collect import collect as collect_data
    from linglong.scout.raw_store import store_raw

    config = get_config()
    if not config.ingest.packages:
        logger.warning("No packages configured, skipping scheduled collection")
        return

    package = SourcePackage(**config.ingest.packages[0])
    today = date.today().isoformat()

    try:
        raw = await collect_data(package)
        counts = store_raw(
            target_date=today,
            searxng=raw["searxng"],
            github=raw["github"],
            rss=raw["rss"],
            github_source=raw["github_source"],
        )
        total = sum(counts.values())
        logger.info("Scheduled collection done: %d items for %s (%s)", total, today, counts)
    except Exception:
        logger.exception("Scheduled collection failed for %s", today)


async def collect_scheduler() -> None:
    """Background loop: sleep until scheduled time, collect, repeat."""
    config = get_config()
    schedule_time = config.ingest.collect_schedule
    if not schedule_time or not schedule_time.strip():
        logger.info("Auto-collect disabled (collect_schedule is empty)")
        return

    logger.info("Auto-collect scheduler started, next run at %s", schedule_time)

    while not _shutdown.is_set():
        delay = _seconds_until(schedule_time)
        logger.info("Next collection in %.0f seconds", delay)
        await _interruptible_sleep(delay)
        if _shutdown.is_set():
            logger.info("Scheduler stopping before collection")
            break
        await _run_collect()

    logger.info("Scheduler stopped")
