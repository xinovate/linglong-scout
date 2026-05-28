# API 与 MCP 工具设计

## MCP 工具注册

- 工具按模块组织：`ingest`（仅采集相关工具）
- 每个模块独立 FastMCP 实例，专属 HTTP 路径（`/mcp/ingest`）
- 远程部署暴露 `ingest`，本地 stdio 同样暴露 `ingest`
- 工具函数名必须描述性强、动词开头：`generate_brief`、`search_web`、`fetch_rss`
- 工具名用 `snake_case`，禁止模块前缀（`ingest_search` → `search_web`），路由已隐含模块

## 工具函数模板

```python
@mcp_tool
async def tool_name(param: str) -> dict:
    """一句话描述工具功能。

    描述规则：
    - 用第三人称现在时（"Searches web for..."）
    - 说明输入是什么、输出是什么
    - 不写实现细节
    """
    try:
        # 领域逻辑
        return {"status": "ok", ...}
    except ValueError as exc:
        return {"error": f"Invalid input: {exc}"}
    except LookupError as exc:
        return {"error": f"Not found: {exc}"}
    except Exception as exc:
        logger.exception("tool_name failed")
        return {"error": str(exc)}
```

- 返回类型：`dict`（JSON 可序列化）
- 显式捕获领域异常，`Exception` 仅作兜底并配合 `logger.exception()`
- 禁止向客户端暴露内部堆栈

## 工具参数设计

- 参数用类型注解，MCP 自动生成 schema
- 必选参数在前，可选参数在后（带默认值）
- 枚举值用 `Literal` 类型：

```python
async def search_web(
    query: str,
    max_results: int = 10,
) -> dict:
```

- 避免过多参数（>6 个时考虑接收一个 JSON 对象）
- 参数校验在函数入口处尽早失败，返回明确错误信息

## 工具描述规范

- docstring 第一行是简短描述（一句话，MCP 客户端显示用）
- 后续行补充使用场景和注意事项
- 描述要面向 Agent 消费者：说明何时调用此工具，而非如何实现

```
好的描述：Searches the web via SearXNG and returns ranked results.
坏的描述：A tool that uses the search module to query SearXNG.
```

## 错误响应格式

```json
{"error": "人类可读的错误信息"}
```

- 不自创错误码，HTTP 状态码 + 错误信息足够
- 错误信息用英文，面向开发者可读
- 验证错误列出具体字段：`{"error": "Invalid input: query must not be empty"}`
- 外部服务故障不暴露内部 URL 或堆栈

## 幂等性

- 查询类工具天然幂等（`search_web`、`fetch_rss`）
- 写入类工具（`record_feedback`）应容忍重复调用
- 批量操作部分失败时返回成功和失败的明细，不静默丢弃

## 配置字段

- Python 中用 `snake_case`，YAML 中用 `snake_case`
- 环境变量覆盖：`LL_<节>_<字段>`（如 `LL_MCP_AUTH_TOKEN`）
- 新增配置字段必须同步到配置文档
- 配置字段和环境变量不重复 — 只用一种机制
- 敏感配置（Token、API Key）只从环境变量或 Redis 读取，不进 YAML

## 新增工具 Checklist

1. 在 `src/linglong_scout/<模块>/` 实现工具函数
2. 在 `src/linglong_scout/mcp/server.py` 的 `_INGEST_TOOLS` 中注册
3. 编写单元测试：正常路径 + 至少一个错误路径
4. 更新 MCP 工具表（名称、描述、参数、返回格式）
5. 确认测试通过

## 工具与内部模块边界

- 工具函数是薄适配层：参数校验 → 调用领域模块 → 格式化返回
- 业务逻辑放在领域模块（`ingest/agent.py`），工具函数不直接实现逻辑
- 工具函数可以组合多个领域模块调用（如 `generate_brief` = search + summarize）
- 领域模块的异常由工具函数统一捕获转换为 JSON 错误响应
