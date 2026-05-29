"""Tests for collect scheduler."""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from linglong.scout.scheduler import _seconds_until, _run_collect, collect_scheduler


class TestSecondsUntil:
    def test_returns_positive_for_future_time(self):
        now = datetime.now()
        future = (now + timedelta(hours=2)).strftime("%H:%M")
        result = _seconds_until(future)
        assert 7000 < result < 7300

    def test_wraps_to_next_day_for_past_time(self):
        now = datetime.now()
        past = (now - timedelta(hours=2)).strftime("%H:%M")
        result = _seconds_until(past)
        assert result > 78000

    def test_exactly_now_returns_one_day(self):
        now = datetime.now().replace(second=1)
        target = now.strftime("%H:%M")
        result = _seconds_until(target)
        assert result > 86000


class TestRunCollect:
    async def test_collects_and_stores(self):
        config = MagicMock()
        config.ingest.packages = [{"name": "test", "topic": "AI"}]

        mock_raw = {
            "searxng": [{"title": "t", "url": "u", "snippet": "s", "source": "searxng", "fetched_at": "t", "extra": {}}],
            "github": [],
            "github_source": "opengithubs",
            "rss": [],
        }

        with patch("linglong.scout.scheduler.get_config", return_value=config), \
             patch("linglong.scout.collect.collect", return_value=mock_raw) as mock_collect, \
             patch("linglong.scout.raw_store.store_raw", return_value={"searxng": 1, "github": 0, "rss": 0}) as mock_store:
            await _run_collect()
            mock_collect.assert_called_once()
            mock_store.assert_called_once()

    async def test_skips_when_no_packages(self):
        config = MagicMock()
        config.ingest.packages = []

        with patch("linglong.scout.scheduler.get_config", return_value=config):
            await _run_collect()

    async def test_continues_on_collect_failure(self):
        config = MagicMock()
        config.ingest.packages = [{"name": "test", "topic": "AI"}]

        with patch("linglong.scout.scheduler.get_config", return_value=config), \
             patch("linglong.scout.collect.collect", side_effect=RuntimeError("network error")):
            await _run_collect()


class TestCollectScheduler:
    async def test_disabled_when_empty(self):
        config = MagicMock()
        config.ingest.collect_schedule = ""

        with patch("linglong.scout.scheduler.get_config", return_value=config):
            await collect_scheduler()

    async def test_disabled_when_none(self):
        config = MagicMock()
        config.ingest.collect_schedule = None

        with patch("linglong.scout.scheduler.get_config", return_value=config):
            await collect_scheduler()

    async def test_runs_one_cycle(self):
        config = MagicMock()
        config.ingest.collect_schedule = "06:55"
        config.ingest.packages = [{"name": "test", "topic": "AI"}]

        call_count = 0

        async def fake_sleep(seconds):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()

        with patch("linglong.scout.scheduler.get_config", return_value=config), \
             patch("linglong.scout.scheduler._seconds_until", return_value=1.0), \
             patch("linglong.scout.scheduler._run_collect", new_callable=AsyncMock) as mock_run, \
             patch("asyncio.sleep", side_effect=fake_sleep):
            task = asyncio.create_task(collect_scheduler())
            try:
                await asyncio.wait_for(task, timeout=0.5)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            assert mock_run.call_count >= 1
