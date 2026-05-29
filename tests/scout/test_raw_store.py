"""Tests for raw_store module."""

import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from linglong.scout.raw_store import (
    _normalize_github,
    _normalize_rss,
    _normalize_searxng,
    cleanup_raw,
    get_raw,
    get_raw_meta,
    has_raw,
    store_raw,
)


class TestNormalizeSearxng:
    def test_basic_mapping(self):
        items = [{"title": "OpenAI news", "url": "https://example.com/1", "snippet": "summary"}]
        result = _normalize_searxng(items, "2026-05-28T06:55:00Z")
        assert len(result) == 1
        assert result[0]["source"] == "searxng"
        assert result[0]["title"] == "OpenAI news"
        assert result[0]["fetched_at"] == "2026-05-28T06:55:00Z"
        assert result[0]["extra"]["query"] == ""

    def test_empty_list(self):
        assert _normalize_searxng([], "t") == []


class TestNormalizeGithub:
    def test_stars_growth_in_extra(self):
        items = [{
            "title": "foo/bar (+500⭐ 日增长)",
            "url": "https://github.com/foo/bar",
            "snippet": "description",
            "stars": "21700",
            "growth": "500",
            "period": "日增长",
        }]
        result = _normalize_github(items, "2026-05-28T06:55:00Z")
        assert result[0]["source"] == "github"
        assert result[0]["extra"]["stars"] == "21700"
        assert result[0]["extra"]["growth"] == "500"
        assert result[0]["extra"]["period"] == "日增长"


class TestNormalizeRss:
    def test_feed_name_in_extra(self):
        items = [{
            "title": "AI news",
            "url": "https://example.com/rss/1",
            "snippet": "summary",
            "source": "36氪",
        }]
        result = _normalize_rss(items, "2026-05-28T06:55:00Z")
        assert result[0]["source"] == "rss"
        assert result[0]["extra"]["feed_name"] == "36氪"


def _mock_redis_with_store():
    """Create mock Redis with in-memory string + hash storage."""
    str_store: dict[str, str] = {}
    hash_store: dict[str, dict[str, str]] = {}

    client = MagicMock()

    def setex(key, ttl, value):
        str_store[key] = value

    def get(key):
        return str_store.get(key)

    def hset(key, mapping=None):
        if mapping:
            hash_store.setdefault(key, {}).update(mapping)

    def hgetall(key):
        return hash_store.get(key, {})

    def expire(key, ttl):
        pass

    def delete(key):
        str_store.pop(key, None)
        hash_store.pop(key, None)

    def exists(key):
        return key in str_store or key in hash_store

    def scan(cursor, match=None):
        prefix = match.rstrip("*") if match else ""
        matching = [k for k in list(str_store.keys()) + list(hash_store.keys()) if k.startswith(prefix)]
        return 0, matching

    client.setex.side_effect = setex
    client.get.side_effect = get
    client.hset.side_effect = hset
    client.hgetall.side_effect = hgetall
    client.expire.side_effect = expire
    client.delete.side_effect = delete
    client.exists.side_effect = exists
    client.scan.side_effect = scan

    return client, str_store, hash_store


@pytest.fixture
def mock_redis():
    client, str_store, hash_store = _mock_redis_with_store()
    with patch("linglong.scout.raw_store._get_redis", return_value=client):
        yield client, str_store, hash_store


@pytest.fixture
def tmp_raw_dir(tmp_path):
    """Redirect raw data dir to temp directory."""
    with patch("linglong.scout.raw_store._raw_dir", return_value=tmp_path):
        yield tmp_path


class TestStoreRaw:
    def test_stores_to_redis(self, mock_redis, tmp_raw_dir):
        _, str_store, _ = mock_redis
        searxng = [{"title": "test", "url": "https://example.com", "snippet": "s"}]
        counts = store_raw(
            target_date="2026-05-28",
            searxng=searxng,
            github=[],
            rss=[],
        )
        assert counts["searxng"] == 1
        assert counts["github"] == 0
        key = "scout:raw:2026-05-28:searxng"
        assert key in str_store
        data = json.loads(str_store[key])
        assert len(data) == 1
        assert data[0]["source"] == "searxng"

    def test_stores_to_file(self, mock_redis, tmp_raw_dir):
        store_raw(target_date="2026-05-28", searxng=[{"title": "t", "url": "u", "snippet": "s"}])
        path = tmp_raw_dir / "2026-05-28_searxng.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert len(data) == 1

    def test_stores_meta(self, mock_redis, tmp_raw_dir):
        _, _, hash_store = mock_redis
        store_raw(target_date="2026-05-28", github_source="opengithubs")
        assert "scout:raw:2026-05-28:meta" in hash_store
        meta_file = tmp_raw_dir / "2026-05-28_meta.json"
        assert meta_file.exists()

    def test_skips_none_sources(self, mock_redis, tmp_raw_dir):
        counts = store_raw(target_date="2026-05-28", searxng=[{"title": "t", "url": "u", "snippet": "s"}])
        assert "github" not in counts
        assert "rss" not in counts


class TestGetRaw:
    def test_reads_from_redis(self, mock_redis, tmp_raw_dir):
        _, str_store, _ = mock_redis
        str_store["scout:raw:2026-05-28:searxng"] = json.dumps([
            {"title": "test", "url": "u", "snippet": "s", "source": "searxng", "fetched_at": "t", "extra": {}},
        ])
        data = get_raw(target_date="2026-05-28")
        assert len(data["searxng"]) == 1

    def test_falls_back_to_file(self, mock_redis, tmp_raw_dir):
        path = tmp_raw_dir / "2026-05-28_rss.json"
        path.write_text(json.dumps([
            {"title": "rss item", "url": "u", "snippet": "s", "source": "rss"},
        ]))
        data = get_raw(target_date="2026-05-28")
        assert len(data["rss"]) == 1
        assert data["rss"][0]["title"] == "rss item"

    def test_returns_empty_for_missing(self, mock_redis, tmp_raw_dir):
        data = get_raw(target_date="2026-05-28")
        assert data["searxng"] == []
        assert data["rss"] == []
        assert data["github"] == []

    def test_filters_by_source(self, mock_redis, tmp_raw_dir):
        _, str_store, _ = mock_redis
        str_store["scout:raw:2026-05-28:searxng"] = json.dumps([{"title": "s"}])
        str_store["scout:raw:2026-05-28:rss"] = json.dumps([{"title": "r"}])
        data = get_raw(target_date="2026-05-28", source="searxng")
        assert "searxng" in data
        assert "rss" not in data


class TestHasRaw:
    def test_true_when_redis_has_data(self, mock_redis, tmp_raw_dir):
        _, str_store, _ = mock_redis
        str_store["scout:raw:2026-05-28:searxng"] = "data"
        assert has_raw("2026-05-28") is True

    def test_true_when_file_exists(self, mock_redis, tmp_raw_dir):
        (tmp_raw_dir / "2026-05-28_github.json").write_text("[]")
        assert has_raw("2026-05-28") is True

    def test_false_when_nothing_exists(self, mock_redis, tmp_raw_dir):
        assert has_raw("2026-05-28") is False


class TestGetRawMeta:
    def test_reads_from_redis_hash(self, mock_redis, tmp_raw_dir):
        _, _, hash_store = mock_redis
        hash_store["scout:raw:2026-05-28:meta"] = {
            "fetched_at": "2026-05-28T06:55:00Z",
            "github_count": "3",
        }
        meta = get_raw_meta("2026-05-28")
        assert meta["fetched_at"] == "2026-05-28T06:55:00Z"

    def test_returns_empty_when_missing(self, mock_redis, tmp_raw_dir):
        meta = get_raw_meta("2026-05-28")
        assert meta == {}


class TestCleanupRaw:
    def test_removes_old_keys(self, mock_redis, tmp_raw_dir):
        _, str_store, _ = mock_redis
        old_date = (date.today() - __import__("datetime").timedelta(days=15)).isoformat()
        str_store[f"scout:raw:{old_date}:searxng"] = "old data"
        removed = cleanup_raw()
        assert removed == 1
