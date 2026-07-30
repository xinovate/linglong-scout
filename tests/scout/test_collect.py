"""Tests for collect.py concurrent collection and orchestration."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from linglong.scout.collect import (
    _parse_trending_html,
    collect as collect_data,
    fetch_single_feed,
)

_FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def _mock_config():
    config = MagicMock()
    config.ingest.rsshub_url = None
    config.ingest.rsshub_access_key = None
    config.ingest.rss_sources = []
    config.ingest.github_trending_limits = {"daily": 5, "weekly": 3, "monthly": 3}
    config.ingest.github_search_fallback = {"since_days": 30, "min_stars": 500}
    return config


class TestConcurrentCollect:
    @pytest.mark.asyncio
    async def test_two_sources_run_concurrently(self):
        """Verify github and rss are called in collect()."""
        config = _mock_config()

        with patch("linglong.scout.collect.get_config", return_value=config), \
             patch("linglong.scout.collect._github_trending", new_callable=AsyncMock, return_value=([
                 {"title": "GH1", "url": "https://github.com/r1", "snippet": "g1",
                  "stars": "100", "growth": "50", "period": "日增长"},
             ], "opengithubs")) as mock_gh, \
             patch("linglong.scout.collect._fetch_rss_feeds", new_callable=AsyncMock, return_value=[
                 {"title": "RSS1", "url": "https://c.com/3", "snippet": "r1", "source": "Feed"},
             ]) as mock_rss:
            result = await collect_data()

        mock_gh.assert_called_once()
        mock_rss.assert_called_once()
        assert "searxng" not in result
        assert len(result["github"]) == 1
        assert result["github_source"] == "opengithubs"
        assert len(result["rss"]) == 1

    @pytest.mark.asyncio
    async def test_source_health_records_all_sources(self):
        """SourceHealth tracks success/failure for all sources."""
        from linglong.scout.collect import source_health

        prev_stats = source_health._stats.copy()
        source_health._stats.clear()

        config = _mock_config()

        try:
            with patch("linglong.scout.collect.get_config", return_value=config), \
                 patch("linglong.scout.collect._github_trending", new_callable=AsyncMock, return_value=([], "opengithubs")), \
                 patch("linglong.scout.collect._fetch_rss_feeds", new_callable=AsyncMock, return_value=[]):
                await collect_data()

            stats = source_health._stats
            assert "GitHub" in stats
            assert "RSS" in stats
            assert stats["GitHub"]["success"] == 1
        finally:
            source_health._stats = prev_stats

    @pytest.mark.asyncio
    async def test_collect_continues_on_github_failure(self):
        """Collect should return partial results if GitHub fails."""
        config = _mock_config()

        with patch("linglong.scout.collect.get_config", return_value=config), \
             patch("linglong.scout.collect._github_trending", new_callable=AsyncMock, side_effect=Exception("GitHub down")), \
             patch("linglong.scout.collect._fetch_rss_feeds", new_callable=AsyncMock, return_value=[
                 {"title": "RSS1", "url": "https://c.com/3", "snippet": "r1", "source": "Feed"},
             ]):
            result = await collect_data()

        assert result["github"] == []
        assert result["github_source"] == "unavailable"
        assert len(result["rss"]) == 1

    @pytest.mark.asyncio
    async def test_collect_continues_on_all_failures(self):
        """Collect returns empty structure when all sources fail."""
        config = _mock_config()

        with patch("linglong.scout.collect.get_config", return_value=config), \
             patch("linglong.scout.collect._github_trending", new_callable=AsyncMock, side_effect=Exception("fail")), \
             patch("linglong.scout.collect._fetch_rss_feeds", new_callable=AsyncMock, side_effect=Exception("fail")):
            result = await collect_data()

        assert result["github"] == []
        assert result["rss"] == []


def test_parses_wangchujiang_total_and_daily_stars():
    html = (_FIXTURES_DIR / "wangchujiang_trending.html").read_text(encoding="utf-8")

    repos = _parse_trending_html(html, max_results=2)

    assert [repo["stars"] for repo in repos] == ["18.813k", "2345"]
    assert [repo["growth"] for repo in repos] == ["341", "180"]


class TestFetchSingleFeed:
    @pytest.mark.asyncio
    async def test_fetches_and_parses_feed(self):
        rss_xml = """<?xml version="1.0"?>
        <rss version="2.0">
          <channel>
            <title>Test</title>
            <item>
              <title>Article 1</title>
              <link>https://example.com/1</link>
              <pubDate>Mon, 20 Jul 2026 08:30:00 +0000</pubDate>
              <description>Summary 1</description>
            </item>
          </channel>
        </rss>"""

        mock_resp = MagicMock()
        mock_resp.text = rss_xml
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("linglong.scout.collect.httpx.AsyncClient", return_value=mock_client), \
             patch("linglong.scout.collect.get_config", return_value=_mock_config()):
            items = await fetch_single_feed("https://example.com/feed", name="TestFeed")

        assert len(items) == 1
        assert items[0]["source"] == "TestFeed"
        assert items[0]["published"] == "2026-07-20"

    @pytest.mark.asyncio
    async def test_returns_empty_on_network_error(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("Connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("linglong.scout.collect.httpx.AsyncClient", return_value=mock_client), \
             patch("linglong.scout.collect.get_config", return_value=_mock_config()):
            items = await fetch_single_feed("https://example.com/feed")

        assert items == []

    @pytest.mark.asyncio
    async def test_respects_max_items(self):
        items_xml = "\n".join(
            f'<item><title>T{i}</title><link>https://x.com/{i}</link><description>D</description></item>'
            for i in range(10)
        )
        rss_xml = f'<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>{items_xml}</channel></rss>'

        mock_resp = MagicMock()
        mock_resp.text = rss_xml
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("linglong.scout.collect.httpx.AsyncClient", return_value=mock_client), \
             patch("linglong.scout.collect.get_config", return_value=_mock_config()):
            items = await fetch_single_feed("https://example.com/feed", max_items=3)

        assert len(items) == 3

    @pytest.mark.asyncio
    async def test_rejects_internal_url(self):
        with pytest.raises(ValueError, match="internal network"):
            await fetch_single_feed("http://localhost:8080/feed")
