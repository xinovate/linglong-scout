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
- 组件测试用例多时，用 class 分组：

```python
class TestSearchWeb:
    def test_returns_matching_results(self, mock_searxng):
        ...

    def test_returns_empty_for_no_match(self, empty_results):
        ...
```

- 测试类名：`Test<组件名>`，不用 `Test` 前缀的类 pytest 不收集
- 测试文件和测试函数名应表达意图：`test_rejects_invalid_token` 而非 `test_auth_3`

## 覆盖要求

- **每个公共方法**至少一个测试
- **关键路径**（MCP 工具依赖）必须有多个测试覆盖正常 + 边界：
  - `IngestAgent.generate_brief()` — 必测 LLM 失败、空结果、部分数据
  - MCP 工具函数（`search_web`、`fetch_rss` 等）— 必测外部服务故障
- 只有抽象基类可以无直接测试，其他都必须覆盖
- 优先保证关键路径的覆盖率，非关键路径的纯数据转换可酌情降低

## Mock 规则

- **禁止调用真实外部服务**：不联网 SearXNG、LLM API、RSS、GitHub
- 在 HTTP 层（`httpx`/`requests`）或适配器边界 mock
- 不 mock 内部模块。如果需要 mock 内部函数，说明测试层次可能不对
- 共享测试数据和 mock 用 `pytest.fixture`
- Mock 对象用 `unittest.mock.AsyncMock` 替代异步函数，`unittest.mock.patch` 替代模块级对象
- Mock 范围最小化：只 mock 调用链上必要的一层，不要层层 mock

```python
# 好：mock HTTP 层
@patch("httpx.AsyncClient.get")
async def test_search_web(mock_get):
    mock_get.return_value = MagicMock(json=lambda: {"results": [...]})

# 坏：mock 内部业务函数
@patch("linglong.scout.agent.IngestAgent._build_prompt")
async def test_search_web(mock_prompt):
    ...
```

- Mock 使用后必须清理：用 `patch` 的 context manager 或 fixture 的自动清理
- 验证 mock 调用参数用 `mock.assert_called_once_with()`，不要手动检查 `call_args`

## 测试结构

遵循 Arrange → Act → Assert：

```python
def test_search_returns_matching_results(store_with_data):
    # Arrange — fixture 处理
    # Act
    results = store_with_data.search_hybrid("machine learning")
    # Assert
    assert len(results) > 0
    assert all(r.confidence >= 0.5 for r in results)
```

- 每个测试只验证一个行为，不要在一个测试中验证多个不相关的行为
- Assert 消息：`assert x == y` 不需要消息，`assert result is not None, "search should return results"` 只在不明显时加

## 参数化测试

- 同一逻辑多组输入输出时，用 `@pytest.mark.parametrize` 消除重复：

```python
@pytest.mark.parametrize("query,expected_count", [
    ("machine learning", 3),
    ("nonexistent topic", 0),
    ("", 0),
])
def test_search_with_various_queries(store_with_data, query, expected_count):
    results = store_with_data.search_hybrid(query)
    assert len(results) == expected_count
```

- 参数名保持简短，`ids` 参数用中文或描述性标签提高可读性
- 参数组合爆炸时用 `pytest.param` 标记 `pytest.mark.xfail` 或 `pytest.mark.skip`

## Fixture

- 共享的测试数据、mock 对象、临时数据库用 fixture
- 作用域选择：
  - `scope="function"`（默认）：每个测试独立，适用于有副作用的 fixture（写数据库）
  - `scope="module"`：同一模块共享，适用于只读的昂贵资源
  - `scope="session"`：整个测试会话共享，仅用于真正昂贵的初始化（如启动 mock server）
- fixture 命名表达内容：`mock_llm_client`、`sample_rss_feed`
- 依赖其他 fixture 的 fixture 通过参数声明依赖链
- 用 `yield` 实现清理逻辑（teardown）

## 异步测试

- 异步测试函数用 `async def test_...()` + `pytest-asyncio`
- 在 `pyproject.toml` 中设置 `asyncio_mode = "auto"` 或用 `@pytest.mark.asyncio`
- 异步 fixture 用 `@pytest_asyncio.fixture`
- 不手动 `asyncio.run()`，让 pytest-asyncio 管理事件循环

## 异常测试

- 测试异常用 `pytest.raises()`，验证异常类型和消息：

```python
def test_rejects_empty_query(store):
    with pytest.raises(ValueError, match="query must not be empty"):
        store.search_hybrid("")
```

- 不要用 `try/except + assert False` 的模式
- 验证异常消息时用 `match=` 正则，不检查完整字符串

## 不测什么

- 第三方库行为（如 "feedparser 能不能用"）
- 无逻辑的 getter/setter
- 抽象基类方法（测具体子类）

## 测试隔离

- 每个测试必须独立运行，不依赖执行顺序
- 临时文件用 `tmp_path` fixture（pytest 内建），不用手动 `/tmp/test_xxx`
- 数据库测试每个测试用独立路径，不共享文件
- 环境变量修改后必须还原（用 `monkeypatch` fixture）

```python
def test_reads_config_from_env(monkeypatch):
    monkeypatch.setenv("LL_MCP_PORT", "8888")
    config = get_config()
    assert config.mcp.port == 8888
```
