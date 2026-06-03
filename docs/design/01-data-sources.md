# D-01 数据源架构

> 状态：✅ 已实现 | 最后更新：2026-06-01
> 属于 [D-00 设计总览](00-overview.md) 的数据层子设计。

---

## 概述

Scout 采用 **RSS 为主力、SearXNG 为精准补充** 的采集策略。三路通过 `asyncio.gather` 并行拉取。

```
IngestAgent.run()
  ├── _fetch_rss_feeds()         RSS 11 源（主力，人工编辑筛选） Semaphore(3) 并发
  ├── _search_all_keywords()     SearXNG 17 次精准查询（补充） Semaphore(5) 并发
  └── _github_trending()         GitHub Trending 日/周/月三级 fallback
```

---

## SearXNG 搜索（精准补充）

**后端**：自建 SearXNG 实例

**策略**：只保留实体级精准查询（具体人名/公司名/产品名），宽泛主题查询由 RSS 覆盖。

**关键词分组**（17 个，分 3 组）：

| 组 | 定位 | 关键词数 | max_results |
|---|------|---------|-------------|
| 1 | 关键人物 | 8 | 2 |
| 2 | 公司/产品 | 6 | 2 |
| 3 | 应用/技术 | 3 | 2 |

**并发策略**：`asyncio.Semaphore(5)`，17 次查询并发执行。

**认证**：Bearer Token（`searxng_api_key`），通过 nginx 反代注入。

---

## GitHub Trending（三级 fallback）

| 优先级 | 数据源 | 方法 | 输出 |
|--------|--------|------|------|
| 1 | OpenGithubs | GitHub Contents API | 日 5 + 周 3 + 月 3 = 11 条 |
| 2 | wangchujiang.com | HTML 解析 | 仅日榜，有缓存延迟 |
| 3 | GitHub Search API | `created:>30days stars:>500` | 非趋势，兜底 |

**认证**：优先用 `gh auth token`（5000 req/hr），未认证仅 60 req/hr。

---

## RSS 订阅源（11 源，信息主力）

| 源 | 类型 | 条目/次 | 维度覆盖 |
|---|------|---------|---------|
| AIHOT | RSS 直连 | ~30 | 全维度（编辑精选） |
| 36氪 | RSS 直连 | ~30 | 行业要闻 |
| 36氪快讯 | RSSHub | ~20 | 行业要闻、政策动态 |
| 量子位 | RSS 直连 | ~10 | 行业要闻 |
| The Rundown AI | RSS 直连 | ~20 | 关键人物、行业要闻 |
| 财联社电报 | RSSHub | ~20 | 行业要闻、政策动态 |
| 财联社深度 | RSSHub | ~10 | 行业要闻、政策动态 |
| TechCrunch AI | RSS 直连 | ~20 | 关键人物、行业要闻（英文） |
| The Verge AI | RSS 直连 | ~15 | 行业要闻（英文） |
| 工信部文件公示 | RSSHub (gov) | ~15 | 政策动态 |
| 发改委新闻动态 | RSSHub (gov) | ~25 | 政策动态 |

**并发策略**：`asyncio.Semaphore(3)`，11 源并发拉取。

**RSSHub 认证**：源定义中带 `route` 字段的，采集时自动在前面拼接 `rsshub_url` 配置值，并注入 `access_key` 参数；带 `url` 字段的直接使用原 URL，不做拼接。

---

## 性能数据

| 阶段 | 串行 | 并发 |
|------|------|------|
| SearXNG 17 次查询 | ~15s | ~3s |
| GitHub | ~2s | ~2s（与 SearXNG 并行） |
| RSS 11 源 | ~10s | ~3s（并行） |
| **数据采集总耗时** | **~27s** | **~3s** |

---

## 关键文件

| 文件 | 说明 |
|------|------|
| `src/linglong/scout/collect.py` | `_search_all_keywords()` / `_github_trending()` / `fetch_single_feed()` / `_fetch_rss_feeds()` |
| `.scout.yml` | RSS 源列表、搜索关键词、SearXNG/RSSHub 配置 |
