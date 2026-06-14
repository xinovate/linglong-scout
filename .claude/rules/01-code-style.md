---
description: Python 代码风格、类型注解、命名、格式规约
globs:
  - "**/*.py"
---

# Python 代码风格

基线：PEP 8 + Google Python Style Guide。以下为项目特化规则。

## 注释

- **语言**：统一英文，禁止中文注释
- **策略**：默认不写注释，只在 WHY 不显而易见时写一行
- **不写什么**：代码做了什么（标识符自解释）
- **写什么**：隐藏约束、微妙不变量、特定 bug 的 workaround、会令读者意外的行为
- **禁止 TODO/FIXME**：用 issue 或文档记录

## Docstring

- 公共模块、类、函数写 docstring；私有辅助函数和显而易见的方法不写
- 格式：Google Style，三引号写在 def 下一行

```python
def fetch_feed(url: str, timeout: int = 30) -> dict:
    """Fetch and parse an RSS/Atom feed.

    Args:
        url: Feed URL to fetch.
        timeout: Request timeout in seconds.

    Returns:
        Parsed feed dict with "entries" key.

    Raises:
        RuntimeError: If the request fails or feed cannot be parsed.
    """
```

## 命名

- 函数、方法、变量：`snake_case`
- 类：`PascalCase`
- 常量：`UPPER_SNAKE_CASE`
- 模块级私有辅助函数：`_` 前缀
- 布尔变量/函数：使用 `is_`、`has_`、`should_` 前缀
- 避免与内置函数/类型同名（如 `id`、`type`、`list`、`dict`、`input`）
- 缩写全项目统一：`cfg`/`url`/`db` 不混用全称和缩写

## 类型注解

- 所有公共函数和方法必须标注参数类型和返回类型
- `__init__` 必须标注 `-> None`
- 使用现代联合语法：`str | None`，不用 `Optional[str]`
- 复杂类型表达式的文件顶部加 `from __future__ import annotations`
- 容器类型用泛型语法：`list[str]`，不用 `List[str]`

## 导入

- 顺序：标准库 → 第三方库 → 本项目模块，每组之间空一行
- 禁止通配符导入（`from module import *`）
- 禁止相对导入（`from .. import x`），用完整包路径

## 格式

- 行宽上限 88 字符（black 默认）
- 缩进：4 空格，禁止 Tab
- 类之间空 2 行，方法之间空 1 行
- 字符串统一 f-string，禁止 `+` 拼接和 `%` 格式化（日志除外）
- 字符串多行用 `"""` 或括号隐式续行，不用 `\`

## 函数设计

- 函数只做一件事。需要注释分隔段落 → 应拆成独立函数
- 函数体目标 40 行以内，单文件目标 300 行以内（超 400 考虑拆分）
- 参数不超过 5 个，超过用 `dataclass` 或 `TypedDict` 封装
- 禁止可变默认参数：`def foo(items=[])` → `def foo(items=None)`
- 返回类型统一，不要有时返回 `None` 有时返回 `str`

## 属性与布尔判断

- 简单取值/赋值用 `@property`，有副作用用方法
- 判断 None 用 `is None` / `is not None`
- 空容器用 `if not items:`，不用 `if items == []:`

## ⭐ 异步边界红线（高频盲区）

AI 生成 Python 异步代码时极易踩坑，**这是必须人工审查的强制检查项**：

1. **async 函数内禁止直接调用同步 IO**。所有 `httpx`/`requests`/`redis.Redis`(同步)/文件 IO/`subprocess` 在 `async def` 内必须：
   - 用异步等价物（`httpx.AsyncClient`、`redis.asyncio`），或
   - 包 `await asyncio.to_thread(sync_fn, ...)`，或
   - 包 `await anyio.to_thread.run_sync(...)`
2. **审查方法**：看到 `async def` → 扫描函数体内所有非 `await` 的函数调用 → 逐个确认是否 IO → 是则按上述处理
3. **隐形性提醒**：Python `async def` 语法太顺，同步 IO 调用 IDE 不报错，必须主动审查，不能依赖工具

## ⭐ 连接/客户端生命周期红线（高频盲区）

1. `httpx.AsyncClient`、`redis.Redis`、数据库连接、`aiohttp.ClientSession` **必须 module-level 复用**或通过应用生命周期管理的单例，**禁止在函数体内每次 `new`**
2. 函数内 new = 每次调用都建 TCP+TLS 握手 + 丢弃连接池，是慢泄漏
3. **正确模式**：模块级 lazy 单例 + 应用 shutdown 时 close

```python
# 错：每次调用都建连
def get_redis():
    return redis.from_url(url)

# 对：module-level 单例
_CLIENT = None
def get_redis():
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = redis.from_url(url, decode_responses=True)
    return _CLIENT
```
