# Ingest 设计总览

> 创建日期：2026-05-25 | 最后更新：2026-05-28 | 状态：已实现

---

## 定位

**ingest 是用户的信息采集助手。**

采集结果交给用户阅读和思考，有价值的内容在讨论中沉淀进知识库。ingest 不是知识库的数据入口——知识库的入口是"人的思考"。

```
数据源 → ingest（采集+精选+去重+LLM 编排）→ 定制化早报 → 用户阅读思考 → 讨论 → 沉淀 → 知识库
```

ingest 负责从采集到格式化输出的完整链路。推送和调度由调用方处理。

---

## 子设计索引

| 编号 | 文档 | 分类 | 状态 | 依赖 | 最后更新 |
|------|------|------|------|------|----------|
| D-01 | [数据源架构](01-data-sources.md) | 数据层 | ✅ 已实现 | — | 2026-05-26 |
| D-02 | [Agent 流水线](02-agent-pipeline.md) | 核心流程 | ✅ 已实现 | D-01 | 2026-05-26 |
| D-03 | [去重机制](03-dedup.md) | 质量层 | ✅ 已实现 | D-02 | 2026-05-26 |
| D-04 | [缓存与调度](04-cache.md) | 运维层 | ✅ 已实现 | D-02 | 2026-05-26 |
| D-05 | [Prompt 设计](05-prompt.md) | 内容层 | ✅ 已实现 | D-02 | 2026-05-26 |
| D-06 | [MCP 接入](06-mcp.md) | 接入层 | ✅ 已实现 | D-02 | 2026-05-28 |

---

## 全局设计决策

| 编号 | 决策 | 选择 | 原因 | 替代方案 |
|------|------|------|------|----------|
| GD-01 | LLM 调用模式 | 单次 Agent prompt | v1.x 流水线 JSON 解析频繁失败 | 多次 LLM 调用流水线 |
| GD-02 | 搜索后端 | 自建 SearXNG | 完全控制搜索结果和隐私 | Google API / Bing API |
| GD-03 | GitHub Trending | 三级 fallback | 单源不可靠 | 单一数据源 |
| GD-04 | 并发策略 | asyncio.gather + Semaphore | 数据采集 57s → 7.6s | 串行拉取 |
| GD-05 | 缓存机制 | 文件级日内缓存 | 0.2ms vs 83s，避免重复 LLM 调用 | 无缓存 / Redis |
| GD-06 | 去重方式 | URL 级 + BriefHistory 语义级 | 双层去重，LLM 判断重复 | 纯 URL 去重 |
| GD-07 | MCP 部署 | 双模式：stdio + streamable-http | 本地开发 + 远程部署 | 仅 stdio |

---

## 核心设计原则

### 1. ingest 不写知识库

采集结果返回给调用方，写入由人决定。未经思考的原始数据直接入库只是堆积。

### 2. LLM Agent 驱动

预搜索后单次 LLM prompt 直接输出 markdown（v2.0+），避免流水线 JSON 解析问题。

### 3. 并发优先

三路数据源（SearXNG / GitHub / RSS）并发拉取，内部 Semaphore 限流保护上游服务。

### 4. 可外部化配置

所有数据源、关键词、去重窗口、缓存策略通过 `.linglong-scout.yaml` 管理，无需改代码。

---

## 架构演进

| 版本 | 主题 | 关键变更 |
|------|------|---------|
| v1.x | 流水线模式 | 多次 LLM 调用 → JSON 解析瓶颈 |
| v2.0 | Agent 重构 | 单次 LLM prompt + BriefHistory 去重 |
| v2.1 | RSS 接入 | 6 个 RSS 源 + 交叉去重 |
| v2.2 | 增强 | 融资快照 + 健康监控 + LLM 容错 |
| v2.3 | 安全加固 | API Key 认证 + MCP 工具 |
| v2.4 | Agent 接入 | Claude Code 连通 + 配置外部化 |
| v2.5 | 性能优化 | 三路并发 + 日内缓存 + Prompt 强化 |
| v2.6 | 远程部署 | HTTP 传输 + Token 认证 |
| v2.7 | 独立项目 | 从 linglong-knowledge 拆分为 linglong-scout |

---

## 明确放弃的方案

| 方案 | 放弃原因 | 替代方案 |
|------|----------|----------|
| 多次 LLM 调用流水线 | JSON 解析频繁失败 | 单次 Agent prompt |
| 串行数据拉取 | 56 次查询串行 ~57s | asyncio.gather 并发 7.6s |
| company_snapshot 内嵌代码包 | 不灵活，改了要重新部署 | 外部化到 ~/linglong/ |
| MCP 仅 stdio 模式 | 无法远程部署 | 双模式 stdio + streamable-http |

---

## 信息维度（5 维度）

| # | 维度 | 典型内容 | 数据源 |
|---|------|---------|--------|
| 1 | 关键人物 | 观点/言论/人事变动 | SearXNG + RSS |
| 2 | 公司动态 | 产品发布、融资、股价、估值 | SearXNG + RSS |
| 3 | 政策动态 | AI 监管、产业政策 | SearXNG + RSS |
| 4 | 开源趋势 | AI 新项目 Stars 增长 | OpenGithubs（日/周/月三段） |
| 5 | 应用落地 | 模型/Agent/机器人产品更新 | SearXNG + RSS |

---

## 组件列表

| 组件 | 路径 | 说明 |
|------|------|------|
| `IngestAgent` | `src/linglong_scout/ingest/agent.py` | LLM Agent：预搜索 + 单 prompt → markdown |
| `BriefHistory` | `src/linglong_scout/ingest/brief_history.py` | 按维度跨天去重 + 重叠检测 + fallback |
| `SourcePackage` | `src/linglong_scout/ingest/package.py` | 采集包定义模型 |
| `FeedbackStore` | `src/linglong_scout/ingest/feedback.py` | 用户偏好存储 + 权重计算 |
| `morning_brief.md` | `src/linglong_scout/ingest/prompts/morning_brief.md` | 早报 prompt 模板 |

---

## 外部配置

所有配置通过 `.linglong-scout.yaml` 管理：

| 配置 | 路径 | 说明 |
|------|------|------|
| RSS 源 | `ingest.rss_sources` | 11 个订阅源 |
| 搜索关键词 | `ingest.packages[].search_queries` | 56 个关键词 |
| 去重窗口 | `ingest.dedup_windows` | 各维度回看天数 |
| 缓存 | `ingest.brief_output_dir` / `brief_cache_days` | 日内缓存目录和保留天数 |
| LLM | `llm.model` / `llm.base_url` | glm-5.1 + Anthropic 端点 |
| MCP | `mcp.transport` / `mcp.auth_token` | 传输方式 + 认证 |

---

## 实现路线

| 阶段 | 内容 | 状态 |
|------|------|------|
| Phase 1–8 | 架构清理→SearXNG→模板→多源→LLM 标签→反馈 | ✅ v1.x |
| Phase 9 | IngestAgent 重构（LLM Agent 单 prompt） | ✅ v2.0 |
| Phase 10 | BriefHistory 维度去重 + GitHub Trending 多源 | ✅ v2.0 |
| Phase 11 | RSS 订阅源接入 + 交叉去重 | ✅ v2.1 |
| Phase 12 | 公司融资快照 + 更多 RSS 源 + 健康监控 + 容错 | ✅ v2.2 |
| Phase 13 | API Key 认证 + MCP 工具 + Claude Code 接入 | ✅ v2.4 |
| Phase 14 | 配置外部化 + LLM 对齐 + company_snapshot 外部化 | ✅ v2.4 |
| Phase 15 | 三路并发拉取 + 日内缓存 + 时段标记 + Prompt 强化 | ✅ v2.5 |
| Phase 16 | HTTP 传输 + Token 认证 | ✅ v2.6 |
| Phase 17 | 从 linglong-knowledge 拆分为独立项目 | ✅ v2.7 |

---

## 参考

- [Ingest README](../README.md) — 模块使用说明 + MCP 接入示例
