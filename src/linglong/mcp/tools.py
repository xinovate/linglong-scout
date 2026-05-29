"""MCP tool implementations for Linglong Scout."""

import json
import logging
from typing import Any

from linglong.config import get_config
from linglong.mcp._auth import get_current_user_id

logger = logging.getLogger(__name__)


async def fetch_rss(url: str, name: str | None = None, max_items: int = 20) -> str:
    """Fetch and parse an RSS feed. Returns entity previews for discussion.

    Use this to collect information from RSS sources. Discuss with the user
    before writing any results to the knowledge store via write_entity.
    """
    try:
        import re

        import feedparser
        import httpx

        config = get_config()
        if config.ingest.rsshub_access_key and (":1200/" in url or url.rstrip("/").endswith(":1200")):
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}key={config.ingest.rsshub_access_key}"

        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
            )
            resp.raise_for_status()
            xml_text = resp.text

        feed = feedparser.parse(xml_text)
        items = []
        for entry in feed.entries[:max_items]:
            summary = getattr(entry, "summary", "") or getattr(entry, "description", "")
            clean = re.sub(r"<[^>]+>", "", summary)[:300]
            items.append({
                "title": getattr(entry, "title", ""),
                "url": getattr(entry, "link", ""),
                "snippet": clean,
                "source": name or url,
            })

        return json.dumps(
            {"results": items, "count": len(items)},
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.exception("fetch_rss failed")
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


async def fetch_github_trending(
    daily: int = 5, weekly: int = 3, monthly: int = 3,
) -> str:
    """Fetch GitHub trending repos with stars growth.

    Returns repos from OpenGithubs (primary), wangchujiang HTML (fallback),
    or GitHub Search API (last resort).
    """
    try:
        from linglong.scout.collect import _github_trending

        limits = {"daily": daily, "weekly": weekly, "monthly": monthly}
        repos, source = await _github_trending(limits=limits)

        results = []
        for r in repos:
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("snippet", ""),
                "stars": r.get("stars", ""),
                "growth": r.get("growth", ""),
                "period": r.get("period", ""),
            })

        return json.dumps(
            {"results": results, "count": len(results), "source": source},
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.exception("fetch_github_trending failed")
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


async def record_feedback(
    content_hash: str,
    feedback: str,
    tags: list[str] | None = None,
) -> str:
    """Record user feedback on an scout result for preference learning.

    Args:
        content_hash: Hash identifying the news item.
        feedback: "useful" or "not_interested".
        tags: Tags associated with the news item (optional).
    """
    try:
        from linglong.scout.feedback import FeedbackStore

        store = FeedbackStore()
        if feedback not in ("useful", "not_interested"):
            return json.dumps(
                {"error": "feedback must be 'useful' or 'not_interested'"},
                ensure_ascii=False,
            )
        user_id = get_current_user_id()
        store.record(content_hash, feedback, tags, user_id=user_id)
        return json.dumps(
            {"status": "recorded", "content_hash": content_hash, "feedback": feedback},
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.exception("record_feedback failed")
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


async def execute_package(
    topic: str,
    keywords: list[str] | None = None,
    name: str = "custom-brief",
    max_results: int = 5,
) -> str:
    """Execute a custom scout package with given parameters.

    Collects data from SearXNG, GitHub trending, and RSS feeds based on
    keywords, then generates a structured brief via LLM.

    Args:
        topic: Brief topic, e.g. "AI 早报" or "开源周刊".
        keywords: Search keywords for SearXNG. If empty, skips web search.
        name: Package name identifier.
        max_results: Max results per keyword.
    """
    try:
        from linglong.scout.agent import IngestAgent
        from linglong.scout.brief_history import BriefHistory
        from linglong.scout.feedback import FeedbackStore
        from linglong.scout.package import SearchQueryConfig, SourcePackage

        package = SourcePackage(
            name=name,
            topic=topic,
            search_queries=[
                SearchQueryConfig(
                    keywords=keywords or [],
                    max_results=max_results,
                ),
            ] if keywords else [],
        )

        config = get_config()
        feedback_store = FeedbackStore()
        brief_history = BriefHistory(dedup_windows=config.ingest.dedup_windows)
        agent = IngestAgent(feedback_store=feedback_store, brief_history=brief_history)
        user_id = get_current_user_id()
        output = await agent.run(package, user_id=user_id)

        response: dict[str, Any] = {
            "package": package.name,
            "output_length": len(output) if output else 0,
        }
        if output:
            response["output"] = output
        return json.dumps(response, ensure_ascii=False)
    except Exception as exc:
        logger.exception("execute_package failed")
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


async def generate_brief() -> str:
    """Generate morning brief from collected data.

    If raw data already exists in Redis for today, skips collection and
    feeds existing data to LLM. Otherwise collects fresh, stores raw data,
    then generates the brief.
    """
    try:
        from datetime import date

        from linglong.scout.agent import IngestAgent
        from linglong.scout.brief_history import BriefHistory
        from linglong.scout.cache import get_brief, set_brief
        from linglong.scout.feedback import FeedbackStore
        from linglong.scout.package import SourcePackage
        from linglong.scout.raw_store import get_raw, get_raw_meta, has_raw

        config = get_config()
        if not config.ingest.packages:
            return json.dumps(
                {"error": "No packages configured in .scout.yml"},
                ensure_ascii=False,
            )

        user_id = get_current_user_id()
        today = date.today().isoformat()
        cached = get_brief(today, user_id=user_id)
        if cached:
            return json.dumps({
                "package": config.ingest.packages[0].get("name", ""),
                "output_length": len(cached),
                "cached": True,
                "output": cached,
            }, ensure_ascii=False)

        package = SourcePackage(**config.ingest.packages[0])
        feedback_store = FeedbackStore()
        brief_history = BriefHistory(dedup_windows=config.ingest.dedup_windows)
        agent = IngestAgent(feedback_store=feedback_store, brief_history=brief_history)

        if has_raw(today):
            raw_data = get_raw(today)
            meta = get_raw_meta(today)
            raw = {
                "searxng": raw_data.get("searxng", []),
                "github": raw_data.get("github", []),
                "github_source": meta.get("github_source", ""),
                "rss": raw_data.get("rss", []),
            }
            output = agent.run_from_raw(package, raw, user_id=user_id)
        else:
            output = await agent.run(package, user_id=user_id)

        if output:
            set_brief(output, today, user_id=user_id)

        response: dict[str, Any] = {
            "package": package.name,
            "output_length": len(output) if output else 0,
            "cached": False,
        }
        if output:
            response["output"] = output
        return json.dumps(response, ensure_ascii=False)
    except Exception as exc:
        logger.exception("generate_brief failed")
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


async def search_web(query: str, max_results: int = 10) -> str:
    """Search the web via SearXNG. Returns results including web page title, web page URL, web page summary, website name, website icon, etc."""
    try:
        import httpx

        config = get_config()
        base_url = config.ingest.searxng_url.rstrip("/")
        timeout = config.ingest.search_timeout

        params = {
            "q": query,
            "format": "json",
            "categories": "general",
        }
        headers: dict[str, str] = {}
        if config.ingest.searxng_api_key:
            headers["Authorization"] = f"Bearer {config.ingest.searxng_api_key}"

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{base_url}/search", params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        results = []
        for r in data.get("results", [])[:max_results]:
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", ""),
                "engine": r.get("engine", ""),
            })

        return json.dumps(
            {"results": results, "count": len(results)},
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.exception("search_web failed")
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


async def fetch_raw(target_date: str | None = None, source: str | None = None) -> str:
    """Fetch structured raw data collected for a given date.

    Returns raw collected data (SearXNG search results, GitHub trending,
    RSS items) as structured JSON. Useful for inspecting data before
    brief generation or for custom analysis.

    Args:
        target_date: ISO date string (e.g. "2026-05-28"). Defaults to today.
        source: Filter to a specific source: "searxng", "rss", or "github".
    """
    try:
        from datetime import date

        from linglong.scout.raw_store import get_raw, get_raw_meta

        d = target_date or date.today().isoformat()

        if source and source not in ("searxng", "rss", "github"):
            return json.dumps(
                {"error": f"Invalid source '{source}'. Use: searxng, rss, github"},
                ensure_ascii=False,
            )

        data = get_raw(target_date=d, source=source)
        meta = get_raw_meta(target_date=d)

        result: dict[str, Any] = {"date": d, "meta": meta, "sources": {}}
        for src, items in data.items():
            if items:
                result["sources"][src] = {"count": len(items), "items": items}

        if not any(data.values()):
            result["warning"] = "No raw data found for this date"

        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        logger.exception("fetch_raw failed")
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
