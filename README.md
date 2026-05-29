# Linglong Scout

AI 信息采集 Agent —— 搜索、RSS 抓取、LLM 摘要生成，输出结构化早报。

## 快速开始

```bash
# 安装
pip install -e .

# 配置
cp .scout.example.yml .scout.yml

# 生成早报
linglong-scout brief

# 仅采集（不调 LLM）
linglong-scout collect

# 启动 MCP 服务（远程部署）
linglong-scout serve
```

## 架构

```
SearXNG / RSS / GitHub Trending → 采集 → Redis 存储 → LLM → Markdown 早报
```

- 7 个 MCP 工具（远程/本地双模式）
- 容器内自调度（每天 06:55 自动采集）
- 多用户偏好隔离
- Docker 一键部署

## MCP 工具

| 工具 | 说明 |
|------|------|
| `generate_brief` | 生成 AI 早报 |
| `search_web` | SearXNG 搜索 |
| `fetch_rss` | RSS feed 采集 |
| `fetch_github_trending` | GitHub 趋势项目 |
| `fetch_raw` | 获取原始采集数据 |
| `execute_package` | 自定义主题采集 |
| `record_feedback` | 记录用户偏好 |

## 文档

完整文档在 [`docs/`](docs/)：

- [模块说明 + MCP 接入](docs/README.md)
- [设计总览](docs/design/00-overview.md)
- [MCP 工具参考](docs/design/07-mcp-tools.md)

## 配置

所有配置通过 `.scout.yml` 管理，敏感值用 `${ENV_VAR}` 引用。详见 [.scout.example.yml](.scout.example.yml)。

## License

MIT
