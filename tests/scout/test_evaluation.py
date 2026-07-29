"""Tests for deterministic morning brief evaluation."""

import json

from linglong.scout.evaluation import evaluate_brief, load_raw_snapshot


def _raw() -> dict:
    return {
        "rss": [
            {
                "title": "Person",
                "url": "https://example.com/person",
                "published": "2026-06-03",
            },
            {
                "title": "Industry",
                "url": "https://example.com/industry",
                "published": "2026-06-02",
            },
            {
                "title": "Paper",
                "url": "https://example.com/paper",
                "published": "2026-06-01",
            },
            {
                "title": "Funding",
                "url": "https://example.com/funding",
                "published": "2026-06-02",
            },
            {
                "title": "Policy",
                "url": "https://example.com/policy",
                "published": "2026-06-01",
            },
        ],
        "github": [
            {
                "title": "a/repo",
                "url": "https://github.com/a/repo",
                "extra": {"period": "日增长", "growth": "200"},
            },
            {
                "title": "b/repo",
                "url": "https://github.com/b/repo",
                "extra": {"period": "日增长", "growth": "100"},
            },
            {
                "title": "weekly/repo",
                "url": "https://github.com/weekly/repo",
                "extra": {"period": "周增长", "growth": "999"},
            },
        ],
        "github_source": "fixture",
    }


def _brief() -> str:
    return """# AI 早报

### 👤 关键人物
| 动态 | 人物 | 日期 | 解读 | 来源 |
|---|---|---|---|---|
| 动态 | 人物 | 6.3 | 解读 | [来源](https://example.com/person) |

### 🏢 行业要闻
| 事件 | 公司/日期 | 解读 | 来源 |
|---|---|---|---|
| 事件 | 公司 / 6.2 | 解读 | [来源](https://example.com/industry) |

### 🔬 学术前沿
| 论文 | 日期 | 作者 | 领域 | 解读 | 链接 |
|---|---|---|---|---|---|
| 论文 | 6.1 | 作者 | AI | 解读 | [论文](https://example.com/paper) |

### 💰 融资动态
- 融资 — [来源](https://example.com/funding)

### 📜 政策动态
- 政策 — [来源](https://example.com/policy)

### ⭐ 开源趋势
1. [a/repo](https://github.com/a/repo)
2. [b/repo](https://github.com/b/repo)

### 🔥 今日最有价值信息
**① 一**
**② 二**
**③ 三**
**④ 四**
**⑤ 五**
"""


def _check(report, name: str):
    return next(check for check in report.checks if check.name == name)


def test_accepts_valid_brief():
    report = evaluate_brief(_brief(), _raw(), "2026-06-04")

    assert report.passed


def test_rejects_unknown_and_duplicate_links():
    output = _brief().replace(
        "- 融资 — [来源](https://example.com/funding)",
        "- 融资 — [来源](https://example.com/invented)",
    ).replace(
        "- 政策 — [来源](https://example.com/policy)",
        "- 政策 — [来源](https://example.com/industry)",
    )

    report = evaluate_brief(output, _raw(), "2026-06-04")

    assert not _check(report, "link_provenance").passed
    assert not _check(report, "cross_section_duplicates").passed


def test_rejects_stale_link_and_wrong_github_order():
    raw = _raw()
    raw["rss"][0]["published"] = "2026-05-01"
    output = _brief().replace(
        "1. [a/repo](https://github.com/a/repo)\n"
        "2. [b/repo](https://github.com/b/repo)",
        "1. [b/repo](https://github.com/b/repo)\n"
        "2. [a/repo](https://github.com/a/repo)",
    )

    report = evaluate_brief(output, raw, "2026-06-04")

    assert not _check(report, "link_timeliness").passed
    assert not _check(report, "github_daily_top8").passed


def test_normalizes_equivalent_source_urls():
    raw = _raw()
    raw["rss"][3]["url"] = (
        "https://www.example.com/funding?f=rss&utm_source=feed#fragment"
    )

    report = evaluate_brief(_brief(), raw, "2026-06-04")

    assert _check(report, "link_provenance").passed
    assert _check(report, "link_timeliness").passed


def test_detects_duplicate_across_equivalent_urls():
    output = _brief().replace(
        "https://example.com/policy",
        "https://www.example.com/industry?utm_source=brief",
    )

    report = evaluate_brief(output, _raw(), "2026-06-04")

    assert _check(report, "link_provenance").passed
    assert not _check(report, "cross_section_duplicates").passed


def test_loads_cold_snapshot(tmp_path):
    (tmp_path / "2026-06-04_rss.json").write_text(
        json.dumps([{"url": "https://example.com/rss"}]),
        encoding="utf-8",
    )
    (tmp_path / "2026-06-04_github.json").write_text(
        json.dumps([{"url": "https://github.com/a/repo"}]),
        encoding="utf-8",
    )
    (tmp_path / "2026-06-04_meta.json").write_text(
        json.dumps({"github_source": "fixture"}),
        encoding="utf-8",
    )

    raw = load_raw_snapshot(tmp_path, "2026-06-04")

    assert raw["github_source"] == "fixture"
    assert len(raw["rss"]) == 1
    assert len(raw["github"]) == 1
