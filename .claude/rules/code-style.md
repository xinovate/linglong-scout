# 代码风格

基线：PEP 8 + Google Python Style Guide。以下为项目特化规则。

## 注释

- **语言**：统一英文，禁止中文注释
- **策略**：默认不写注释，只在 WHY 不显而易见时写一行
- **不写什么**：代码做了什么（标识符自解释）
- **写什么**：隐藏约束、微妙不变量、特定 bug 的 workaround、会令读者意外的行为
- **禁止 TODO/FIXME**：用 issue 或 journal 记录

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

- 模块 docstring 放在文件顶部（导入之前），简述模块职责
- 类 docstring 描述类的用途，`__init__` 只在初始化参数需要额外说明时才写

## 命名

- 函数、方法、变量：`snake_case`
- 类：`PascalCase`
- 常量：`UPPER_SNAKE_CASE`
- 模块级私有辅助函数：`_` 前缀
- 布尔变量/函数：使用 `is_`、`has_`、`should_` 前缀
- 避免单字母变量（循环计数器 `i` 除外），变量名应传达意图
- 避免与内置函数/类型同名（如 `id`、`type`、`list`、`dict`、`input`）
- 缩写保持一致：`cfg`、`url`、`db` 全项目统一，不混用全称和缩写

## 类型注解

- 所有公共函数和方法必须标注参数类型和返回类型
- `__init__` 必须标注 `-> None`
- 使用现代联合语法：`str | None`，不用 `Optional[str]`
- 复杂类型表达式的文件顶部加 `from __future__ import annotations`
- 容器类型用泛型语法：`list[str]`，不用 `List[str]`（除非需兼容 3.9 以下）
- 回调类型用 `Callable[[int, str], bool]` 或 `Protocol`

## 导入

- 顺序：标准库 → 第三方库 → 本项目模块（`linglong.*`）
- 每组之间空一行
- 禁止通配符导入（`from module import *`）
- 禁止相对导入（`from .. import x`），用完整包路径
- 日志统一用 `logging.getLogger(__name__)`，禁止 `print()`（`cli.py` 豁免）

## 错误处理

按语义分层，让调用方能区分不同失败模式：

| 异常类型 | 使用场景 |
|---------|---------|
| `ValueError` | 调用方传入无效参数 |
| `LookupError` | 实体/资源未找到 |
| `RuntimeError` | 外部服务故障（LLM、SearXNG、RSS） |
| `Exception` | 批处理兜底（需 `noqa: BLE001`） |

- MCP 工具函数：捕获领域异常，返回结构化错误 JSON，不让原始异常泄露给客户端
- 外部依赖（网络调用、文件 I/O）：必须 try/except，单个来源失败不能中断整批
- 自定义异常类放在各模块的 `exceptions.py` 中，继承内建异常
- raise 语句附带描述性错误信息，不裸 `raise ValueError()`
- re-raise 时用 `raise ... from exc` 保留因果链

## 同步/异步边界

- IO 密集操作（HTTP 调用、embedding 生成）：用 `async` + `httpx.AsyncClient`
- CPU 密集或 SQLite 操作：用同步代码
- 同一层次不要混用 `requests`（同步）和 `httpx`（异步）
- `EmbeddingGenerator` 应从同步 `requests` 迁移到异步 `httpx`
- 异步函数命名不加 `async_` 前缀，调用方看到 `await` 就知道是异步

## SQL

- 所有用户输入必须用参数化查询（`?` 占位符），禁止拼接用户数据到 SQL
- 动态 WHERE 子句：只从硬编码列名构建，不用用户输入
- PRAGMA 用 f-string 可接受（值来自已验证的配置）

## 格式

- 行宽上限 88 字符（black 默认），括号内换行自然对齐
- 缩进：4 空格，禁止 Tab
- 类之间空 2 行，方法之间空 1 行，函数内逻辑段落空 1 行
- 尾随空格禁止，文件末尾保留一个空行
- 字符串：统一 f-string，禁止 `+` 拼接和 `%` 格式化（日志除外）
- 字符串多行用 `"""` 或括号隐式续行，不用 `\`

## 函数设计

- 目标：单文件 300 行以内，超过 400 行时考虑按职责拆分
- 函数只做一件事。如果需要注释分隔段落，说明应该拆成独立函数
- 函数体目标 40 行以内，超过时考虑拆分子函数
- 参数不超过 5 个，超过时用 `dataclass` 或 `TypedDict` 封装
- 禁止可变默认参数：`def foo(items=[])` → `def foo(items=None)`
- 返回类型统一，不要有时返回 `None` 有时返回 `str`

## 列表推导与 lambda

- 列表推导简单时可读性更好，超过 1 个 for + 1 个 if 时改用普通循环
- 禁止嵌套列表推导
- lambda 仅用于 `key=` 等单行场景，复杂逻辑用 `def`
- 用 `any()` / `all()` 替代手动循环检查布尔条件

## 属性与布尔判断

- 简单的取值/赋值用属性（`@property`），有副作用的用方法
- 布尔判断用隐式真假：`if items:` 而非 `if len(items) > 0:`
- 判断 None 用 `is None` / `is not None`，不用 `==`
- 判断空容器用 `if not items:`，不用 `if items == []`

## 资源管理

- 文件、网络连接、数据库连接用 `with` 语句确保释放
- `httpx.AsyncClient` 在应用生命周期内复用，不在每次请求新建
- 使用 `contextlib.closing()` 包装不支持 `with` 的资源

## 日志

- 格式：`logging.getLogger(__name__)`
- 级别：DEBUG（调试细节）、INFO（正常流程关键节点）、WARNING（可恢复异常）、ERROR（需要关注的失败）
- 日志消息用 `%s` 占位符，不用 f-string（避免不必要的字符串构造）

```python
logger.info("Processed %d entities from %s", len(entities), source)
logger.error("Failed to fetch %s: %s", url, exc)
```

- 禁止在日志中记录敏感信息（API Key、Token、密码）
- 异常路径用 `logger.exception()` 自动附带堆栈

## main 模式

- CLI 入口用 `if __name__ == "__main__":` 保护
- 复杂命令行逻辑拆分到 `cli.py`，`__main__.py` 只做入口转发
