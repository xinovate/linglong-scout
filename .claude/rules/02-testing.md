---
description: pytest 测试约定、Mock 规则、覆盖要求
globs:
  - "**/tests/**/*.py"
  - "**/test_*.py"
---

# 测试约定

## 框架与运行

- 框架：`pytest`
- 全量：`.venv/bin/pytest`
- 指定模块：`.venv/bin/pytest tests/<module>/ -v`
- 单个测试：`.venv/bin/pytest tests/<module>/test_x.py::test_name -v`
- 覆盖率：`.venv/bin/pytest --cov=<package> --cov-report=term-missing`

## 文件与命名

- 测试文件：`tests/<模块>/test_<组件>.py`
- 测试函数：`def test_<行为描述>()` —— 描述预期行为，不描述实现
- 命名表达意图：`test_rejects_invalid_token` 而非 `test_auth_3`

## 覆盖要求

- 每个公共方法至少一个测试
- 关键路径必须有多个测试覆盖正常 + 边界
- 抽象基类可不直接测，测具体子类
- 优先保证关键路径覆盖率，纯数据转换可酌情降低

## Mock 规则

- **禁止调用真实外部服务**：不联网 LLM/RSS/DB API
- **在 HTTP 层或适配器边界 mock**，不 mock 内部业务函数
- 需要时用 `pytest.fixture` 共享测试数据和 mock
- 异步用 `unittest.mock.AsyncMock`，模块级对象用 `unittest.mock.patch`
- Mock 范围最小化：只 mock 调用链上必要的一层

```python
# 好：mock HTTP 层
@patch("httpx.AsyncClient.get")
async def test_fetch(mock_get):
    mock_get.return_value = MagicMock(json=lambda: {...})

# 坏：mock 内部业务函数
@patch("myapp.agent.build_prompt")
async def test_fetch(mock_prompt):
    ...
```

- Mock 用完即清：用 `patch` context manager 或 fixture 自动清理
- 验证调用参数用 `mock.assert_called_once_with()`，不手动检查 `call_args`

## 异步测试

- pytest-asyncio，`asyncio_mode = "auto"`
- 测试函数直接 `async def test_xxx()`，无需额外装饰器

## 不测什么

- 第三方库行为（"feedparser 能不能用"）
- 无逻辑的 getter/setter
- 抽象基类方法（测具体子类）

## Golden Fixture（推荐用于脆弱解析器）

涉及正则解析外部 HTML/Markdown/JSON 的解析函数，**必须有 golden fixture 测试**（用捕获的真实样本作为输入），否则上游格式一变就静默返空。
