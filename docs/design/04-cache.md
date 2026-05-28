# D-04 缓存与调度

> 状态：✅ 已实现 | 最后更新：2026-05-26

---

## 概述

`generate_brief()` 支持日内缓存，当天已生成的早报直接返回文件内容，避免重复 LLM 调用。

---

## 缓存机制

```
generate_brief()
  ├── 检查缓存文件 ~/linglong/briefs/{YYYY-MM-DD}.md
  │   ├── 存在 → 直接返回（0.2ms）
  │   └── 不存在 → 执行完整采集 + LLM 生成
  │       └── 保存到缓存文件
  └── 清理过期缓存（超过 brief_cache_days 天）
```

---

## 配置

| 配置 | 默认值 | 说明 |
|------|--------|------|
| `brief_output_dir` | `~/linglong/briefs` | 缓存目录，按日期 `{YYYY-MM-DD}.md` |
| `brief_schedule_time` | `07:30` | 播报时段标记 |
| `brief_cache_days` | `14` | 缓存保留天数 |

---

## 性能对比

| 场景 | 耗时 |
|------|------|
| 缓存命中 | 0.2ms |
| 完整生成 | ~83s（7.6s 采集 + ~75s LLM） |

---

## 调度

ingest 不做调度，由调用方处理：

- **Claude Code**：对话中按需调用 `generate_brief`
- **OpenClaw**：可通过 cron 定时触发
- **CLI**：`linglong-scout ingest`

---

## 关键文件

| 文件 | 说明 |
|------|------|
| `src/linglong_scout/mcp/tools.py` | `generate_brief()` 缓存逻辑 |
