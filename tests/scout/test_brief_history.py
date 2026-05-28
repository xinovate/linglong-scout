"""Tests for BriefHistory."""

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from linglong.scout.brief_history import BriefHistory, parse_sections


_SAMPLE_OUTPUT = """# AI 早报 · 2026-05-25

## 👤 关键人物

| 观点/动态 | 来源人 | 解读 |
|-----------|--------|------|
| LLM is a dead end | Yann LeCun | 公开唱反调 |

## 🏢 公司动态

| 事件 | 公司 | 最新融资 | 股价/估值变动 | 解读 |
|------|------|----------|--------------|------|
| 发布 GPT-5.5 | OpenAI | — | 估值 $3000亿 ↑ | 推理速度大幅优化 |

## 📜 政策动态

| 政策名称 | 发布部门 | 解读 |
|----------|----------|------|
| EU AI Act | 欧盟 | 合规成本剧增 |

## ⭐ 开源趋势

| 项目名 | 分类 | Stars | 解读 | 链接 |
|--------|------|-------|------|------|
| foo/bar | 日增长 #1 | 21k | test | [GitHub](https://github.com/foo/bar) |

## 🚀 应用落地

| 产品/功能 | 公司 | 解读 |
|-----------|------|------|
| AI填表 | OpenAI | 实用场景落地 |

━━━━━━━━━━━━━━━━━━━━

## 🔥 今日最有价值信息

**① [Test]**
- 公司层面：...
"""


class TestParseSections:
    def test_extracts_all_dimensions(self):
        sections = parse_sections(_SAMPLE_OUTPUT)
        assert "关键人物" in sections
        assert "公司动态" in sections
        assert "政策动态" in sections
        assert "应用落地" in sections

    def test_excludes_open_source(self):
        sections = parse_sections(_SAMPLE_OUTPUT)
        assert "开源趋势" not in sections

    def test_stops_at_divider(self):
        sections = parse_sections(_SAMPLE_OUTPUT)
        for dim_content in sections.values():
            assert "今日最有价值信息" not in dim_content

    def test_empty_input(self):
        assert parse_sections("") == {}

    def test_no_headers(self):
        assert parse_sections("just some text\nmore text") == {}


def _mock_redis():
    """Create a mock Redis client with in-memory hash storage."""
    store: dict[str, dict[str, str]] = {}

    client = MagicMock()

    def hset(key, mapping=None):
        if mapping:
            store.setdefault(key, {}).update(mapping)

    def hget(key, field):
        return store.get(key, {}).get(field)

    def hgetall(key):
        return store.get(key, {})

    def setex(key, ttl, value):
        pass

    def expire(key, ttl):
        pass

    def delete(key):
        store.pop(key, None)

    def scan(cursor, match=None):
        matching = [k for k in store if match and k.startswith(match.rstrip("*"))]
        return 0, matching

    client.hset.side_effect = hset
    client.hget.side_effect = hget
    client.hgetall.side_effect = hgetall
    client.setex.side_effect = setex
    client.expire.side_effect = expire
    client.delete.side_effect = delete
    client.scan.side_effect = scan

    return client, store


class TestBriefHistory:
    @pytest.fixture
    def mock_r(self):
        client, store = _mock_redis()
        with patch("linglong.scout.cache._get_redis", return_value=client):
            yield client, store

    def test_save_and_load(self, mock_r):
        _, store = mock_r
        history = BriefHistory()
        today = date.today().isoformat()
        sections = {"公司动态": "| 发布 GPT-5.5 | OpenAI | ... |"}
        history.save(today, sections)

        key = f"scout:history:{today}"
        assert key in store
        assert store[key]["公司动态"] == "| 发布 GPT-5.5 | OpenAI | ... |"

    def test_load_past_days(self, mock_r):
        _, store = mock_r
        history = BriefHistory()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        sections = {"公司动态": "| 发布 GPT-5.5 | OpenAI | ... |"}
        history.save(yesterday, sections)

        loaded = history.load()
        assert "公司动态" in loaded
        assert yesterday in loaded["公司动态"]

    def test_load_respects_windows(self, mock_r):
        _, store = mock_r
        history = BriefHistory()
        old_date = (date.today() - timedelta(days=10)).isoformat()
        sections = {"公司动态": "| old news |"}
        history.save(old_date, sections)

        loaded = history.load()
        assert "公司动态" not in loaded

    def test_load_policy_14_day_window(self, mock_r):
        _, store = mock_r
        history = BriefHistory()
        old_date = (date.today() - timedelta(days=10)).isoformat()
        sections = {"政策动态": "| EU AI Act | 欧盟 | ... |"}
        history.save(old_date, sections)

        loaded = history.load()
        assert "政策动态" in loaded

    def test_format_for_prompt_empty(self, mock_r):
        history = BriefHistory()
        assert history.format_for_prompt() == ""

    def test_format_for_prompt_with_data(self, mock_r):
        _, store = mock_r
        history = BriefHistory()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        sections = {"公司动态": "| some event |"}
        history.save(yesterday, sections)

        text = history.format_for_prompt()
        assert "近期已播报" in text
        assert "公司动态" in text

    def test_no_history_returns_empty(self, mock_r):
        history = BriefHistory()
        assert history.load() == {}
