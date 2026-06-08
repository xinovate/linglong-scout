# 工作日志

> **定位**：按天记录工作过程中的问题调查、决策和发现。
> **不记录**：阶段方向（去设计文档）、设计决策（去 `docs/ingest/design/`）。
> **结构**：概览 → 问题/任务 → 结论 → 关联链接。
> **更新时机**：当天工作结束或会话压缩前。

| 日期 | 主题 | 关键结论 |
|------|------|----------|
| 2026-06-08 | SearXNG 完全移除 + 文档清理 | 48 条早报零引用 SearXNG；采集从三路改为两路（RSS+GitHub）；删除 search_web 工具（7→6）；6 规则文件 + 8 文档文件引用清理 |
| 2026-06-05 | 早报 prompt 优化 + OpenClaw MCP 排查 | 开源趋势改为日榜 TOP 8（解决日/周/月混排+数字幻觉）；关键人物/行业要闻增加来源溯源列；OpenClaw MCP 连接失败定位为客户端 streamable-http 支持问题 |
| 2026-06-04 | README 全流程验证 + 维度名统一 + OpenGithubs 修复 + 配置重构 | 临时目录端到端验证；.env.example + SearXNG 默认配置；pydantic extra=ignore；OpenGithubs 列目录+seen 去重（2→8 条）；journal-check 日期 bug；${VAR:-default} 替代 _apply_env_overrides 硬编码映射 |
| 2026-06-03 | v2.14 强制鉴权 + 早报维度合并 + Docker 合并 + README 重构 | HTTP 强制 auth_token + init 命令；早报 6 维度合并为 5（行业要闻+精选限流）；Docker Compose 四合一；移除 search_web（7→6 工具）；超级个体/OPC 关键词 |
| 2026-06-02 | 早报格式重构 + CI deploy 修复 + 服务器配置修复 | 融资独立段+开源双 star 列；CI deploy 三连失败（本地改动/404/401→TCP 检查）；Redis 密码+allowed_hosts 遗漏修复；journal-check 三项检查增强 |
| 2026-06-01 | v2.11 RSS-first 采集策略 + OpenGithubs 修复 | SearXNG 63→20 关键词（仅实体级精准查询）；RSS 11→14 源（+VentureBeat/SyncedReview/EU AI Act）；OpenGithubs 描述解析 bug 修复（re.DOTALL 跨段匹配）；GITHUB_TOKEN 环境变量支持（Docker 无 gh CLI）；总数据 493→~210 条，信噪比大幅提升 |
| 2026-05-29 | 27 项：功能 + 重构 + 安全 + 质量优化 | v2.10；LLM async + prompt 修正；tools 去重；FeedbackStore 单例；scheduler 优雅退出；domain exceptions；hatch-vcs 版本；SSRF 防护(172.16/12)；auth 18 测试；CI 质量门禁；_get_redis 去重；regex bug 修复；schedule 依赖清理；healthcheck TCP；retry 范围缩窄 |
| 2026-05-28 | 项目独立化：命名统一 + Docker + 配置重构 + 文档同步 | 10 commits；ingest→scout 全面重命名；.scout.yml；Docker 镜像 309MB；doc-check hook |
| 2026-05-26 | v2.4–v2.6 Agent 接入 + 并发优化 + 缓存 + MCP 远程部署 | Claude Code MCP 连通；数据采集 57s→7.6s；日内缓存；HTTP+Token 认证 |
| 2026-05-25 | v2.2 ingest 增强 + 安全加固 + MCP 工具增强 | 融资快照；API Key 三服务加固；generate_brief/search_web MCP |
| 2026-05-23 | v1.3 信源增强 + 动态标签 + 反馈闭环 | ArXiv/GitHub 适配器；auto_tag；FeedbackStore；search_queries 替换 dimensions |
| 2026-05-22 | v1.2 早报能力（SearXNG + AIHOT + LLM + 晨报） | 端到端通过；英文关键词效果远好于中文；多源聚合架构 |
