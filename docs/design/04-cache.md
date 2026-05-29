# D-04 缓存与调度

> 状态：✅ 已实现 | 最后更新：2026-05-29

---

## 概述

`generate_brief()` 支持日内缓存（按 user_id 隔离），当天已生成的早报直接从 Redis 返回，避免重复 LLM 调用。

---

## 缓存机制

```
generate_brief()
  ├── 检查 Redis scout:brief:{YYYY-MM-DD}:{user_id}
  │   ├── 存在 → 直接返回
  │   └── 不存在 → 执行完整采集 + LLM 生成
  │       └── 写入 Redis（TTL 25h，按 user_id 隔离）
  └── 清理过期 history key（超过 16 天）
```

---

## Redis 数据结构

| Key | 类型 | TTL | 说明 |
|-----|------|-----|------|
| `scout:brief:{date}:{user_id}` | string | 25h | 当天早报 markdown（按用户隔离） |
| `scout:history:{date}` | hash | 16d | 按维度的去重历史 |

---

## 配置

| 配置 | 默认值 | 说明 |
|------|--------|------|
| `brief_schedule_time` | `07:00` | 播报时段标记 |
| `collect_schedule` | `06:55` | 每天自动采集时间（HH:MM），留空禁用 |
| `mcp.redis_url` | `""` | Redis 连接地址，未配置时缓存不可用 |

---

## 性能对比

| 场景 | 耗时 |
|------|------|
| 缓存命中 | <1ms |
| 完整生成 | ~100s（数据采集 + LLM） |

---

## 调度

容器内自调度：MCP server 启动时自动运行 `scheduler.py` 后台 asyncio 任务。

| 配置 | 默认值 | 说明 |
|------|--------|------|
| `ingest.collect_schedule` | `"06:55"` | 每天采集时间（HH:MM），留空禁用 |

也提供 CLI 命令供手动触发：

```bash
# 仅采集（不调 LLM）
linglong-scout collect

# 生成早报（有缓存则直接返回）
linglong-scout brief
linglong-scout brief --force  # 强制重新生成
```

---

## 关键文件

| 文件 | 说明 |
|------|------|
| `src/linglong/scout/cache.py` | Redis 缓存读写 |
| `src/linglong/scout/brief_history.py` | 去重历史（Redis hash） |
| `src/linglong/mcp/tools.py` | `generate_brief()` 缓存逻辑 |
| `src/linglong/cli.py` | `brief` CLI 命令 |
