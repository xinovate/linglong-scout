"""Tests for Linglong Scout MCP Server scout tools."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from linglong_scout.config import get_config, set_config
from linglong_scout.mcp.tools import (
    execute_package,
    fetch_rss,
    generate_brief,
    search_web,
)


# --- fetch_rss ---


def test_fetch_rss_returns_previews():
    rss_xml = """<?xml version="1.0"?>
    <rss version="2.0">
      <channel>
        <title>Test Feed</title>
        <item>
          <title>Test Article</title>
          <link>https://example.com/article1</link>
          <description>Article content here</description>
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

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = fetch_rss("https://example.com/feed.xml", name="test-feed")
        data = json.loads(result)

    assert "error" not in data
    assert data["count"] == 1
    assert data["results"][0]["title"] == "Test Article"


def test_fetch_rss_handles_error():
    with patch("asyncio.run", side_effect=Exception("Connection failed")):
        result = fetch_rss("https://invalid.example/feed.xml")
        data = json.loads(result)

    assert "error" in data


def test_fetch_rss_rsshub_key_only_for_rsshub_urls():
    rss_xml = '<?xml version="1.0"?><rss version="2.0"><channel><title>T</title></channel></rss>'
    mock_response = MagicMock()
    mock_response.text = rss_xml
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    config_mock = MagicMock()
    config_mock.ingest.rsshub_access_key = "test-key"

    with patch("httpx.AsyncClient", return_value=mock_client), \
         patch("linglong_scout.mcp.tools.get_config", return_value=config_mock):
        # Non-RSSHub URL should NOT get key
        fetch_rss("https://techcrunch.com/feed/")
        called_url = mock_client.get.call_args.args[0]
        assert "key=" not in called_url

        mock_client.get.reset_mock()
        # RSSHub URL should get key
        fetch_rss("http://redacted-server-ip:1200/36kr/newsflashes")
        called_url = mock_client.get.call_args.args[0]
        assert "key=test-key" in called_url


# --- generate_brief ---


def test_generate_brief_returns_output():
    config = get_config()
    config.ingest.packages = [{"name": "ai-morning-brief", "topic": "AI 早报"}]
    set_config(config)

    with patch("linglong_scout.ingest.agent.IngestAgent") as mock_agent_cls, \
         patch("linglong_scout.ingest.brief_history.BriefHistory") as mock_bh_cls, \
         patch("linglong_scout.ingest.feedback.FeedbackStore") as mock_fs_cls, \
         patch("asyncio.run", return_value="# AI 早报\n\nContent"):
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value="# AI 早报\n\nContent")
        mock_agent_cls.return_value = mock_agent

        result = generate_brief()
        data = json.loads(result)

    assert "error" not in data
    assert data["package"] == "ai-morning-brief"
    assert "output" in data


def test_generate_brief_no_packages():
    config = get_config()
    config.ingest.packages = []
    set_config(config)

    result = generate_brief()
    data = json.loads(result)

    assert "error" in data
    assert "No packages" in data["error"]


def test_generate_brief_handles_error(tmp_path):
    config = get_config()
    config.ingest.packages = [{"name": "test", "topic": "test"}]
    config.ingest.brief_output_dir = str(tmp_path / "briefs")
    set_config(config)

    with patch("linglong_scout.ingest.agent.IngestAgent", side_effect=Exception("Agent failed")):
        result = generate_brief()
        data = json.loads(result)

    assert "error" in data


# --- search_web ---


def test_search_web_returns_results():
    mock_data = {
        "results": [
            {"title": "AI News", "url": "https://example.com", "content": "Summary", "engine": "google"},
        ]
    }
    mock_response = MagicMock()
    mock_response.json.return_value = mock_data
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = search_web("AI news", max_results=5)
        data = json.loads(result)

    assert "error" not in data
    assert data["count"] == 1
    assert data["results"][0]["title"] == "AI News"


def test_search_web_handles_error():
    with patch("asyncio.run", side_effect=Exception("Connection failed")):
        result = search_web("test query")
        data = json.loads(result)

    assert "error" in data


# --- execute_package ---


def test_execute_package_returns_results():
    with patch("linglong_scout.ingest.package.SourcePackage") as mock_pkg_cls, \
         patch("linglong_scout.ingest.agent.IngestAgent") as mock_agent_cls, \
         patch("linglong_scout.ingest.brief_history.BriefHistory") as mock_bh_cls, \
         patch("linglong_scout.ingest.feedback.FeedbackStore") as mock_fs_cls, \
         patch("asyncio.run", return_value="# AI 早报\n\nContent"):
        mock_pkg = MagicMock()
        mock_pkg.name = "test-package"
        mock_pkg_cls.from_yaml.return_value = mock_pkg

        result = execute_package("/path/to/package.yaml")
        data = json.loads(result)

    assert "error" not in data
    assert data["package"] == "test-package"
    assert "output" in data


def test_execute_package_handles_error():
    with patch("linglong_scout.ingest.package.SourcePackage") as mock_cls:
        mock_cls.from_yaml.side_effect = FileNotFoundError("Package not found")

        result = execute_package("/nonexistent/package.yaml")
        data = json.loads(result)

    assert "error" in data
