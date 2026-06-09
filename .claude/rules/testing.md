# 测试约定

## 框架与运行

- 框架：`pytest`
- 全量：`.venv/bin/pytest`
- 指定模块：`.venv/bin/pytest tests/ingest/ -v`
- 单个测试：`.venv/bin/pytest tests/ingest/test_agent.py::test_generate_brief -v`
- 覆盖率：`.venv/bin/pytest --cov=linglong --cov-report=term-missing`

## 文件与命名

- 测试文件：`tests/<模块>/test_<组件>.py`
- 测试函数：`def test_<行为描述>()` — 描述预期行为，不描述实现
- 测试文件和测试函数名应表达意图：`test_rejects_invalid_token` 而非 `test_auth_3`

## 覆盖要求

- **每个公共方法**至少一个测试
- **关键路径**（MCP 工具依赖）必须有多个测试覆盖正常 + 边界：
  - `IngestAgent.generate_brief()` — 必测 LLM 失败、空结果、部分数据
  - MCP 工具函数（`fetch_rss`、`fetch_raw` 等）— 必测外部服务故障
- 只有抽象基类可以无直接测试，其他都必须覆盖
- 优先保证关键路径的覆盖率，非关键路径的纯数据转换可酌情降低

## Mock 规则

- **禁止调用真实外部服务**：不联网 LLM API、RSS、GitHub
- 在 HTTP 层（`httpx`/`requests`）或适配器边界 mock
- 不 mock 内部模块。如果需要 mock 内部函数，说明测试层次可能不对
- 共享测试数据和 mock 用 `pytest.fixture`
- Mock 对象用 `unittest.mock.AsyncMock` 替代异步函数，`unittest.mock.patch` 替代模块级对象
- Mock 范围最小化：只 mock 调用链上必要的一层，不要层层 mock

```python
# 好：mock HTTP 层
@patch("httpx.AsyncClient.get")
async def test_fetch_rss(mock_get):
    mock_get.return_value = MagicMock(json=lambda: {"entries": [...]})

# 坏：mock 内部业务函数
@patch("linglong.scout.agent.IngestAgent._build_prompt")
async def test_fetch_rss(mock_prompt):
    ...
```

- Mock 使用后必须清理：用 `patch` 的 context manager 或 fixture 的自动清理
- 验证 mock 调用参数用 `mock.assert_called_once_with()`，不要手动检查 `call_args`

## 不测什么

- 第三方库行为（如 "feedparser 能不能用"）
- 无逻辑的 getter/setter
- 抽象基类方法（测具体子类）

## 参考

pytest 用法模式（参数化、Fixture、异步测试等）见 skill：`python-testing-patterns`
