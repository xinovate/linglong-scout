# D-06 MCP 接入

> 状态：✅ 已实现 | 最后更新：2026-05-28 | 依赖：[D-02 Agent 流水线](02-agent-pipeline.md)

---

## 概述

Linglong Scout 通过 MCP Server 暴露采集工具，同时提供 CLI 命令供 cron 调用。支持本地（stdio）和远程（streamable-http）两种接入方式。

---

## 启动流程图

```mermaid
flowchart TD
    START(["python -m linglong.mcp"]) --> CONFIG["get_config()"]
    CONFIG --> CREATE["create_server()"]
    CREATE --> REGISTER["_INGEST_TOOLS 注册"]
    REGISTER --> TRANSPORT{mcp.transport?}

    TRANSPORT -->|stdio| STDIO["server.run(transport='stdio')<br/>子进程 stdio 管道"]
    TRANSPORT -->|streamable-http| HTTP_CHECK{auth_token?}

    HTTP_CHECK -->|有| HTTP_AUTH["create_http_app()<br/>+ TokenAuthMiddleware<br/>+ uvicorn 监听"]
    HTTP_CHECK -->|无| HTTP_NOAUTH["server.run(transport='streamable-http')<br/>无认证"]

    STDIO --> RUNNING(["服务运行中"])
    HTTP_AUTH --> RUNNING
    HTTP_NOAUTH --> RUNNING

    style STDIO fill:#4CAF50,color:#fff
    style HTTP_AUTH fill:#2196F3,color:#fff
    style HTTP_NOAUTH fill:#FF9800,color:#fff
```

---

## HTTP 请求认证流程

```mermaid
sequenceDiagram
    participant Agent as OpenClaw / Claude Code
    participant Server as MCP Server :9900
    participant Auth as TokenAuthMiddleware
    participant Tool as generate_brief()

    Agent->>Server: POST /mcp<br/>Authorization: Bearer xxx
    Server->>Auth: 校验 Token
    alt Token 有效
        Auth-->>Server: 放行
        Server->>Tool: 执行工具
        Tool-->>Agent: 返回结果
    else Token 无效/缺失
        Auth-->>Agent: 401 Unauthorized
    end
```

---

## 工具列表（6 个）

| 工具 | 说明 |
|------|------|
| `generate_brief()` | 生成 AI 早报：优先从 Redis 读 raw 数据，无则采集 → LLM 合成 |
| `fetch_raw(date, source)` | 获取结构化原始数据（Redis → fallback 文件） |
| `execute_package(path)` | 执行指定 YAML 采集包 |
| `fetch_rss(url)` | 采集单个 RSS feed |
| `search_web(query)` | SearXNG 搜索 |
| `record_feedback(hash, feedback)` | 记录用户偏好 |

---

## 双模式部署架构

```mermaid
graph LR
    subgraph 本地["stdio 模式（本地）"]
        CC["Claude Code"] -->|子进程| MCP1["linglong.mcp<br/>stdio 管道"]
        OC["OpenClaw"] -->|子进程| MCP1
    end

    subgraph 远程["streamable-http 模式（服务器）"]
        OC2["OpenClaw"] -->|HTTP + Bearer Token| NGINX["Nginx (可选)"]
        NGINX --> MCP2["linglong.mcp :9900<br/>TokenAuthMiddleware"]
        MCP2 --> SEARXNG["SearXNG"]
        MCP2 --> LLM["LLM API"]
    end
```

---

## CLI 命令

除了 MCP 工具，还提供 CLI 命令供 cron 和手动调用：

```bash
# 生成早报（供 cron 触发）
linglong-scout brief          # 有缓存则直接返回
linglong-scout brief --force  # 强制重新生成

# 手动运行采集包
linglong-scout scout

# 启动 MCP 服务
linglong-scout serve
```

`brief` 命令的缓存逻辑：检查 Redis `scout:brief:{date}`，命中则直接输出，未命中则完整采集 + LLM 生成后写入 Redis（TTL 25h）。

---

## 日志

CLI 和 MCP 入口统一使用 `setup_logging()`（定义在 `config.py`）：

- RotatingFileHandler：5MB × 3 备份，写入 `~/linglong/logs/scout.log`
- StreamHandler：同时输出到 stderr
- CLI `-v` 参数可切换为 DEBUG 级别

---

## 已知注意事项

- `generate_brief()` 内部用 `_run_async()` (ThreadPoolExecutor) 运行 async 函数，MCP server 有自己的事件循环
- RSSHub `ACCESS_KEY` 仅追加到 `:1200` 端口的 URL
- GitHub API 优先用 `gh auth token` 认证（5000 req/hr）
- MCP 子进程不继承 shell 环境变量，Claude Code 需通过 `env` 字段注入

---

## 关键文件

| 文件 | 说明 |
|------|------|
| `src/linglong/mcp/server.py` | FastMCP 工厂 + 工具注册（6 个） |
| `src/linglong/mcp/__main__.py` | 按 transport 启动，含日志初始化 |
| `src/linglong/mcp/_auth.py` | Token 认证中间件 |
| `src/linglong/mcp/tools.py` | 6 个 MCP 工具实现 |
| `src/linglong/scout/raw_store.py` | 结构化原始数据存储（Redis 热 + JSON 冷） |
| `src/linglong/cli.py` | CLI 入口：brief / collect / scout / serve |
| `src/linglong/config.py` | 配置模型 + `setup_logging()` |
| `deploy/linglong-scout-mcp.service` | systemd 守护配置 |
