---
name: cost-aware-llm-pipeline
description: LLM API 成本控制模式 — 模型路由、预算追踪、重试逻辑、prompt 缓存。处理 linglong-scout LLM 调用相关代码时激活。
---

# LLM 成本控制模式

linglong-scout 调用 LLM 生成摘要。本 skill 提供成本控制参考模式。

## 适用场景

- 添加或修改 LLM 调用逻辑
- 实现摘要生成的成本追踪
- 优化批量处理的 API 开销
- 配置模型选择策略

## 核心模式

### 1. 按复杂度路由模型

简单任务用便宜模型，复杂任务用强模型。

```python
MODEL_HAIKU = "claude-haiku-4-5-20251001"
MODEL_SONNET = "claude-sonnet-4-6"

_SONNET_TEXT_THRESHOLD = 10_000  # 字符数
_SONNET_ITEM_THRESHOLD = 30     # 条目数

def select_model(
    text_length: int,
    item_count: int,
    force_model: str | None = None,
) -> str:
    if force_model is not None:
        return force_model
    if text_length >= _SONNET_TEXT_THRESHOLD or item_count >= _SONNET_ITEM_THRESHOLD:
        return MODEL_SONNET
    return MODEL_HAIKU  # 便宜 3-4 倍
```

### 2. 不可变成本追踪

用 frozen dataclass 追踪累计开销。每次 API 调用返回新的 tracker，不修改原状态。

```python
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class CostRecord:
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float

@dataclass(frozen=True, slots=True)
class CostTracker:
    budget_limit: float = 1.00
    records: tuple[CostRecord, ...] = ()

    def add(self, record: CostRecord) -> "CostTracker":
        return CostTracker(
            budget_limit=self.budget_limit,
            records=(*self.records, record),
        )

    @property
    def total_cost(self) -> float:
        return sum(r.cost_usd for r in self.records)

    @property
    def over_budget(self) -> bool:
        return self.total_cost > self.budget_limit
```

### 3. 窄重试逻辑

只重试瞬态错误（网络、限流、服务器错误）。认证或参数错误立即失败。

```python
import asyncio

_RETRYABLE_ERRORS = (ConnectionError, TimeoutError)

async def call_with_retry(func, *, max_retries: int = 3):
    for attempt in range(max_retries):
        try:
            return await func()
        except _RETRYABLE_ERRORS:
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(2 ** attempt)
```

### 4. Prompt 缓存

长 system prompt 加 `cache_control` 标记，避免每次请求重发。

```python
messages = [
    {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            },
            {
                "type": "text",
                "text": user_input,
            },
        ],
    }
]
```

## 组合管线

```python
async def generate_with_cost_control(
    text: str,
    config: Config,
    tracker: CostTracker,
) -> tuple[str, CostTracker]:
    model = select_model(len(text), estimated_items)
    if tracker.over_budget:
        raise BudgetExceededError(tracker.total_cost, tracker.budget_limit)

    response = await call_with_retry(lambda: llm_client.generate(model, text))
    record = CostRecord(model=model, input_tokens=..., output_tokens=..., cost_usd=...)
    return response, tracker.add(record)
```

## 定价参考

| 模型 | 输入 ($/1M tokens) | 输出 ($/1M tokens) | 相对成本 |
|------|---------------------|---------------------|----------|
| Haiku 4.5 | $0.80 | $4.00 | 1x |
| Sonnet 4.6 | $3.00 | $15.00 | ~4x |
| Opus 4.5 | $15.00 | $75.00 | ~19x |

## 最佳实践

- 从最便宜的模型开始，只在复杂度超阈值时升级
- 处理批量前设置明确预算上限，宁可早失败不要超支
- 记录模型选择日志，方便后续调优阈值
- 超过 1024 tokens 的 system prompt 用 prompt 缓存
- 认证和参数错误不重试，只重试瞬态故障

## 反模式

- 所有请求都用最贵模型
- 所有错误都重试（浪费预算在永久性失败上）
- 成本追踪用可变状态（难以调试和审计）
- 代码中到处硬编码模型名（用常量或配置）
