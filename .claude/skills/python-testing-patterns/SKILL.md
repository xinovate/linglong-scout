---
name: python-testing-patterns
description: pytest 用法模式参考 — 测试结构、参数化、Fixture、异步测试、异常测试、测试隔离。编写或修改 Python 测试代码时激活。
---

# pytest 测试模式参考

本 skill 提供 pytest 常用模式速查。编写或修改测试时参考对应章节。

## 测试结构

```python
def test_<行为描述>():
    # Arrange
    data = build_fixture()
    # Act
    result = process(data)
    # Assert
    assert result.status == "ok"
```

测试函数描述预期行为，不描述实现。`test_rejects_invalid_token` 而非 `test_auth_3`。

## 参数化

```python
import pytest

@pytest.mark.parametrize("value,expected", [
    ("https://example.com", True),
    ("ftp://evil.com", False),
    ("http://localhost", False),
])
def test_url_validation(value, expected):
    assert is_safe_url(value) is expected
```

## Fixture

```python
@pytest.fixture
def sample_feed():
    return {"title": "test", "entries": [...]}

def test_parse(sample_feed):
    result = parse(sample_feed)
    assert len(result) == 1

# scope 控制生命周期
@pytest.fixture(scope="module")
def expensive_resource():
    return build_once()

# autouse 自动应用
@pytest.fixture(autouse=True)
def reset_state():
    yield
    cleanup()
```

## 异步测试

```python
# pyproject.toml: [tool.pytest.ini_options] asyncio_mode = "auto"
async def test_async_fetch():
    result = await fetch(url)
    assert result is not None
```

无需装饰器，`asyncio_mode = "auto"` 自动处理。

## Mock 模式

```python
from unittest.mock import AsyncMock, MagicMock, patch

# patch 模块级对象
@patch("myapp.fetcher.httpx.AsyncClient.get")
async def test_fetch(mock_get):
    mock_get.return_value = MagicMock(json=lambda: {"entries": []})

# AsyncMock 替代协程
mock_agent.run = AsyncMock(return_value="result")

# 验证调用
mock_get.assert_called_once_with("https://example.com")
mock_get.assert_called_once()  # 不关心参数
```

## 异常测试

```python
def test_invalid_input_raises():
    with pytest.raises(ValueError, match="must not be empty"):
        validate("")

# 测试具体异常类型
def test_not_found_raises():
    with pytest.raises(LookupError):
        lookup("missing")
```

## 测试隔离

- 每个 test 独立，不依赖执行顺序
- 用 fixture autouse 重置全局状态
- 用 tmp_path fixture 处理临时文件（自动清理）

```python
def test_write_file(tmp_path):
    target = tmp_path / "out.json"
    write_to(target)
    assert target.exists()
```

## Mock 在 HTTP 层

```python
# 好：mock HTTP 边界
@patch("httpx.AsyncClient.post")
async def test_llm_call(mock_post):
    mock_post.return_value = MagicMock(
        status_code=200,
        json=lambda: {"choices": [...]},
        raise_for_status=lambda: None,
    )

# 坏：mock 内部业务函数
@patch("myapp.agent.build_prompt")  # 说明测试层次错了
```
