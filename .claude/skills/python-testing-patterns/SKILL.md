---
name: python-testing-patterns
description: pytest 用法模式参考 — 测试结构、参数化、Fixture、异步测试、异常测试、测试隔离。编写 linglong-scout 测试代码时激活。
---

# pytest 模式参考

本 skill 提供 pytest 用法参考。项目硬约束见 `.claude/rules/testing.md`。

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

- 每个测试只验证一个行为
- Assert 消息：`assert x == y` 不需要消息，不明显时 `assert result is not None, "search should return results"`

## 参数化测试

同一逻辑多组输入输出时，用 `@pytest.mark.parametrize` 消除重复：

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

- 参数名保持简短，`ids` 参数用描述性标签提高可读性
- 参数组合爆炸时用 `pytest.param` 标记 `pytest.mark.xfail` 或 `pytest.mark.skip`

## Fixture

### 作用域选择

- `scope="function"`（默认）：每个测试独立，适用于有副作用的 fixture（写数据库）
- `scope="module"`：同一模块共享，适用于只读的昂贵资源
- `scope="session"`：整个测试会话共享，仅用于真正昂贵的初始化（如启动 mock server）

### 命名与依赖

- fixture 命名表达内容：`mock_llm_client`、`sample_rss_feed`
- 依赖其他 fixture 通过参数声明依赖链
- 用 `yield` 实现清理逻辑（teardown）

### 示例

```python
@pytest.fixture
def mock_httpx_response():
    """Mock httpx 响应。"""
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"entries": [...]}
    return response

@pytest.fixture
def sample_rss_feed():
    """共享 RSS 测试数据。"""
    return {
        "title": "Test Feed",
        "entries": [
            {"title": "Item 1", "link": "https://example.com/1"},
            {"title": "Item 2", "link": "https://example.com/2"},
        ]
    }
```

## 异步测试

- 异步测试函数用 `async def test_...()` + `pytest-asyncio`
- 在 `pyproject.toml` 中设置 `asyncio_mode = "auto"` 或用 `@pytest.mark.asyncio`
- 异步 fixture 用 `@pytest_asyncio.fixture`
- 不手动 `asyncio.run()`，让 pytest-asyncio 管理事件循环

```python
@pytest.mark.asyncio
async def test_fetch_rss(mock_httpx):
    result = await fetch_rss("https://example.com/feed.xml")
    assert len(result["entries"]) > 0
```

## 异常测试

用 `pytest.raises()` 验证异常类型和消息：

```python
def test_rejects_empty_query(store):
    with pytest.raises(ValueError, match="query must not be empty"):
        store.search_hybrid("")
```

- 不用 `try/except + assert False` 模式
- 验证异常消息时用 `match=` 正则，不检查完整字符串

## 测试隔离

- 每个测试必须独立运行，不依赖执行顺序
- 临时文件用 `tmp_path` fixture（pytest 内建），不手动 `/tmp/test_xxx`
- 数据库测试每个测试用独立路径，不共享文件
- 环境变量修改后必须还原（用 `monkeypatch` fixture）

```python
def test_reads_config_from_env(monkeypatch):
    monkeypatch.setenv("LL_MCP_PORT", "8888")
    config = get_config()
    assert config.mcp.port == 8888
```

## 组件分组

测试用例多时，用 class 分组：

```python
class TestFetchRss:
    def test_returns_parsed_items(self, mock_feed):
        ...

    def test_returns_empty_for_no_items(self, empty_feed):
        ...
```

- 类名：`Test<组件名>`，不用 `Test` 前缀的类 pytest 不收集
