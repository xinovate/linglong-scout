"""Tests for FeedbackStore."""

import json
import tempfile
from pathlib import Path

from linglong.scout.feedback import FeedbackStore


def _make_store(tmpdir: Path) -> FeedbackStore:
    return FeedbackStore(db_path=tmpdir / "feedback.db")


def test_record_and_query(tmp_path):
    store = _make_store(tmp_path)
    store.record("hash1", "useful", ["funding", "openai"])
    store.record("hash2", "not_interested", ["policy"])
    store.record("hash3", "useful", ["funding", "anthropic"])

    prefs = store.get_preferences()
    assert "funding" in prefs
    assert prefs["funding"] > 0  # 2 useful
    assert "policy" in prefs
    assert prefs["policy"] < 0  # 1 not_interested


def test_empty_preferences(tmp_path):
    store = _make_store(tmp_path)
    prefs = store.get_preferences()
    assert prefs == {}


def test_preference_text_empty(tmp_path):
    store = _make_store(tmp_path)
    assert store.get_preference_text() == ""


def test_preference_text_with_data(tmp_path):
    store = _make_store(tmp_path)
    store.record("h1", "useful", ["funding"])
    store.record("h2", "not_interested", ["policy"])
    text = store.get_preference_text()
    assert "funding" in text
    assert "policy" in text


def test_mixed_feedback_on_same_tag(tmp_path):
    store = _make_store(tmp_path)
    store.record("h1", "useful", ["open_source"])
    store.record("h2", "useful", ["open_source"])
    store.record("h3", "not_interested", ["open_source"])

    prefs = store.get_preferences()
    # 2 useful - 1 not_interested = net positive but < 1
    assert prefs["open_source"] > 0
    assert prefs["open_source"] < 1


class TestMCPRecordFeedback:
    """Tests for MCP record_feedback tool function."""

    def test_record_useful(self, tmp_path):
        from linglong.mcp.tools import record_feedback

        store = _make_store(tmp_path)
        with patch_store(store):
            result = json.loads(record_feedback("hash_abc", "useful", ["funding"]))
        assert result["status"] == "recorded"

    def test_record_invalid_feedback(self):
        from linglong.mcp.tools import record_feedback

        result = json.loads(record_feedback("hash_abc", "maybe"))
        assert "error" in result

    def test_record_not_interested(self, tmp_path):
        from linglong.mcp.tools import record_feedback

        store = _make_store(tmp_path)
        with patch_store(store):
            result = json.loads(record_feedback("hash_xyz", "not_interested", ["policy"]))
        assert result["status"] == "recorded"


def patch_store(store: FeedbackStore):
    """Context manager to patch FeedbackStore() to return a specific instance."""
    from unittest.mock import patch
    return patch("linglong.scout.feedback.FeedbackStore", return_value=store)
