"""Tests for CLI commands."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from linglong.cli import cmd_brief, cmd_collect, cmd_ingest, cmd_serve, main
from linglong.config import ScoutConfig


def _make_config(**overrides) -> ScoutConfig:
    defaults = {
        "llm": {"llm_api_key": "k", "llm_base_url": "https://api.example.com", "llm_model": "m"},
        "ingest": {
            "packages": [{
                "name": "test",
                "topic": "AI",
                "output": {"format": "morning-brief"},
                "search_queries": [{"keywords": ["test"], "max_results": 5, "max_age_days": 3}],
            }],
            "dedup_windows": {"test": 7},
        },
    }
    defaults.update(overrides)
    return ScoutConfig(**defaults)


def _make_args(**overrides):
    defaults = {"command": "brief", "force": False, "verbose": False}
    defaults.update(overrides)
    return MagicMock(**defaults)


class TestCmdBrief:
    def test_exits_when_no_packages(self):
        config = _make_config()
        config.ingest.packages = []
        with patch("linglong.config.get_config", return_value=config), \
             pytest.raises(SystemExit, match="1"):
            cmd_brief(_make_args())

    def test_prints_cached_brief_without_force(self, capsys):
        config = _make_config()
        args = _make_args(force=False)

        with patch("linglong.config.get_config", return_value=config), \
             patch("linglong.scout.cache.get_brief", return_value="# Cached Brief"):
            cmd_brief(args)

        captured = capsys.readouterr()
        assert "Cached Brief" in captured.out

    def test_generates_brief_when_no_cache(self, capsys):
        config = _make_config()

        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value="# Fresh Brief")

        with patch("linglong.config.get_config", return_value=config), \
             patch("linglong.scout.cache.get_brief", return_value=None), \
             patch("linglong.scout.cache.set_brief") as mock_set, \
             patch("linglong.scout.agent.IngestAgent", return_value=mock_agent), \
             patch("linglong.scout.feedback.FeedbackStore"), \
             patch("linglong.scout.brief_history.BriefHistory"), \
             patch("linglong.scout.raw_store.has_raw", return_value=False), \
             patch("linglong.config.setup_logging"):
            cmd_brief(_make_args())

        captured = capsys.readouterr()
        assert "Fresh Brief" in captured.out
        mock_set.assert_called_once()

    def test_uses_raw_data_when_available(self, capsys):
        config = _make_config()

        mock_agent = MagicMock()
        mock_agent.run_from_raw = AsyncMock(return_value="# Raw Brief")

        with patch("linglong.config.get_config", return_value=config), \
             patch("linglong.scout.cache.get_brief", return_value=None), \
             patch("linglong.scout.cache.set_brief"), \
             patch("linglong.scout.agent.IngestAgent", return_value=mock_agent), \
             patch("linglong.scout.feedback.FeedbackStore"), \
             patch("linglong.scout.brief_history.BriefHistory"), \
             patch("linglong.scout.raw_store.has_raw", return_value=True), \
             patch("linglong.scout.raw_store.get_raw", return_value={"searxng": [], "github": [], "rss": []}), \
             patch("linglong.scout.raw_store.get_raw_meta", return_value={"github_source": ""}), \
             patch("linglong.config.setup_logging"):
            cmd_brief(_make_args())

        mock_agent.run_from_raw.assert_called_once()
        captured = capsys.readouterr()
        assert "Raw Brief" in captured.out

    def test_exits_on_empty_output(self):
        config = _make_config()

        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value="")

        with patch("linglong.config.get_config", return_value=config), \
             patch("linglong.scout.cache.get_brief", return_value=None), \
             patch("linglong.scout.agent.IngestAgent", return_value=mock_agent), \
             patch("linglong.scout.feedback.FeedbackStore"), \
             patch("linglong.scout.brief_history.BriefHistory"), \
             patch("linglong.scout.raw_store.has_raw", return_value=False), \
             patch("linglong.config.setup_logging"), \
             pytest.raises(SystemExit, match="1"):
            cmd_brief(_make_args())

    def test_force_regenerates_even_with_cache(self, capsys):
        config = _make_config()

        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value="# Force Brief")

        with patch("linglong.config.get_config", return_value=config), \
             patch("linglong.scout.cache.get_brief", return_value="# Old Cached"), \
             patch("linglong.scout.cache.set_brief"), \
             patch("linglong.scout.agent.IngestAgent", return_value=mock_agent), \
             patch("linglong.scout.feedback.FeedbackStore"), \
             patch("linglong.scout.brief_history.BriefHistory"), \
             patch("linglong.scout.raw_store.has_raw", return_value=False), \
             patch("linglong.config.setup_logging"):
            cmd_brief(_make_args(force=True))

        captured = capsys.readouterr()
        assert "Force Brief" in captured.out


class TestCmdIngest:
    def test_exits_when_no_packages(self):
        config = _make_config()
        config.ingest.packages = []
        with patch("linglong.config.get_config", return_value=config), \
             pytest.raises(SystemExit, match="1"):
            cmd_ingest(_make_args())

    def test_prints_output(self, capsys):
        config = _make_config()

        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value="# Scout Output")

        with patch("linglong.config.get_config", return_value=config), \
             patch("linglong.scout.agent.IngestAgent", return_value=mock_agent), \
             patch("linglong.scout.feedback.FeedbackStore"), \
             patch("linglong.scout.brief_history.BriefHistory"), \
             patch("linglong.config.setup_logging"):
            cmd_ingest(_make_args())

        captured = capsys.readouterr()
        assert "Scout Output" in captured.out

    def test_no_output_when_empty(self, capsys):
        config = _make_config()

        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value="")

        with patch("linglong.config.get_config", return_value=config), \
             patch("linglong.scout.agent.IngestAgent", return_value=mock_agent), \
             patch("linglong.scout.feedback.FeedbackStore"), \
             patch("linglong.scout.brief_history.BriefHistory"), \
             patch("linglong.config.setup_logging"):
            cmd_ingest(_make_args())

        captured = capsys.readouterr()
        assert captured.out == ""


class TestCmdCollect:
    def test_exits_when_no_packages(self):
        config = _make_config()
        config.ingest.packages = []
        with patch("linglong.config.get_config", return_value=config), \
             pytest.raises(SystemExit, match="1"):
            cmd_collect(_make_args())

    def test_collects_and_stores(self, capsys):
        config = _make_config()

        mock_raw = {"searxng": [{"title": "T"}], "github": [], "rss": [], "github_source": ""}

        with patch("linglong.config.get_config", return_value=config), \
             patch("linglong.scout.collect.collect", new_callable=AsyncMock, return_value=mock_raw), \
             patch("linglong.scout.raw_store.store_raw", return_value={"searxng": 1, "github": 0, "rss": 0}) as mock_store, \
             patch("linglong.config.setup_logging"):
            cmd_collect(_make_args())

        captured = capsys.readouterr()
        assert "Collected 1 items" in captured.out
        mock_store.assert_called_once()


class TestCmdServe:
    def test_calls_mcp_main(self):
        with patch("linglong.mcp.main") as mock_main:
            cmd_serve(_make_args())
        mock_main.assert_called_once()


class TestMainParser:
    def test_no_command_exits(self):
        with patch("sys.argv", ["linglong-scout"]), \
             pytest.raises(SystemExit, match="1"):
            main()

    def test_verbose_flag(self):
        with patch("sys.argv", ["linglong-scout", "-v", "brief"]), \
             patch("linglong.cli.cmd_brief"), \
             patch("linglong.config.setup_logging") as mock_log:
            main()
        mock_log.assert_called_once_with("DEBUG")

    def test_brief_subcommand(self):
        with patch("sys.argv", ["linglong-scout", "brief", "--force"]), \
             patch("linglong.cli.cmd_brief") as mock_cmd:
            main()
        args_passed = mock_cmd.call_args[0][0]
        assert args_passed.force is True
