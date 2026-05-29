"""Tests for IngestAgent."""

import json
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from linglong.scout.agent import (
    IngestAgent,
    _call_llm,
    _format_company_snapshot,
    _format_github,
    _format_results,
    _format_rss,
)
from linglong.scout.collect import (
    SourceHealth,
    _dedup_results,
    _fetch_rss_feeds,
    _github_trending,
    _is_noise_url,
    _parse_opengithub_table,
    _searxng_search,
    _validate_feed_url,
    collect as collect_data,
)
from linglong.scout.package import SearchQueryConfig, SourcePackage


def _make_package() -> SourcePackage:
    return SourcePackage(
        name="test-brief",
        topic="AI 早报",
        output={"format": "morning-brief"},
        search_queries=[
            SearchQueryConfig(
                keywords=["OpenAI news 2026", "Anthropic Claude latest"],
                max_results=5,
                max_age_days=3,
            ),
        ],
    )


class TestNoiseFilter:
    def test_dictionary_is_noise(self):
        assert _is_noise_url("https://www.iciba.com/word?w=open")

    def test_baidu_baike_is_noise(self):
        assert _is_noise_url("https://baike.baidu.com/item/test")

    def test_news_site_is_not_noise(self):
        assert not _is_noise_url("https://www.36kr.com/p/123456")

    def test_tech_blog_is_not_noise(self):
        assert not _is_noise_url("https://openai.com/blog/something")


class TestDedup:
    def test_removes_duplicate_urls(self):
        results = [
            {"title": "A", "url": "https://a.com/1", "snippet": ""},
            {"title": "B", "url": "https://b.com/1", "snippet": ""},
            {"title": "A2", "url": "https://a.com/1", "snippet": "dup"},
        ]
        deduped = _dedup_results(results)
        assert len(deduped) == 2

    def test_empty_list(self):
        assert _dedup_results([]) == []


class TestFormatResults:
    def test_formats_with_numbering(self):
        results = [
            {"title": "Test News", "url": "https://example.com/1", "snippet": "A test"},
        ]
        text = _format_results(results)
        assert "1. Test News" in text
        assert "https://example.com/1" in text
        assert "A test" in text

    def test_truncates_long_snippet(self):
        results = [
            {"title": "T", "url": "https://x.com", "snippet": "x" * 300},
        ]
        text = _format_results(results)
        assert len(text.split("摘要: ")[1].split("\n")[0]) <= 200


class TestIngestAgent:
    @pytest.mark.asyncio
    async def test_run_produces_output(self):
        pkg = _make_package()
        agent = IngestAgent()

        mock_raw = {
            "searxng": [{"title": "OpenAI release", "url": "https://openai.com/blog/x", "snippet": "GPT-5"}],
            "github": [],
            "github_source": "trending",
            "rss": [],
        }

        with patch("linglong.scout.agent.collect_data", new_callable=AsyncMock, return_value=mock_raw), \
             patch("linglong.scout.agent._call_llm", new_callable=AsyncMock, return_value="# AI 早报 · 2026-05-25\n\nMorning brief content"), \
             patch("linglong.scout.raw_store.store_raw") as mock_store:
            mock_store.return_value = {"searxng": 1}
            output = await agent.run(pkg)

        assert "AI 早报" in output

    @pytest.mark.asyncio
    async def test_run_with_no_results(self):
        pkg = _make_package()
        agent = IngestAgent()

        mock_raw = {"searxng": [], "github": [], "github_source": "trending", "rss": []}

        with patch("linglong.scout.agent.collect_data", new_callable=AsyncMock, return_value=mock_raw), \
             patch("linglong.scout.raw_store.store_raw") as mock_store:
            mock_store.return_value = {}
            output = await agent.run(pkg)

        assert "暂无搜索结果" in output

    @pytest.mark.asyncio
    async def test_preference_injection(self):
        from linglong.scout.feedback import FeedbackStore

        pkg = _make_package()
        store = MagicMock(spec=FeedbackStore)
        store.get_preference_text.return_value = "用户偏好：funding 类型偏好"

        agent = IngestAgent(feedback_store=store)

        mock_raw = {
            "searxng": [{"title": "T", "url": "https://t.com", "snippet": "s"}],
            "github": [],
            "github_source": "trending",
            "rss": [],
        }

        with patch("linglong.scout.agent.collect_data", new_callable=AsyncMock, return_value=mock_raw), \
             patch("linglong.scout.agent._call_llm", new_callable=AsyncMock, return_value="# AI 早报") as mock_llm, \
             patch("linglong.scout.raw_store.store_raw") as mock_store:
            mock_store.return_value = {"searxng": 1}
            await agent.run(pkg)

        call_args = mock_llm.call_args
        system_prompt = call_args[0][0] if call_args[0] else call_args[1].get("system", "")
        assert "偏好" in system_prompt

    @pytest.mark.asyncio
    async def test_collect_returns_raw_dict(self):
        pkg = _make_package()

        with patch("linglong.scout.collect._searxng_search", new_callable=AsyncMock, return_value=[
            {"title": "T", "url": "https://t.com", "snippet": "s"},
        ]), \
             patch("linglong.scout.collect._github_trending", new_callable=AsyncMock, return_value=([], "opengithubs")), \
             patch("linglong.scout.collect._fetch_rss_feeds", new_callable=AsyncMock, return_value=[]):
            raw = await collect_data(pkg)

        assert "searxng" in raw
        assert "github" in raw
        assert "rss" in raw
        assert "github_source" in raw
        assert len(raw["searxng"]) == 1

    @pytest.mark.asyncio
    async def test_run_from_raw_skips_collection(self):
        pkg = _make_package()
        agent = IngestAgent()

        raw = {
            "searxng": [{"title": "T", "url": "https://t.com", "snippet": "s"}],
            "github": [],
            "github_source": "",
            "rss": [],
        }

        with patch("linglong.scout.agent._call_llm", new_callable=AsyncMock, return_value="# AI 早报"):
            output = await agent.run_from_raw(pkg, raw)

        assert "AI 早报" in output


class TestParseOpengithub:
    def test_parses_table_rows(self):
        md = """## 日榜排行

| 排名 | 项目名 | Star⭐ | 今日增长量 |
|------|--------|--------|------------|
| 1 | [foo/bar](https://github.com/foo/bar) | 21.7k | 🔺2637 |
| 2 | [baz/qux](https://github.com/baz/qux) | 13.5k | 🔺1819 |
"""
        seen: set[str] = set()
        repos = _parse_opengithub_table(md, "日增长", 5, seen)
        assert len(repos) == 2
        assert repos[0]["title"] == "foo/bar (+2637⭐ 日增长)"
        assert repos[0]["stars"] == "21700"
        assert repos[1]["growth"] == "1819"

    def test_dedup_across_periods(self):
        md = """| 1 | [foo/bar](https://github.com/foo/bar) | 21k | 🔺1000 |"""
        seen: set[str] = set()
        r1 = _parse_opengithub_table(md, "日增长", 5, seen)
        r2 = _parse_opengithub_table(md, "周增长", 5, seen)
        assert len(r1) == 1
        assert len(r2) == 0

    def test_limit(self):
        rows = "| 1 | [r{i}](https://github.com/r{i}) | 1k | 🔺100 |"
        md = "\n".join(rows.format(i=i) for i in range(10))
        repos = _parse_opengithub_table(md, "日增长", 3, set())
        assert len(repos) == 3


class TestFormatGithub:
    def test_groups_by_period(self):
        repos = [
            {"title": "a (+100⭐ 日增长)", "url": "https://github.com/a", "snippet": "sa", "stars": "100", "growth": "100", "period": "日增长"},
            {"title": "b (+500⭐ 周增长)", "url": "https://github.com/b", "snippet": "sb", "stars": "500", "growth": "500", "period": "周增长"},
        ]
        text = _format_github(repos, "opengithubs")
        assert "### 日增长" in text
        assert "### 周增长" in text
        assert "OpenGithubs" in text


class TestFormatRss:
    def test_empty_list(self):
        assert _format_rss([]) == ""

    def test_formats_items_with_source(self):
        items = [
            {"title": "AI News", "url": "https://example.com/1", "snippet": "Summary", "source": "AIHOT"},
        ]
        text = _format_rss(items)
        assert "[AIHOT] AI News" in text
        assert "https://example.com/1" in text
        assert "Summary" in text

    def test_truncates_long_snippet(self):
        items = [
            {"title": "T", "url": "https://x.com", "snippet": "x" * 400, "source": "S"},
        ]
        text = _format_rss(items)
        assert "摘要:" in text

    def test_omits_empty_snippet(self):
        items = [
            {"title": "T", "url": "https://x.com", "snippet": "", "source": "S"},
        ]
        text = _format_rss(items)
        assert "摘要" not in text


class TestFetchRssFeeds:
    @pytest.mark.asyncio
    async def test_fetches_and_parses_rss(self):
        rss_xml = """<?xml version="1.0"?>
        <rss version="2.0">
          <channel>
            <title>Test Feed</title>
            <item>
              <title>Test Article</title>
              <link>https://example.com/article1</link>
              <description>A test article about AI</description>
            </item>
          </channel>
        </rss>"""

        mock_response = MagicMock()
        mock_response.text = rss_xml
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        config_mock = MagicMock()
        config_mock.ingest.rss_sources = [
            {"name": "TestSource", "url": "https://example.com/feed"},
        ]

        with patch("linglong.scout.collect.httpx.AsyncClient", return_value=mock_client), \
             patch("linglong.scout.collect.get_config", return_value=config_mock):
            items = await _fetch_rss_feeds()

        assert len(items) == 1
        assert items[0]["title"] == "Test Article"
        assert items[0]["source"] == "TestSource"

    @pytest.mark.asyncio
    async def test_dedup_by_url(self):
        rss_xml = """<?xml version="1.0"?>
        <rss version="2.0">
          <channel>
            <title>Feed</title>
            <item>
              <title>Article A</title>
              <link>https://example.com/1</link>
              <description>Desc A</description>
            </item>
            <item>
              <title>Article B</title>
              <link>https://example.com/1</link>
              <description>Desc B</description>
            </item>
          </channel>
        </rss>"""

        mock_response = MagicMock()
        mock_response.text = rss_xml
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        config_mock = MagicMock()
        config_mock.ingest.rss_sources = [
            {"name": "S1", "url": "https://s1.com/feed"},
            {"name": "S2", "url": "https://s2.com/feed"},
        ]

        with patch("linglong.scout.collect.httpx.AsyncClient", return_value=mock_client), \
             patch("linglong.scout.collect.get_config", return_value=config_mock):
            items = await _fetch_rss_feeds()

        assert len(items) == 1
        assert items[0]["title"] == "Article A"

    @pytest.mark.asyncio
    async def test_continues_on_source_failure(self):
        good_xml = """<?xml version="1.0"?>
        <rss version="2.0">
          <channel>
            <title>Good</title>
            <item>
              <title>Good Article</title>
              <link>https://good.com/1</link>
              <description>OK</description>
            </item>
          </channel>
        </rss>"""

        good_response = MagicMock()
        good_response.text = good_xml
        good_response.raise_for_status = MagicMock()

        call_count = 0

        async def mock_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Connection failed")
            return good_response

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        config_mock = MagicMock()
        config_mock.ingest.rss_sources = [
            {"name": "Bad", "url": "https://bad.com/feed"},
            {"name": "Good", "url": "https://good.com/feed"},
        ]

        with patch("linglong.scout.collect.httpx.AsyncClient", return_value=mock_client), \
             patch("linglong.scout.collect.get_config", return_value=config_mock):
            items = await _fetch_rss_feeds()

        assert len(items) == 1
        assert items[0]["source"] == "Good"


class TestCompanySnapshot:
    def test_load_snapshot(self):
        from linglong.scout.cache import get_company_snapshot
        mock_redis_data = {
            "__updated__": "2026-05-25",
            "OpenAI": '{"latest_funding":"$100亿","valuation":"$3000亿","stock":null}',
        }
        with patch("linglong.scout.cache._get_redis") as mock_r:
            mock_redis = MagicMock()
            mock_redis.hgetall.return_value = mock_redis_data
            mock_r.return_value = mock_redis
            snapshot = get_company_snapshot()
        assert "companies" in snapshot
        assert "OpenAI" in snapshot["companies"]
        assert snapshot["updated"] == "2026-05-25"

    def test_format_snapshot(self):
        snapshot = {
            "updated": "2026-05-25",
            "companies": {
                "OpenAI": {
                    "latest_funding": "$100亿 E轮 (2026.03)",
                    "valuation": "$3000亿",
                    "stock": None,
                },
            },
        }
        text = _format_company_snapshot(snapshot)
        assert "OpenAI" in text
        assert "$100亿" in text
        assert "$3000亿" in text

    def test_format_empty_snapshot(self):
        assert _format_company_snapshot({}) == ""

    def test_format_missing_companies(self):
        assert _format_company_snapshot({"updated": "2026-05-25"}) == ""


class TestSourceHealth:
    def test_records_success(self):
        health = SourceHealth()
        health.record("test", True, 10)
        summary = health.summary()
        assert "100% success" in summary

    def test_consecutive_failures_warning(self, caplog):
        import logging

        health = SourceHealth(warn_threshold=2)
        with caplog.at_level(logging.WARNING):
            health.record("bad", False, 0)
            health.record("bad", False, 0)
        assert any("failed 2 times" in r.message for r in caplog.records)

    def test_summary_empty(self):
        health = SourceHealth()
        assert health.summary() == ""

    def test_mixed_success_rate(self):
        health = SourceHealth()
        health.record("src", True, 5)
        health.record("src", True, 3)
        health.record("src", False, 0)
        summary = health.summary()
        assert "67% success" in summary


class TestLlmRetry:
    @pytest.mark.asyncio
    async def test_llm_retries_on_failure(self):
        pkg = _make_package()
        agent = IngestAgent()
        mock_raw = {
            "searxng": [{"title": "T", "url": "https://t.com", "snippet": "s"}],
            "github": [],
            "github_source": "trending",
            "rss": [],
        }

        with patch("linglong.scout.agent.collect_data", new_callable=AsyncMock, return_value=mock_raw), \
             patch("linglong.scout.agent._call_llm", new_callable=AsyncMock, side_effect=Exception("API error")), \
             patch("linglong.scout.raw_store.store_raw") as mock_store:
            mock_store.return_value = {"searxng": 1}
            with pytest.raises(Exception, match="API error"):
                await agent.run(pkg)

    @pytest.mark.asyncio
    async def test_llm_fallback_to_history(self, tmp_path):
        from linglong.scout.brief_history import BriefHistory

        store: dict[str, dict[str, str]] = {}
        mock_client = MagicMock()

        def hset(key, mapping=None):
            if mapping:
                store.setdefault(key, {}).update(mapping)

        def hget(key, field):
            return store.get(key, {}).get(field)

        def hgetall(key):
            return store.get(key, {})

        def scan(cursor, match=None):
            return 0, [k for k in store if "history" in k]

        mock_client.hset.side_effect = hset
        mock_client.hget.side_effect = hget
        mock_client.hgetall.side_effect = hgetall
        mock_client.scan.side_effect = scan

        mock_raw = {
            "searxng": [{"title": "T", "url": "https://t.com", "snippet": "s"}],
            "github": [],
            "github_source": "trending",
            "rss": [],
        }

        with patch("linglong.scout.cache._get_redis", return_value=mock_client), \
             patch("linglong.scout.agent.collect_data", new_callable=AsyncMock, return_value=mock_raw), \
             patch("linglong.scout.agent._call_llm", new_callable=AsyncMock, side_effect=Exception("API error")), \
             patch("linglong.scout.raw_store.store_raw") as mock_store:
            mock_store.return_value = {"searxng": 1}
            history = BriefHistory()
            history.save("2026-05-24", {"关键人物": "Some content"})

            pkg = _make_package()
            agent = IngestAgent(brief_history=history)
            output = await agent.run(pkg)

        assert "LLM 生成失败" in output
        assert "Some content" in output


class TestBriefHistoryOverlap:
    def _make_history_with_store(self):
        store: dict[str, dict[str, str]] = {}
        mock_client = MagicMock()

        def hset(key, mapping=None):
            if mapping:
                store.setdefault(key, {}).update(mapping)

        def hget(key, field):
            return store.get(key, {}).get(field)

        def hgetall(key):
            return store.get(key, {})

        def scan(cursor, match=None):
            return 0, list(store.keys())

        mock_client.hset.side_effect = hset
        mock_client.hget.side_effect = hget
        mock_client.hgetall.side_effect = hgetall
        mock_client.scan.side_effect = scan
        return mock_client, store

    def test_detects_overlap(self, tmp_path):
        from linglong.scout.brief_history import BriefHistory

        mock_client, store = self._make_history_with_store()
        with patch("linglong.scout.cache._get_redis", return_value=mock_client):
            history = BriefHistory()
            yesterday = (date.today() - timedelta(days=1)).isoformat()
            history.save(yesterday, {"关键人物": "LeCun says AI is great. Hinton warns about dangers."})

            new_sections = {"关键人物": "LeCun says AI is great. Hinton warns about dangers. New stuff."}
            warnings = history.check_overlap(new_sections)
        assert len(warnings) >= 1
        assert "关键人物" in warnings[0]

    def test_no_overlap_no_warning(self, tmp_path):
        from linglong.scout.brief_history import BriefHistory

        mock_client, store = self._make_history_with_store()
        with patch("linglong.scout.cache._get_redis", return_value=mock_client):
            history = BriefHistory()
            yesterday = (date.today() - timedelta(days=1)).isoformat()
            history.save(yesterday, {"关键人物": "Completely different content about robots."})

            new_sections = {"关键人物": "OpenAI released GPT-6 model today."}
            warnings = history.check_overlap(new_sections)
        assert len(warnings) == 0

    def test_empty_history(self, tmp_path):
        from linglong.scout.brief_history import BriefHistory

        mock_client, _ = self._make_history_with_store()
        with patch("linglong.scout.cache._get_redis", return_value=mock_client):
            history = BriefHistory()
            warnings = history.check_overlap({"关键人物": "content"})
        assert len(warnings) == 0


class TestApiKeyAuth:
    @pytest.mark.asyncio
    async def test_searxng_sends_auth_header(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"results": []}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        config_mock = MagicMock()
        config_mock.ingest.searxng_url = "http://localhost:8088"
        config_mock.ingest.search_timeout = 10.0
        config_mock.ingest.searxng_api_key = "test-secret-key"

        with patch("linglong.scout.collect.httpx.AsyncClient", return_value=mock_client), \
             patch("linglong.scout.collect.get_config", return_value=config_mock):
            await _searxng_search("test query")

        call_kwargs = mock_client.get.call_args
        headers = call_kwargs.kwargs.get("headers", {})
        assert headers.get("Authorization") == "Bearer test-secret-key"

    @pytest.mark.asyncio
    async def test_searxng_no_header_without_key(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"results": []}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        config_mock = MagicMock()
        config_mock.ingest.searxng_url = "http://localhost:8088"
        config_mock.ingest.search_timeout = 10.0
        config_mock.ingest.searxng_api_key = None

        with patch("linglong.scout.collect.httpx.AsyncClient", return_value=mock_client), \
             patch("linglong.scout.collect.get_config", return_value=config_mock):
            await _searxng_search("test query")

        call_kwargs = mock_client.get.call_args
        headers = call_kwargs.kwargs.get("headers", {})
        assert "Authorization" not in headers

    @pytest.mark.asyncio
    async def test_rsshub_appends_key(self):
        rss_xml = '<?xml version="1.0"?><rss version="2.0"><channel><title>T</title></channel></rss>'
        mock_response = MagicMock()
        mock_response.text = rss_xml
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        config_mock = MagicMock()
        config_mock.ingest.rss_sources = [
            {"name": "36氪快讯", "url": "https://rsshub.example.com:1200/36kr/newsflashes"},
        ]
        config_mock.ingest.rsshub_access_key = "rsshub-secret"

        with patch("linglong.scout.collect.httpx.AsyncClient", return_value=mock_client), \
             patch("linglong.scout.collect.get_config", return_value=config_mock):
            await _fetch_rss_feeds()

        called_url = mock_client.get.call_args.args[0]
        assert "key=rsshub-secret" in called_url

    @pytest.mark.asyncio
    async def test_rsshub_key_not_added_for_non_rsshub_urls(self):
        rss_xml = '<?xml version="1.0"?><rss version="2.0"><channel><title>T</title></channel></rss>'
        mock_response = MagicMock()
        mock_response.text = rss_xml
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        config_mock = MagicMock()
        config_mock.ingest.rss_sources = [
            {"name": "TechCrunch", "url": "https://techcrunch.com/category/artificial-intelligence/feed/"},
            {"name": "The Verge", "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"},
        ]
        config_mock.ingest.rsshub_access_key = "rsshub-secret"

        with patch("linglong.scout.collect.httpx.AsyncClient", return_value=mock_client), \
             patch("linglong.scout.collect.get_config", return_value=config_mock):
            await _fetch_rss_feeds()

        for call in mock_client.get.call_args_list:
            called_url = call.args[0]
            assert "key=" not in called_url, f"key should not be in non-RSSHub URL: {called_url}"


class TestUrlValidation:
    def test_rejects_ftp_scheme(self):
        with pytest.raises(ValueError, match="scheme not allowed"):
            _validate_feed_url("ftp://example.com/feed")

    def test_rejects_localhost(self):
        with pytest.raises(ValueError, match="internal network"):
            _validate_feed_url("http://localhost/feed")

    def test_rejects_private_ip(self):
        with pytest.raises(ValueError, match="internal network"):
            _validate_feed_url("http://192.168.1.1/feed")

    def test_allows_public_url(self):
        _validate_feed_url("https://example.com/feed.xml")  # no error

    def test_rejects_empty_host(self):
        with pytest.raises(ValueError, match="hostname"):
            _validate_feed_url("http:///feed")
