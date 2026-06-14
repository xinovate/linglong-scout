---
description: 异常分层、错误可见性、批量容错规约
globs:
  - "**/*.py"
---

# 错误处理

## 异常类型分层

按语义分层，让调用方能区分不同失败模式：

| 异常类型 | 使用场景 |
|---------|---------|
| `ValueError` | 调用方传入无效参数 |
| `LookupError` | 实体/资源未找到 |
| `RuntimeError` | 外部服务故障（LLM、网络、存储） |
| `Exception` | 批处理兜底（需 `noqa: BLE001`） |

- 自定义异常放各模块 `exceptions.py`，继承内建异常
- raise 附带描述性信息，不裸 `raise ValueError()`
- re-raise 用 `raise ... from exc` 保留因果链

## ⭐ 错误可见性红线（高频盲区）

**禁止 bare `except Exception: pass`** —— 系统会变得"健壮但失明"，故障时无法定位。

- `except Exception` 后**必须 log**（至少 `logger.debug`，推荐 `logger.warning`/`logger.exception`）
- 被吞掉的异常必须留下痕迹：来源、错误类型、关键上下文

```python
# 错：故障不可见
try:
    fetch_source(url)
except Exception:
    pass

# 对：留痕
try:
    fetch_source(url)
except Exception as exc:
    logger.warning("source %s fetch failed: %s", url, exc)
```

## 异常处理位置

- **外部依赖**（网络、文件 IO、LLM）：必须 try/except，单个来源失败不能中断整批
- **批处理**：用 `asyncio.gather(..., return_exceptions=True)` 或循环内 try/except，部分失败返回成功/失败明细，不静默丢弃
- **MCP 工具/HTTP handler**：捕获领域异常返回结构化错误，不让原始堆栈泄露给客户端
- **内部函数**：信任调用，不重复 try/except

## 重试

- 区分可重试异常（`TimeoutException`、`HTTPStatusError` 5xx）和不可重试（4xx、`ValueError`）
- 只重试可重试异常，其余直接抛出
- 重试次数和退避策略从配置读取，不硬编码

## 异步路径

- 异常路径用 `logger.exception()` 自动附带堆栈（在 except 块内）
- 异步任务（`asyncio.create_task`）的异常要收集，否则静默丢失 —— 用 `TaskGroup` 或显式 `add_done_callback`

## 不该做的事

- 不要 `except Exception` 后返回一个"看起来正常"的默认值掩盖错误（如返回空列表假装成功）
- 不要在循环里反复 try/except 同一个可预期的校验错误（应在循环外校验）
- 不要捕获 `BaseException`（会吞 `KeyboardInterrupt`/`SystemExit`）
