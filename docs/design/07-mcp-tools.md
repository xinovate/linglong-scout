# D-07 MCP 工具参考

> 状态：✅ 已实现 | 最后更新：2026-05-29 | 依赖：[D-06 MCP 接入](06-mcp.md)
> 本文件是 [D-06 MCP 接入](06-mcp.md) 的工具参数补充。部署和认证详见 D-06。

---

## 工具总览

| 工具 | 说明 |
|------|------|
| `search_web` | SearXNG 搜索 |
| `fetch_rss` | 采集单个 RSS feed |
| `fetch_github_trending` | GitHub 趋势项目（三级 fallback） |
| `fetch_raw` | 获取结构化原始数据 |
| `generate_brief` | 生成 AI 早报（缓存按用户隔离） |
| `execute_package` | 自定义参数执行采集+生成 |
| `record_feedback` | 记录用户偏好（按用户隔离，影响后续采集权重） |

所有工具返回 JSON 字符串，错误响应格式统一为 `{"error": "描述信息"}`。

---

## search_web

通过 SearXNG 搜索网页，返回标题、URL、摘要。

### 参数

| 参数 | 类型 | 必选 | 默认值 | 说明 |
|------|------|------|--------|------|
| `query` | string | 是 | — | 搜索关键词 |
| `max_results` | int | 否 | 10 | 返回结果数量上限 |

### 请求示例

```json
{
  "name": "search_web",
  "arguments": {
    "query": "OpenAI GPT-5 2026",
    "max_results": 3
  }
}
```

### 返回示例

```json
{
  "results": [
    {
      "title": "OpenAI announces GPT-5 with multimodal reasoning",
      "url": "https://example.com/openai-gpt5",
      "snippet": "OpenAI has unveiled GPT-5, featuring advanced multimodal reasoning...",
      "engine": "google"
    }
  ],
  "count": 1
}
```

---

## fetch_rss

采集并解析 RSS/Atom feed，返回条目预览。

### 参数

| 参数 | 类型 | 必选 | 默认值 | 说明 |
|------|------|------|--------|------|
| `url` | string | 是 | — | Feed URL |
| `name` | string | 否 | `null` | Feed 名称（显示用） |
| `max_items` | int | 否 | 20 | 返回条目数量上限 |

RSSHub URL（包含 `:1200`）会自动追加 `ACCESS_KEY`。

### 请求示例

```json
{
  "name": "fetch_rss",
  "arguments": {
    "url": "http://127.0.0.1:1200/36kr/newsflashes",
    "name": "36氪快讯",
    "max_items": 5
  }
}
```

### 返回示例

```json
{
  "results": [
    {
      "title": "某公司完成 A 轮融资",
      "url": "https://www.36kr.com/newsflashes/12345",
      "snippet": "36氪获悉，某公司宣布完成 A 轮融资...",
      "source": "36氪快讯"
    }
  ],
  "count": 1
}
```

---

## fetch_github_trending

获取 GitHub 趋势项目（stars 增长排行），支持日/周/月三个周期。数据源三级 fallback：OpenGithubs → wangchujiang HTML → GitHub Search API。

### 参数

| 参数 | 类型 | 必选 | 默认值 | 说明 |
|------|------|------|--------|------|
| `daily` | int | 否 | 5 | 日增长排行数量 |
| `weekly` | int | 否 | 3 | 周增长排行数量 |
| `monthly` | int | 否 | 3 | 月增长排行数量 |

### 请求示例

```json
{
  "name": "fetch_github_trending",
  "arguments": {
    "daily": 5,
    "weekly": 3,
    "monthly": 3
  }
}
```

### 返回示例

```json
{
  "results": [
    {
      "title": "ai-toolkit (+150⭐ 日增长)",
      "url": "https://github.com/example/ai-toolkit",
      "snippet": "AI toolkit for rapid prototyping",
      "stars": "5000",
      "growth": "150",
      "period": "日增长"
    }
  ],
  "count": 1,
  "source": "opengithubs"
}
```

`source` 取值：`opengithubs`（主）、`wangchujiang`（HTML fallback）、`search-api`（GitHub Search API fallback）。

---

## fetch_raw

获取指定日期的结构化原始采集数据（Redis 热 → JSON 文件冷 fallback）。

### 参数

| 参数 | 类型 | 必选 | 默认值 | 说明 |
|------|------|------|--------|------|
| `target_date` | string | 否 | 今天 | ISO 日期，如 `"2026-05-28"` |
| `source` | string | 否 | `null` | 按源过滤：`"searxng"` / `"rss"` / `"github"` |

### 请求示例

```json
{
  "name": "fetch_raw",
  "arguments": {
    "target_date": "2026-05-28",
    "source": "rss"
  }
}
```

### 返回示例

```json
{
  "date": "2026-05-28",
  "meta": {
    "fetched_at": "2026-05-28T06:55:00Z",
    "searxng_count": 160,
    "rss_count": 85,
    "github_count": 11,
    "github_source": "trending"
  },
  "sources": {
    "rss": {
      "count": 85,
      "items": [
        {
          "title": "某公司发布新模型",
          "url": "https://...",
          "snippet": "摘要文本",
          "source": "rss",
          "published": "2026-05-28T02:00:00Z",
          "fetched_at": "2026-05-28T06:55:00Z",
          "extra": {"feed_name": "AIHOT", "feed_url": "https://aihot.virxact.com/feed"}
        }
      ]
    }
  }
}
```

无数据时返回：

```json
{
  "date": "2026-04-01",
  "meta": {},
  "sources": {},
  "warning": "No raw data found for this date"
}
```

---

## generate_brief

生成 AI 早报。优先使用 Redis 缓存（按 user_id 隔离），无缓存时复用 raw 数据或采集后 LLM 合成。

### 参数

无。

### 行为

1. 检查 `scout:brief:{date}:{user_id}` 缓存，命中则直接返回
2. 检查当天 raw 数据是否存在，存在则跳过采集直接用已有数据
3. 否则执行完整采集 → 存储 raw → LLM 生成
4. 生成结果写入用户专属缓存（TTL 25h）

**注意**：缓存按 token 中的 user_id 隔离，不同用户看到各自的早报。

### 请求示例

```json
{
  "name": "generate_brief",
  "arguments": {}
}
```

### 返回示例

首次生成：

```json
{
  "package": "ai-morning-brief",
  "output_length": 4200,
  "cached": false,
  "output": "# AI 早报 2026-05-28\n\n## 关键人物\n...\n## 公司动态\n..."
}
```

命中缓存：

```json
{
  "package": "ai-morning-brief",
  "output_length": 4200,
  "cached": true,
  "output": "# AI 早报 2026-05-28\n\n## 关键人物\n..."
}
```

---

## execute_package

自定义参数执行采集 + LLM 生成，不依赖 YAML 文件。

### 参数

| 参数 | 类型 | 必选 | 默认值 | 说明 |
|------|------|------|--------|------|
| `topic` | string | 是 | — | 早报主题，如 `"AI 早报"` |
| `keywords` | string[] | 否 | `null` | SearXNG 搜索关键词，空则跳过搜索 |
| `name` | string | 否 | `"custom-brief"` | 包名标识 |
| `max_results` | int | 否 | 5 | 每个关键词返回结果上限 |

### 请求示例

```json
{
  "name": "execute_package",
  "arguments": {
    "topic": "AI 早报",
    "keywords": ["OpenAI news", "Claude AI update"],
    "max_results": 5
  }
}
```

### 返回示例

```json
{
  "package": "custom-brief",
  "output_length": 2100,
  "output": "# AI 早报\n\n..."
}
```

---

## record_feedback

记录用户对采集结果的偏好。数据按 user_id 隔离，仅影响当前用户的后续采集权重。

### 参数

| 参数 | 类型 | 必选 | 默认值 | 说明 |
|------|------|------|--------|------|
| `content_hash` | string | 是 | — | 内容哈希标识 |
| `feedback` | string | 是 | — | `"useful"` 或 `"not_interested"` |
| `tags` | string[] | 否 | `null` | 关联标签 |

### 影响范围

- 偏好数据按 token 中的 user_id 隔离存储（SQLite user_id 列）
- `generate_brief` 生成时注入当前用户的偏好文本到 LLM prompt，影响内容筛选和排序
- 不影响其他用户的采集结果

### 请求示例

```json
{
  "name": "record_feedback",
  "arguments": {
    "content_hash": "a1b2c3d4",
    "feedback": "useful",
    "tags": ["OpenAI", "GPT-5"]
  }
}
```

### 返回示例

```json
{
  "status": "recorded",
  "content_hash": "a1b2c3d4",
  "feedback": "useful"
}
```

---

## 自动调度

MCP server 启动时自动拉起后台采集调度器（纯 asyncio），无需外部 cron。

| 配置字段 | 默认值 | 说明 |
|---------|--------|------|
| `ingest.collect_schedule` | `"06:55"` | 每天采集时间（HH:MM），留空禁用 |

调度流程：sleep 到目标时间 → `collect_data()` → `store_raw()` → Redis + JSON 文件 → 循环

---

## 错误响应

所有工具失败时返回统一格式：

```json
{"error": "人类可读的错误描述"}
```

常见错误：

| 场景 | 错误信息 |
|------|---------|
| SearXNG 不可达 | `search_web failed: ...` |
| RSS feed 解析失败 | `fetch_rss failed: ...` |
| 无 raw 数据 | 返回 `warning` 字段，非 error |
| feedback 值非法 | `feedback must be 'useful' or 'not_interested'` |
| source 参数非法 | `Invalid source 'xxx'. Use: searxng, rss, github` |
| 无配置包 | `No packages configured in .scout.yml` |
