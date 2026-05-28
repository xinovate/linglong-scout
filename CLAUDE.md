# CLAUDE.md — Linglong Scout 项目协作指南

## 项目定位

Linglong Scout 是**信息采集 Agent**，负责搜索、RSS 抓取、LLM 摘要生成。

```
SearXNG/RSS → Scout（采集+摘要）→ 返回给对话 → 用户决定是否写入知识库
```

## 架构规则

- Scout **不写知识库** — 采集结果返回给对话
- Scout 独立于 linglong-knowledge，零依赖

## 关键配置

- 配置文件：`.linglong-scout.yaml`
- LLM 配置：`config.llm.*`（env: `LL_SCOUT_LLM_*`）
- Ingest 配置：`config.ingest.*`（env: `LL_INGEST_*`）

## 文档

- [模块说明 + MCP 接入](docs/README.md)
- [设计总览](docs/design/00-overview.md) — 子设计索引 + 全局决策 + 架构演进
- [工作日志](journal/README.md)

## 详细规则

- [代码风格](.claude/rules/code-style.md)
- [测试约定](.claude/rules/testing.md)
- [API 设计](.claude/rules/api-design.md)
- [安全要求](.claude/rules/security.md)
- [文档同步](.claude/rules/docs-sync.md)
