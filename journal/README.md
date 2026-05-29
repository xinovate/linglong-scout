# 工作日志

> **定位**：按天记录工作过程中的问题调查、决策和发现。
> **不记录**：阶段方向（去设计文档）、设计决策（去 `docs/ingest/design/`）。
> **结构**：概览 → 问题/任务 → 结论 → 关联链接。
> **更新时机**：当天工作结束或会话压缩前。

| 日期 | 主题 | 关键结论 |
|------|------|----------|
| 2026-05-29 | 多用户隔离 + CI/CD + 服务器部署 + 代理修复 + Hook 体系 | token 规范 ll-scout:{user}:{18位id}；FeedbackStore 按用户隔离；GitHub Actions 自动部署；Clash GitHub-only 代理；SessionStart/push hook |
| 2026-05-28 | 项目独立化：命名统一 + Docker + 配置重构 + 文档同步 | 10 commits；ingest→scout 全面重命名；.scout.yml；Docker 镜像 309MB；doc-check hook |
| 2026-05-26 | v2.4–v2.6 Agent 接入 + 并发优化 + 缓存 + MCP 远程部署 | Claude Code MCP 连通；数据采集 57s→7.6s；日内缓存；HTTP+Token 认证 |
| 2026-05-25 | v2.2 ingest 增强 + 安全加固 + MCP 工具增强 | 融资快照；API Key 三服务加固；generate_brief/search_web MCP |
| 2026-05-23 | v1.3 信源增强 + 动态标签 + 反馈闭环 | ArXiv/GitHub 适配器；auto_tag；FeedbackStore；search_queries 替换 dimensions |
| 2026-05-22 | v1.2 早报能力（SearXNG + AIHOT + LLM + 晨报） | 端到端通过；英文关键词效果远好于中文；多源聚合架构 |
