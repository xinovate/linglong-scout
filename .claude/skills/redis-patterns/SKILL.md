---
name: redis-patterns
description: Redis 缓存模式、分布式锁、限流、Pub/Sub、连接管理和反模式参考。处理 linglong-scout Redis 相关代码时激活。
---

# Redis 模式参考

linglong-scout 使用 Redis 缓存原始采集数据和生成的摘要。本 skill 提供常用模式参考。

## 适用场景

- 添加或修改 Redis 缓存逻辑
- 实现 Token 存储或会话管理
- 配置连接池、TTL 策略
- 排查缓存相关问题

## 数据结构速查

| 用途 | 结构 | 示例 Key |
|------|------|----------|
| 采集数据缓存 | String (JSON) | `scout:raw:2026-01-15` |
| 摘要缓存 | String (JSON) | `scout:brief:2026-01-15` |
| Token 存储 | String | `linglong-scout-<随机串>` |
| 限流计数 | String (INCR) | `ratelimit:github:api` |

## Cache-Aside 模式

```python
import json
import redis.asyncio as redis

async def get_cached_brief(r: redis.Redis, date: str) -> dict | None:
    key = f"scout:brief:{date}"
    cached = await r.get(key)
    if cached:
        return json.loads(cached)
    return None

async def set_cached_brief(r: redis.Redis, date: str, data: dict, ttl: int = 86400) -> None:
    key = f"scout:brief:{date}"
    await r.setex(key, ttl, json.dumps(data, ensure_ascii=False))
```

## Write-Through 缓存

```python
async def store_raw_data(r: redis.Redis, date: str, source: str, data: dict) -> None:
    key = f"scout:raw:{date}:{source}"
    await r.setex(key, 86400 * 7, json.dumps(data, ensure_ascii=False))
```

## 连接池

```python
from redis.asyncio import ConnectionPool, Redis

pool = ConnectionPool(
    host="localhost",
    port=6379,
    db=0,
    max_connections=10,
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=2,
)

def get_redis() -> Redis:
    return Redis(connection_pool=pool)
```

## TTL 策略

| 数据类型 | 建议 TTL |
|----------|----------|
| 当日原始数据 | 7 天 (`604800`) |
| 当日摘要 | 3 天 (`259200`) |
| Token | 无 TTL（手动管理） |
| 限流窗口 | 匹配窗口大小 |

**必须设置 TTL**。无 TTL 的 key 会无限累积导致内存压力。

## Key 命名

```
scout:raw:<date>:<source>     # 原始采集数据
scout:brief:<date>            # 生成摘要
```

## 反模式

| 反模式 | 问题 | 修复 |
|--------|------|------|
| Key 无 TTL | 内存无限增长 | 始终设置 TTL |
| 生产环境 `KEYS *` | 阻塞服务器 O(N) | 用 `SCAN` 游标 |
| 存储大于 100KB 的 blob | 序列化慢、内存压力大 | 存引用 + 从对象存储获取 |
| 每次请求新建连接 | 握手开销 | 用连接池 |
| 不处理缓存击穿 | 冷启动时雪崩 | 用锁或概率提前过期 |

## 缓存击穿防护

```python
async def get_or_fetch(r: redis.Redis, key: str, fetch_fn, ttl: int = 300):
    cached = await r.get(key)
    if cached:
        return json.loads(cached)

    lock_key = f"lock:{key}"
    lock = await r.set(lock_key, "1", px=5000, nx=True)
    if lock:
        try:
            value = await fetch_fn()
            await r.setex(key, ttl, json.dumps(value, ensure_ascii=False))
            return value
        finally:
            await r.delete(lock_key)
    else:
        await asyncio.sleep(0.1)
        return await get_or_fetch(r, key, fetch_fn, ttl)
```

## 限流（固定窗口）

```python
async def check_rate_limit(r: redis.Redis, key: str, limit: int = 100, window: int = 60) -> bool:
    pipe = r.pipeline(transaction=True)
    pipe.incr(key)
    pipe.expire(key, window)
    count, _ = await pipe.execute()
    return count <= limit
```
