# 文档同步

## 何时更新文档

| 代码改动 | 必须更新 |
|---------|---------|
| 新增/删除/修改 MCP 工具 | API 文档 + 工具列表 |
| 新增/修改配置字段 | API 文档 + `.scout.example.yml` |
| ingest 数据源变化 | ingest 文档 + 路线图 |
| 版本级改动 | 版本表 + Next Actions + 路线图 |
| 架构决策变更 | 架构文档 + 路线图 ADR |
| 安全/运维相关 | 运维文档 |

## 提交前文档检查清单

代码变更涉及以下模块时，**必须逐个检查**对应文档，确认内容、流程图、架构图同步：

| 变更范围 | 需检查的文档 |
|---------|-------------|
| agent.py（流程/架构） | `docs/README.md` 架构图 + `docs/design/02-agent-pipeline.md` 流程图 + `docs/design/00-overview.md` 组件表/版本表 |
| 新增模块 | `docs/README.md` 核心组件表 + `docs/design/00-overview.md` 组件表/外部配置表 |
| MCP 工具/接入 | `docs/README.md` 工具表 + `docs/design/06-mcp.md` 工具列表/关键文件 |
| 缓存/存储/Redis | `docs/README.md` 缓存机制 + `docs/design/04-cache.md` |
| 配置字段 | `docs/README.md` 配置段 + `.scout.example.yml` + `docs/design/00-overview.md` 外部配置表 |
| CLI 命令 | `docs/README.md` 调用方式 + `docs/design/06-mcp.md` CLI 命令段 |

检查要点：
1. **组件表** — 新增/删除的模块是否在 `docs/README.md` 和 `00-overview.md` 的组件表中同步
2. **流程图** — 数据流是否反映当前代码实际路径（如 collect → store_raw → _generate）
3. **架构图** — 模块间关系是否正确（如新增 raw_store 后的冷热分层）
4. **版本表** — `00-overview.md` 架构演进表是否补了新版本
5. **外部配置表** — `00-overview.md` 中列的配置项是否与 `config.py` 一致

## 准确性规则

- MCP 工具表必须列出所有已注册工具，与 `server.py` 中 `_INGEST_TOOLS` 交叉验证
- 配置字段必须与 `config.py` 一致，删除已不存在的字段
- 架构描述必须反映代码实际行为，未实现功能用 `// 计划中` 标注

## 架构图要求

架构文档应包含：
- 模块依赖图（哪个模块导入哪个）
- 数据流图：SearXNG/RSS → Scout → 对话
- MCP 路由图：远程（ingest）vs 本地（ingest）
- 部署架构：Cloudflare Tunnel → MCP Server → SearXNG/RSS/LLM

图用 Mermaid 代码块或 ASCII art，必须与代码保持同步。

## CLAUDE.md 定位

`CLAUDE.md` 是入口路由文件，控制在 150 行以内。详细规则在 `.claude/rules/` 中。

## 文档写作规范

- 文档语言：项目文档中文为主，技术术语保留英文
- 每个文档文件开头有简短的一句话说明文档用途
- 表格优先于列表展示结构化信息（配置字段、工具列表、版本历史）
- 代码示例可运行、可复制，不写伪代码
- 文档中的路径使用项目相对路径（`src/linglong/...`），不用绝对路径
