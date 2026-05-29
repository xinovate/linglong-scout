"""Tests for collect.py concurrent collection, cross-dedup, and orchestration."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from linglong.scout.collect import (
    _searxng_search,
    collect as collect_data,
    fetch_single_feed,
)
from linglong.scout.package import SearchQueryConfig, SourcePackage


def _make_package() -> SourcePackage:
    return SourcePackage(
        name="test",
        topic="AI",
        search_queries=[
            SearchQueryConfig(keywords=["test query"], max_results=5),
        ],
    )


def _mock_config():
    config = MagicMock()
    config.ingest.searxng_url = "http://localhost:8088"
    config.ingest.search_timeout = 10.0
    config.ingest.searxng_api_key = None
    config.ingest.rsshub_access_key = None
    config.ingest.rss_sources = []
    config.ingest.github_trending_limits = {"daily": 5, "weekly": 3, "monthly": 3}
    config.ingest.github_search_fallback = {"since_days": 30, "min_stars": 500}
    return config


class TestConcurrentCollect:
    @pytest.mark.asyncio
    async def test_three_sources_run_concurrently(self):
        """Verify all three sources (searxng, github, rss) are called in collect()."""
        pkg = _make_package()
        config = _mock_config()

        with patch("linglong.scout.collect.get_config", return_value=config), \
             patch("linglong.scout.collect._searxng_search", new_callable=AsyncMock, return_value=[
                 {"title": "T1", "url": "https://a.com/1", "snippet": "s1"},
                 {"title": "T2", "url": "https://b.com/2", "snippet": "s2"},
             ]) as mock_sx, \
             patch("linglong.scout.collect._github_trending", new_callable=AsyncMock, return_value=([
                 {"title": "GH1", "url": "https://github.com/r1", "snippet": "g1",
                  "stars": "100", "growth": "50", "period": "日增长"},
             ], "opengithubs")) as mock_gh, \
             patch("linglong.scout.collect._fetch_rss_feeds", new_callable=AsyncMock, return_value=[
                 {"title": "RSS1", "url": "https://c.com/3", "snippet": "r1", "source": "Feed"},
             ]) as mock_rss:
            result = await collect_data(pkg)

        mock_sx.assert_called_once()
        mock_gh.assert_called_once()
        mock_rss.assert_called_once()
        assert len(result["searxng"]) == 2
        assert len(result["github"]) == 1
        assert result["github_source"] == "opengithubs"
        assert len(result["rss"]) == 1

    @pytest.mark.asyncio
    async def test_cross_dedup_removes_searxng_urls_from_rss(self):
        """RSS items with URLs already in SearXNG results should be filtered."""
        pkg = _make_package()
        config = _mock_config()

        with patch("linglong.scout.collect.get_config", return_value=config), \
             patch("linglong.scout.collect._searxng_search", new_callable=AsyncMock, return_value=[
                 {"title": "T", "url": "https://shared.com/article", "snippet": "s"},
             ]), \
             patch("linglong.scout.collect._github_trending", new_callable=AsyncMock, return_value=([], "")), \
             patch("linglong.scout.collect._fetch_rss_feeds", new_callable=AsyncMock, return_value=[
                 {"title": "RSS Dup", "url": "https://shared.com/article", "snippet": "r", "source": "Feed"},
                 {"title": "RSS Unique", "url": "https://unique.com/article", "snippet": "r2", "source": "Feed"},
             ]):
            result = await collect_data(pkg)

        assert len(result["rss"]) == 1
        assert result["rss"][0]["title"] == "RSS Unique"

    @pytest.mark.asyncio
    async def test_source_health_records_all_sources(self):
        """SourceHealth tracks success/failure for all three sources."""
        from linglong.scout.collect import source_health

        prev_stats = source_health._stats.copy()
        source_health._stats.clear()

        pkg = _make_package()
        config = _mock_config()

        try:
            with patch("linglong.scout.collect.get_config", return_value=config), \
                 patch("linglong.scout.collect._searxng_search", new_callable=AsyncMock, return_value=[
                     {"title": "T", "url": "https://a.com", "snippet": "s"},
                 ]), \
                 patch("linglong.scout.collect._github_trending", new_callable=AsyncMock, return_value=([], "opengithubs")), \
                 patch("linglong.scout.collect._fetch_rss_feeds", new_callable=AsyncMock, return_value=[]):
                await collect_data(pkg)

            stats = source_health._stats
            assert "SearXNG" in stats
            assert "GitHub" in stats
            assert "RSS" in stats
            assert stats["SearXNG"]["success"] == 1
            assert stats["GitHub"]["success"] == 1
        finally:
            source_health._stats = prev_stats

    @pytest.mark.asyncio
    async def test_collect_continues_on_searxng_failure(self):
        """Collect should return partial results if SearXNG fails."""
        pkg = _make_package()
        config = _mock_config()

        with patch("linglong.scout.collect.get_config", return_value=config), \
             patch("linglong.scout.collect._searxng_search", new_callable=AsyncMock, side_effect=Exception("SearXNG down")), \
             patch("linglong.scout.collect._github_trending", new_callable=AsyncMock, return_value=([], "")), \
             patch("linglong.scout.collect._fetch_rss_feeds", new_callable=AsyncMock, return_value=[]):
            result = await collect_data(pkg)

        assert result["searxng"] == []
        assert "github" in result

    @pytest.mark.asyncio
    async def test_collect_continues_on_all_failures(self):
        """Collect returns empty structure when all sources fail."""
        pkg = _make_package()
        config = _mock_config()

        with patch("linglong.scout.collect.get_config", return_value=config), \
             patch("linglong.scout.collect._searxng_search", new_callable=AsyncMock, side_effect=Exception("fail")), \
             patch("linglong.scout.collect._github_trending", new_callable=AsyncMock, side_effect=Exception("fail")), \
             patch("linglong.scout.collect._fetch_rss_feeds", new_callable=AsyncMock, side_effect=Exception("fail")):
            result = await collect_data(pkg)

        assert result["searxng"] == []
        assert result["github"] == []
        assert result["rss"] == []


class TestSearchAllKeywords:
    @pytest.mark.asyncio
    async def test_searches_multiple_keywords(self):
        """All keywords in all query groups should be searched."""
        pkg = SourcePackage(
            name="test",
            topic="AI",
            search_queries=[
                SearchQueryConfig(keywords=["k1", "k2"], max_results=5),
                SearchQueryConfig(keywords=["k3"], max_results=3),
            ],
        )

        with patch("linglong.scout.collect._searxng_search", new_callable=AsyncMock, return_value=[]) as mock_search:
            from linglong.scout.collect import _search_all_keywords
            await _search_all_keywords(pkg)

        assert mock_search.call_count == 3

    @pytest.mark.asyncio
    async def test_continues_on_keyword_failure(self):
        """Failed keyword searches should not prevent others from succeeding."""
        pkg = SourcePackage(
            name="test",
            topic="AI",
            search_queries=[
                SearchQueryConfig(keywords=["good", "bad"], max_results=5),
            ],
        )

        call_count = 0

        async def mock_search(query, max_results=15):
            nonlocal call_count
            call_count += 1
            if query == "bad":
                raise Exception("Search failed")
            return [{"title": query, "url": f"https://{query}.com", "snippet": "s"}]

        with patch("linglong.scout.collect._searxng_search", side_effect=mock_search):
            from linglong.scout.collect import _search_all_keywords
            results = await _search_all_keywords(pkg)

        assert len(results) == 1
        assert results[0]["title"] == "good"


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


class TestSearxngNoiseFilter:
    @pytest.mark.asyncio
    async def test_noise_urls_filtered(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "results": [
                {"title": "Dict Entry", "url": "https://www.iciba.com/word?w=test", "content": "c"},
                {"title": "Real News", "url": "https://www.36kr.com/p/123", "content": "d"},
            ],
        }
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        config = _mock_config()
        with patch("linglong.scout.collect.httpx.AsyncClient", return_value=mock_client), \
             patch("linglong.scout.collect.get_config", return_value=config):
            results = await _searxng_search("test")

        assert len(results) == 1
        assert results[0]["title"] == "Real News"

    @pytest.mark.asyncio
    async def test_empty_query_skipped(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": []}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        config = _mock_config()
        with patch("linglong.scout.collect.httpx.AsyncClient", return_value=mock_client), \
             patch("linglong.scout.collect.get_config", return_value=config):
            results = await _searxng_search("test")

        assert results == []
