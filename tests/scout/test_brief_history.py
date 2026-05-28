"""Tests for BriefHistory."""

import json
from datetime import date, timedelta
from pathlib import Path

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


class TestBriefHistory:
    @pytest.fixture
    def history_dir(self, tmp_path: Path) -> Path:
        return tmp_path / "brief_history"

    def test_save_and_load(self, history_dir: Path):
        history = BriefHistory(history_dir)
        today = date.today().isoformat()
        sections = {"公司动态": "| 发布 GPT-5.5 | OpenAI | ... |"}
        history.save(today, sections)

        # Can't load today's (only past days), so check file directly
        path = history_dir / f"{today}.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "公司动态" in data

    def test_load_past_days(self, history_dir: Path):
        history = BriefHistory(history_dir)
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        sections = {"公司动态": "| 发布 GPT-5.5 | OpenAI | ... |"}
        history.save(yesterday, sections)

        loaded = history.load()
        assert "公司动态" in loaded
        assert yesterday in loaded["公司动态"]

    def test_load_respects_windows(self, history_dir: Path):
        history = BriefHistory(history_dir)
        # 公司动态 window is 7 days; save something 10 days ago
        old_date = (date.today() - timedelta(days=10)).isoformat()
        sections = {"公司动态": "| old news |"}
        history.save(old_date, sections)

        loaded = history.load()
        # Should NOT appear (10 > 7 day window for 公司动态)
        assert "公司动态" not in loaded

    def test_load_policy_14_day_window(self, history_dir: Path):
        history = BriefHistory(history_dir)
        # 政策动态 window is 14 days; save something 10 days ago
        old_date = (date.today() - timedelta(days=10)).isoformat()
        sections = {"政策动态": "| EU AI Act | 欧盟 | ... |"}
        history.save(old_date, sections)

        loaded = history.load()
        assert "政策动态" in loaded

    def test_format_for_prompt_empty(self, history_dir: Path):
        history = BriefHistory(history_dir)
        assert history.format_for_prompt() == ""

    def test_format_for_prompt_with_data(self, history_dir: Path):
        history = BriefHistory(history_dir)
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        sections = {"公司动态": "| some event |"}
        history.save(yesterday, sections)

        text = history.format_for_prompt()
        assert "近期已播报" in text
        assert "公司动态" in text

    def test_cleanup(self, history_dir: Path):
        history = BriefHistory(history_dir)
        # Save old files
        for days_ago in [5, 10, 20, 30]:
            d = (date.today() - timedelta(days=days_ago)).isoformat()
            history.save(d, {"公司动态": "test"})

        history.cleanup(max_days=16)

        remaining = list(history_dir.glob("*.json"))
        # Files from 5 and 10 days ago should remain (< 16)
        # Files from 20 and 30 days ago should be removed
        remaining_dates = [f.stem for f in remaining]
        assert len(remaining) == 2

    def test_no_history_returns_empty(self, history_dir: Path):
        history = BriefHistory(history_dir)
        assert history.load() == {}
