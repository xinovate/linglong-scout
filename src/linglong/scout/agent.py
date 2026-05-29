"""IngestAgent — LLM-driven morning brief generator.

Pre-searches all keywords via SearXNG, then calls LLM once with the full
context to produce a structured morning brief in markdown.
"""

import json
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx

from linglong.config import get_config
from linglong.scout.brief_history import BriefHistory, parse_sections
from linglong.scout.cache import get_company_snapshot
from linglong.scout.collect import collect as collect_data
from linglong.scout.feedback import FeedbackStore
from linglong.scout.package import SourcePackage

logger = logging.getLogger(__name__)

_PROMPT_DIR = Path(__file__).parent / "prompts"


def _denormalize(items: list[dict[str, Any]], source: str) -> list[dict[str, str]]:
    """Convert normalized raw items back to source-specific format."""
    if not items:
        return items
    result = []
    for item in items:
        flat: dict[str, str] = {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("snippet", ""),
        }
        if source == "rss":
            flat["source"] = item.get("extra", {}).get("feed_name", "")
        elif source == "github":
            extra = item.get("extra", {})
            flat["stars"] = extra.get("stars", "")
            flat["growth"] = extra.get("growth", "")
            flat["period"] = extra.get("period", "")
        result.append(flat)
    return result


def _format_results(results: list[dict[str, str]]) -> str:
    """Format search results as numbered text for LLM context."""
    lines: list[str] = []
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r['title']}")
        lines.append(f"   URL: {r['url']}")
        if r["snippet"]:
            lines.append(f"   摘要: {r['snippet'][:200]}")
        lines.append("")
    return "\n".join(lines)


_SOURCE_LABELS = {
    "opengithubs": "OpenGithubs（GitHub Stars 增长排行）",
    "wangchujiang": "GitHub Trending（今日 stars 增长）",
    "search-api": "GitHub Search API（近 30 天新建高星项目）",
}


def _format_github(repos: list[dict[str, str]], source: str) -> str:
    """Format GitHub repos as structured text for LLM."""
    if not repos:
        return ""
    source_label = _SOURCE_LABELS.get(source, source)
    lines = [f"以下开源数据来自 {source_label}：", ""]

    periods: dict[str, list[dict[str, str]]] = {}
    for r in repos:
        period = r.get("period", "日增长")
        periods.setdefault(period, []).append(r)

    for period_label, period_repos in periods.items():
        lines.append(f"### {period_label}")
        for i, r in enumerate(period_repos, 1):
            lines.append(f"{i}. {r['title']}")
            lines.append(f"   URL: {r['url']}")
            lines.append(f"   Stars: {r['stars']}")
            if r["snippet"]:
                lines.append(f"   描述: {r['snippet'][:200]}")
            lines.append("")

    return "\n".join(lines)


def _format_rss(items: list[dict[str, str]]) -> str:
    """Format RSS items as structured text for LLM."""
    if not items:
        return ""
    lines = ["以下数据来自 RSS 订阅源：", ""]
    for i, item in enumerate(items, 1):
        lines.append(f"{i}. [{item['source']}] {item['title']}")
        lines.append(f"   URL: {item['url']}")
        if item["snippet"]:
            lines.append(f"   摘要: {item['snippet'][:200]}")
        lines.append("")
    return "\n".join(lines)


def _format_company_snapshot(snapshot: dict[str, Any]) -> str:
    """Format company snapshot as structured text for LLM."""
    companies = snapshot.get("companies", {})
    if not companies:
        return ""
    updated = snapshot.get("updated", "unknown")
    lines = [
        f"以下是中美 AI 头部公司融资快照（更新于 {updated}），用于填充公司动态表格的融资列和股价/估值变动列：",
        "",
        "| 公司 | 融资 | 估值 | 股票代码 |",
        "|------|------|------|----------|",
    ]
    for name, info in companies.items():
        funding = info.get("latest_funding") or "—"
        valuation = info.get("valuation") or "—"
        stock = info.get("stock") or "—"
        lines.append(f"| {name} | {funding} | {valuation} | {stock} |")
    lines.append("")
    return "\n".join(lines)


def _load_prompt() -> str:
    """Load the morning brief prompt template."""
    path = _PROMPT_DIR / "morning_brief.md"
    return path.read_text(encoding="utf-8")


def _call_llm(system: str, user: str, max_tokens: int | None = None, retries: int | None = None) -> str:
    """Call LLM via Anthropic Messages API, with retry."""
    config = get_config()
    base_url = config.llm.llm_base_url
    api_key = config.llm.llm_api_key
    model = config.llm.llm_model
    if not base_url or not api_key or not model:
        raise RuntimeError("LLM not configured: set llm.llm_base_url, llm.llm_api_key, llm.llm_model in .scout.yml")
    base_url = base_url.rstrip("/")
    if max_tokens is None:
        max_tokens = config.ingest.llm_max_tokens
    if retries is None:
        retries = config.ingest.llm_retries
    timeout = config.ingest.llm_timeout

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = httpx.post(
                f"{base_url}/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": max_tokens,
                    "messages": [
                        {"role": "user", "content": f"{system}\n\n{user}"},
                    ],
                },
                timeout=timeout,
            )
            response.raise_for_status()
            data = response.json()
            return data["content"][0]["text"].strip()
        except Exception as e:
            last_error = e
            if attempt < retries:
                logger.warning("LLM call attempt %d failed: %s, retrying...", attempt + 1, e)
            else:
                logger.error("LLM call failed after %d attempts: %s", retries + 1, e)
    raise last_error  # type: ignore[misc]


class IngestAgent:
    """LLM-driven morning brief generator — pre-search + single prompt."""

    def __init__(
        self,
        feedback_store: FeedbackStore | None = None,
        brief_history: BriefHistory | None = None,
    ) -> None:
        self.feedback_store = feedback_store
        self.brief_history = brief_history

    async def run(self, package: SourcePackage, user_id: str = "default") -> str:
        """Full pipeline: collect → store raw → format → LLM → brief."""
        raw = await collect_data(package)
        today = date.today().isoformat()

        from linglong.scout.raw_store import store_raw
        store_raw(
            target_date=today,
            searxng=raw["searxng"],
            github=raw["github"],
            rss=raw["rss"],
            github_source=raw["github_source"],
        )

        return self._generate(package, raw, user_id=user_id)

    def run_from_raw(self, package: SourcePackage, raw: dict[str, Any], user_id: str = "default") -> str:
        """Generate brief from pre-collected raw data (skip collection)."""
        return self._generate(package, raw, user_id=user_id)

    def _generate(self, package: SourcePackage, raw: dict[str, Any], user_id: str = "default") -> str:
        """Format raw data + call LLM to produce brief."""
        all_results = _denormalize(raw["searxng"], "searxng")
        github_repos = _denormalize(raw["github"], "github")
        github_source = raw.get("github_source", "")
        rss_items = _denormalize(raw["rss"], "rss")

        today = date.today().isoformat()

        if not all_results and not github_repos and not rss_items:
            return f"# {package.topic} · {today}\n\n今日暂无搜索结果。"

        search_text = _format_results(all_results)
        github_text = _format_github(github_repos, github_source)
        rss_text = _format_rss(rss_items)

        preference_section = ""
        if self.feedback_store:
            pref = self.feedback_store.get_preference_text(user_id)
            if pref:
                preference_section = f"\n## 用户偏好\n\n{pref}"

        history_section = ""
        if self.brief_history:
            history_text = self.brief_history.format_for_prompt()
            if history_text:
                history_section = f"\n{history_text}"

        snapshot = get_company_snapshot()
        snapshot_text = _format_company_snapshot(snapshot)

        prompt_template = _load_prompt()
        config = get_config()
        schedule_time = config.ingest.brief_schedule_time
        time_range = f"{(date.today() - timedelta(days=1)).isoformat()} {schedule_time} → {today} {schedule_time}"

        system_prompt = prompt_template.format(
            topic=package.topic,
            date=today,
            time_range=time_range,
            search_results=search_text,
            github_data=github_text,
            rss_data=rss_text,
            company_snapshot=snapshot_text,
            preference_section=preference_section,
            history_section=history_section,
        )

        logger.info(
            "Calling LLM with %d SearXNG + %d GitHub + %d RSS items...",
            len(all_results), len(github_repos), len(rss_items),
        )
        try:
            output = _call_llm(system_prompt, search_text[:2000])
            logger.info("LLM output: %d chars", len(output))
        except Exception as e:
            logger.error("LLM call failed, attempting fallback: %s", e)
            if self.brief_history:
                fallback = self.brief_history.get_last_output()
                if fallback:
                    logger.warning("Using last successful brief as fallback")
                    return (
                        f"# {package.topic} · {today}\n\n"
                        f"> ⚠️ 今日 LLM 生成失败，以下为上一次成功生成的早报：\n\n"
                        f"{fallback}"
                    )
            raise

        if self.brief_history:
            sections = parse_sections(output)
            if sections:
                self.brief_history.check_overlap(sections)
                self.brief_history.save(today, sections)
                self.brief_history.cleanup()

        return output
