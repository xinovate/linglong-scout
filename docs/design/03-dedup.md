# D-03 去重机制

> 状态：✅ 已实现 | 最后更新：2026-05-26 | 依赖：[D-02 Agent 流水线](02-agent-pipeline.md)

---

## 概述

ingest 的去重分两层：URL 级（代码去重）和语义级（LLM 通过 BriefHistory 判断）。

---

## 去重流程图

```mermaid
flowchart TD
    START([数据采集完成]) --> URL_DEDUP

    subgraph URL_DEDUP["第一层：URL 级去重"]
        U1["SearXNG 内部去重<br/>seen_urls 集合"]
        U2["RSS 内部去重<br/>seen_urls 集合"]
        U3["交叉去重<br/>RSS 排除 SearXNG 已有 URL"]
    end

    URL_DEDUP --> BH_LOAD

    subgraph SEMANTIC["第二层：语义级去重 (BriefHistory)"]
        BH_LOAD["加载历史<br/>brief_history_dir/*.json"]
        BH_FILTER["按 dedup_windows 过期<br/>关键人物 14d / 公司 7d / ..."]
        BH_FORMAT["format_for_prompt()<br/>按维度汇总已播报"]
        BH_INJECT["注入 {history_section}"]

        BH_LOAD --> BH_FILTER --> BH_FORMAT --> BH_INJECT
    end

    BH_INJECT --> LLM["LLM 生成早报<br/>看到已播报内容"]
    LLM --> DEDUP_NOTE["每个维度下方生成去重注释<br/>> 注：xxx 等已在前期播报"]
    DEDUP_NOTE --> SAVE["保存当天输出到 BriefHistory"]

    style URL_DEDUP fill:#4CAF50,color:#fff
    style SEMANTIC fill:#2196F3,color:#fff
    style LLM fill:#9C27B0,color:#fff
```

---

## 去重层级

| 层级 | 范围 | 方法 | 实现 |
|------|------|------|------|
| SearXNG 内部 | URL 级 | `seen_urls` 集合 | agent.py |
| RSS 内部 | URL 级 | `seen_urls` 集合 | agent.py |
| SearXNG ↔ RSS 交叉 | URL 级 | RSS 排除 SearXNG 已出现的 URL | agent.py |
| BriefHistory 跨天 | 语义级 | 历史输出注入 prompt，LLM 判断 + 去重注释 | brief_history.py |

---

## BriefHistory 去重窗口

每个维度有独立的回看天数：

| 维度 | 默认窗口 | 原因 |
|------|----------|------|
| 关键人物 | 14 天 | 人物观点短期不变 |
| 公司动态 | 7 天 | 事件更新频率高 |
| 政策动态 | 14 天 | 政策周期较长 |
| 应用落地 | 7 天 | 产品更新频率高 |
| 开源趋势 | 不去重 | trending 项目自然变化 |

配置路径：`ingest.dedup_windows`，历史文件存储在 `~/linglong/brief_history/`。

---

## BriefHistory 时序图

```mermaid
sequenceDiagram
    participant Agent as IngestAgent
    participant BH as BriefHistory
    participant FS as ~/linglong/brief_history/
    participant LLM as LLM API

    Agent->>BH: BriefHistory(history_dir, dedup_windows)
    BH->>FS: load() 读取 JSON 文件
    BH->>BH: 按 dedup_windows 过滤过期条目

    Agent->>BH: format_for_prompt()
    BH-->>Agent: {history_section} 文本

    Agent->>Agent: 组装 prompt（注入 history_section）
    Agent->>LLM: _call_llm(prompt)
    LLM-->>Agent: markdown 早报（含去重注释）

    Agent->>BH: save(today_output)
    BH->>FS: 写入 {date}.json
```

---

## 重叠检测

BriefHistory 提供 `check_overlap(new_content)` 方法，检测新生成的早报与历史输出的重叠率。LLM 失败时触发 fallback：直接返回历史输出。

---

## 配置外部化

所有去重参数通过 `.scout.yml` 管理：

```yaml
ingest:
  brief_history_dir: ~/linglong/brief_history
  dedup_windows:
    关键人物: 14
    公司动态: 7
    政策动态: 14
    应用落地: 7
```

---

## 关键文件

| 文件 | 说明 |
|------|------|
| `src/linglong_scout/ingest/brief_history.py` | BriefHistory 类 |
| `src/linglong_scout/ingest/agent.py` | URL 去重逻辑 |
