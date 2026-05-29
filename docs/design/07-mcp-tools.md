# D-07 MCP 工具参考

> 状态：✅ 已实现 | 最后更新：2026-05-29 | 依赖：[D-06 MCP 接入](06-mcp.md)

---

## 工具总览

| 工具 | 说明 |
|------|------|
| `search_web` | SearXNG 搜索 |
| `fetch_rss` | 采集单个 RSS feed |
| `fetch_raw` | 获取结构化原始数据 |
| `generate_brief` | 生成 AI 早报 |
| `execute_package` | 执行指定 YAML 采集包 |
| `record_feedback` | 记录用户偏好 |

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

生成 AI 早报。优先使用 Redis 缓存，无缓存时采集 → LLM 合成。

### 参数

无。

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

执行指定路径的 YAML 采集包。

### 参数

| 参数 | 类型 | 必选 | 默认值 | 说明 |
|------|------|------|--------|------|
| `package_path` | string | 是 | — | YAML 采集包文件路径 |

### 请求示例

```json
{
  "name": "execute_package",
  "arguments": {
    "package_path": "/opt/linglong-scout/custom-package.yml"
  }
}
```

### 返回示例

```json
{
  "package": "custom-topic",
  "output_length": 2100,
  "output": "# 自定义主题报告\n\n..."
}
```

---

## record_feedback

记录用户对采集结果的偏好，影响后续权重。

### 参数

| 参数 | 类型 | 必选 | 默认值 | 说明 |
|------|------|------|--------|------|
| `content_hash` | string | 是 | — | 内容哈希标识 |
| `feedback` | string | 是 | — | `"useful"` 或 `"not_interested"` |
| `tags` | string[] | 否 | `null` | 关联标签 |

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
