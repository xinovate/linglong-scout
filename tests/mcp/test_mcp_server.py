"""Tests for Linglong Scout MCP Server scout tools."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from linglong.config import get_config, set_config
from linglong.mcp.tools import (
    execute_package,
    fetch_github_trending,
    fetch_raw,
    fetch_rss,
    generate_brief,
    search_web,
)


# --- fetch_rss ---


async def test_fetch_rss_returns_previews():
    mock_items = [
        {"title": "Test Article", "url": "https://example.com/article1",
         "snippet": "Article content here", "source": "test-feed"},
    ]
    with patch("linglong.scout.collect.fetch_single_feed", return_value=mock_items):
        result = await fetch_rss("https://example.com/feed.xml", name="test-feed")
        data = json.loads(result)

    assert "error" not in data
    assert data["count"] == 1
    assert data["results"][0]["title"] == "Test Article"


async def test_fetch_rss_handles_error():
    with patch("linglong.scout.collect.fetch_single_feed", side_effect=Exception("Connection failed")):
        result = await fetch_rss("https://invalid.example/feed.xml")
        data = json.loads(result)

    assert "error" in data


async def test_fetch_rss_delegates_to_fetch_single_feed():
    mock_items = [
        {"title": "Article", "url": "https://example.com/a", "snippet": "s", "source": "feed"},
    ]
    with patch("linglong.scout.collect.fetch_single_feed", return_value=mock_items) as mock_fetch:
        await fetch_rss("https://example.com/feed.xml", name="my-feed", max_items=5)
        mock_fetch.assert_called_once_with(
            "https://example.com/feed.xml", name="my-feed", max_items=5,
        )


# --- generate_brief ---


async def test_generate_brief_returns_output():
    config = get_config()
    config.ingest.packages = [{"name": "ai-morning-brief", "topic": "AI 早报"}]
    set_config(config)

    with patch("linglong.scout.cache.get_brief", return_value=None), \
         patch("linglong.scout.cache.set_brief"), \
         patch("linglong.scout.raw_store.has_raw", return_value=False), \
         patch("linglong.scout.agent.IngestAgent") as mock_agent_cls, \
         patch("linglong.scout.brief_history.BriefHistory") as mock_bh_cls, \
         patch("linglong.scout.feedback.FeedbackStore") as mock_fs_cls:
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value="# AI 早报\n\nContent")
        mock_agent_cls.return_value = mock_agent

        result = await generate_brief()
        data = json.loads(result)

    assert "error" not in data
    assert data["package"] == "ai-morning-brief"
    assert "output" in data


async def test_generate_brief_no_packages():
    config = get_config()
    config.ingest.packages = []
    set_config(config)

    result = await generate_brief()
    data = json.loads(result)

    assert "error" in data
    assert "No packages" in data["error"]


async def test_generate_brief_handles_error():
    config = get_config()
    config.ingest.packages = [{"name": "test", "topic": "test"}]
    set_config(config)

    with patch("linglong.scout.cache.get_brief", return_value=None), \
         patch("linglong.scout.raw_store.has_raw", return_value=False), \
         patch("linglong.scout.agent.IngestAgent", side_effect=Exception("Agent failed")):
        result = await generate_brief()
        data = json.loads(result)

    assert "error" in data


# --- fetch_github_trending ---


async def test_fetch_github_trending_returns_repos():
    mock_repos = [
        {"title": "ai-toolkit (+150⭐ 日增长)", "url": "https://github.com/example/ai-toolkit",
         "snippet": "AI toolkit", "stars": "5000", "growth": "150", "period": "日增长"},
    ]
    with patch("linglong.scout.collect._github_trending", return_value=(mock_repos, "opengithubs")):
        result = await fetch_github_trending(daily=5)
        data = json.loads(result)

    assert "error" not in data
    assert data["count"] == 1
    assert data["source"] == "opengithubs"
    assert data["results"][0]["title"].startswith("ai-toolkit")


async def test_fetch_github_trending_handles_error():
    with patch("linglong.scout.collect._github_trending", side_effect=Exception("GitHub API failed")):
        result = await fetch_github_trending()
        data = json.loads(result)

    assert "error" in data


# --- search_web ---


async def test_search_web_returns_results():
    mock_results = [
        {"title": "AI News", "url": "https://example.com", "snippet": "Summary"},
    ]
    with patch("linglong.scout.collect._searxng_search", return_value=mock_results):
        result = await search_web("AI news", max_results=5)
        data = json.loads(result)

    assert "error" not in data
    assert data["count"] == 1
    assert data["results"][0]["title"] == "AI News"


async def test_search_web_handles_error():
    with patch("linglong.scout.collect._searxng_search", side_effect=Exception("Connection failed")):
        result = await search_web("test query")
        data = json.loads(result)

    assert "error" in data


# --- execute_package ---


async def test_execute_package_returns_results():
    with patch("linglong.scout.agent.IngestAgent") as mock_agent_cls, \
         patch("linglong.scout.brief_history.BriefHistory") as mock_bh_cls, \
         patch("linglong.scout.feedback.FeedbackStore") as mock_fs_cls:
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value="# AI 早报\n\nContent")
        mock_agent_cls.return_value = mock_agent

        result = await execute_package(topic="AI 早报", keywords=["OpenAI news"])
        data = json.loads(result)

    assert "error" not in data
    assert data["package"] == "custom-brief"
    assert "output" in data


async def test_execute_package_handles_error():
    with patch("linglong.scout.agent.IngestAgent", side_effect=Exception("Agent failed")):
        result = await execute_package(topic="test")
        data = json.loads(result)

    assert "error" in data


# --- fetch_raw ---


async def test_fetch_raw_returns_data():
    with patch("linglong.scout.raw_store.get_raw", return_value={
        "searxng": [{"title": "test", "url": "https://example.com", "snippet": "s", "source": "searxng", "fetched_at": "t", "extra": {}}],
        "rss": [],
        "github": [],
    }), \
         patch("linglong.scout.raw_store.get_raw_meta", return_value={"fetched_at": "2026-05-28T06:55:00Z"}):
        result = await fetch_raw(target_date="2026-05-28")
        data = json.loads(result)

    assert "error" not in data
    assert data["date"] == "2026-05-28"
    assert "searxng" in data["sources"]
    assert data["sources"]["searxng"]["count"] == 1


async def test_fetch_raw_invalid_source():
    result = await fetch_raw(target_date="2026-05-28", source="invalid")
    data = json.loads(result)
    assert "error" in data


async def test_fetch_raw_no_data():
    with patch("linglong.scout.raw_store.get_raw", return_value={"searxng": [], "rss": [], "github": []}), \
         patch("linglong.scout.raw_store.get_raw_meta", return_value={}):
        result = await fetch_raw(target_date="2026-05-28")
        data = json.loads(result)

    assert "warning" in data
    assert data["date"] == "2026-05-28"
