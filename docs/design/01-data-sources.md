# D-01 数据源架构

> 状态：✅ 已实现 | 最后更新：2026-05-26

---

## 概述

ingest 的数据来自三路并发采集：SearXNG 搜索、GitHub Trending、RSS 订阅源。三路通过 `asyncio.gather` 并行拉取。

```
IngestAgent.run()
  ├── _search_all_keywords()    SearXNG 56 次查询 Semaphore(5) 并发
  ├── _github_trending()         GitHub Trending 日/周/月三级 fallback
  └── _fetch_rss_feeds()         RSS 11 源 Semaphore(3) 并发
```

---

## SearXNG 搜索

**后端**：自建 SearXNG 实例

**关键词分组**（56 个，分 6 组）：

| 组 | 维度覆盖 | 关键词数 | max_results |
|---|---------|---------|-------------|
| 1 | 关键人物 | 18 | 3 |
| 2 | 公司动态 | 12 | 5 |
| 3 | 融资估值 | 5 | 3 |
| 4 | 政策动态 | 16 | 5 |
| 5 | 开源趋势 | 2 | 5 |
| 6 | 应用落地 | 5 | 3 |

**并发策略**：`asyncio.Semaphore(5)`，56 次查询并发执行，~8s 完成（vs 串行 ~45s）。

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

## RSS 订阅源（11 源）

| 源 | 类型 | 条目/次 | 维度覆盖 |
|---|------|---------|---------|
| AIHOT | RSS 直连 | ~30 | 全维度（编辑精选） |
| 36氪 | RSS 直连 | ~30 | 公司动态、应用落地 |
| 36氪快讯 | RSSHub | ~20 | 政策动态、应用落地 |
| 量子位 | RSS 直连 | ~10 | 公司动态、应用落地 |
| The Rundown AI | RSS 直连 | ~20 | 关键人物、公司动态 |
| 财联社电报 | RSSHub | ~20 | 公司动态、政策动态 |
| 财联社深度 | RSSHub | ~10 | 公司动态、政策动态 |
| TechCrunch AI | RSS 直连 | ~20 | 关键人物、公司动态（英文） |
| The Verge AI | RSS 直连 | ~15 | 公司动态、应用落地（英文） |
| 工信部文件公示 | RSSHub (gov) | ~15 | 政策动态 |
| 发改委新闻动态 | RSSHub (gov) | ~25 | 政策动态 |

**并发策略**：`asyncio.Semaphore(3)`，11 源并发拉取。

**RSSHub 认证**：`ACCESS_KEY` 仅追加到包含 `:1200` 端口的 URL。

---

## 性能数据

| 阶段 | 串行 | 并发 |
|------|------|------|
| SearXNG 56 次查询 | ~45s | ~8s |
| GitHub | ~2s | ~2s（与 SearXNG 并行） |
| RSS 11 源 | ~10s | ~3s（并行） |
| **数据采集总耗时** | **~57s** | **~7.6s** |

---

## 关键文件

| 文件 | 说明 |
|------|------|
| `src/linglong_scout/scout/agent.py` | `_search_all_keywords()` / `_github_trending()` / `_fetch_rss_feeds()` |
| `.scout.yml` | RSS 源列表、搜索关键词、SearXNG/RSSHub 配置 |
