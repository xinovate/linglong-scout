# D-06 MCP 接入

> 状态：✅ 已实现 | 最后更新：2026-05-28 | 依赖：[D-02 Agent 流水线](02-agent-pipeline.md)

---

## 概述

ingest 通过 MCP Server 暴露工具，支持本地（stdio）和远程（streamable-http）两种接入方式。

---

## 启动流程图

```mermaid
flowchart TD
    START(["python -m linglong_scout.mcp"]) --> CONFIG["get_config()"]
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

## 工具列表（5 个）

| 工具 | 说明 |
|------|------|
| `generate_brief()` | 生成当天 AI 早报（有缓存） |
| `execute_package(path)` | 执行指定 YAML 采集包 |
| `fetch_rss(url)` | 采集单个 RSS feed |
| `search_web(query)` | SearXNG 搜索 |
| `record_feedback(hash, feedback)` | 记录用户偏好 |

---

## 双模式部署架构

```mermaid
graph LR
    subgraph 本地["stdio 模式（本地）"]
        CC["Claude Code"] -->|子进程| MCP1["linglong_scout.mcp<br/>stdio 管道"]
        OC["OpenClaw"] -->|子进程| MCP1
    end

    subgraph 远程["streamable-http 模式（服务器）"]
        OC2["OpenClaw"] -->|HTTP + Bearer Token| NGINX["Nginx (可选)"]
        NGINX --> MCP2["linglong_scout.mcp :9900<br/>TokenAuthMiddleware"]
        MCP2 --> SEARXNG["SearXNG"]
        MCP2 --> LLM["LLM API"]
    end
```

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
| `src/linglong_scout/mcp/server.py` | FastMCP 工厂 + 工具注册 |
| `src/linglong_scout/mcp/__main__.py` | 按 transport 启动 |
| `src/linglong_scout/mcp/_auth.py` | Token 认证中间件 |
| `src/linglong_scout/mcp/tools.py` | 5 个 MCP 工具实现 |
| `deploy/linglong-scout-mcp.service` | systemd 守护配置 |
