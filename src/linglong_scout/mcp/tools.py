"""MCP tool implementations for Linglong Scout."""

import asyncio
import json
import logging
from typing import Any

from linglong_scout.config import get_config

logger = logging.getLogger(__name__)


def _run_async(coro: Any) -> Any:
    """Run an async coroutine, handling both fresh and existing event loops."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


def fetch_rss(url: str, name: str | None = None, max_items: int = 20) -> str:
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

        async def _fetch():
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
                )
                resp.raise_for_status()
            return resp.text

        xml_text = _run_async(_fetch())
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


def record_feedback(
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
        from linglong_scout.scout.feedback import FeedbackStore

        store = FeedbackStore()
        if feedback not in ("useful", "not_interested"):
            return json.dumps(
                {"error": "feedback must be 'useful' or 'not_interested'"},
                ensure_ascii=False,
            )
        store.record(content_hash, feedback, tags)
        return json.dumps(
            {"status": "recorded", "content_hash": content_hash, "feedback": feedback},
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.exception("record_feedback failed")
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def execute_package(package_path: str) -> str:
    """Execute an scout package via IngestAgent.

    Returns the morning brief output as markdown.
    """
    try:
        from pathlib import Path

        from linglong_scout.scout.agent import IngestAgent
        from linglong_scout.scout.brief_history import BriefHistory
        from linglong_scout.scout.feedback import FeedbackStore
        from linglong_scout.scout.package import SourcePackage

        package = SourcePackage.from_yaml(package_path)

        config = get_config()
        feedback_store = FeedbackStore()
        history_dir = Path(config.ingest.brief_history_dir).expanduser()
        brief_history = BriefHistory(history_dir, config.ingest.dedup_windows)
        agent = IngestAgent(feedback_store=feedback_store, brief_history=brief_history)
        output = _run_async(agent.run(package))

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


def generate_brief() -> str:
    """Execute an scout package (YAML-defined collection of sources).

    Returns collected entities for discussion. Use write_entity to save
    selected results to the knowledge store.
    """
    try:
        from datetime import date, timedelta
        from pathlib import Path

        from linglong_scout.scout.agent import IngestAgent
        from linglong_scout.scout.brief_history import BriefHistory
        from linglong_scout.scout.feedback import FeedbackStore
        from linglong_scout.scout.package import SourcePackage

        config = get_config()
        if not config.ingest.packages:
            return json.dumps(
                {"error": "No packages configured in .scout.yml"},
                ensure_ascii=False,
            )

        # Cache check: return today's brief if already generated
        output_dir = Path(config.ingest.brief_output_dir).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
        today = date.today().isoformat()
        cache_path = output_dir / f"{today}.md"

        if cache_path.exists():
            cached = cache_path.read_text(encoding="utf-8")
            return json.dumps({
                "package": config.ingest.packages[0].get("name", ""),
                "output_length": len(cached),
                "cached": True,
                "output": cached,
            }, ensure_ascii=False)

        package = SourcePackage(**config.ingest.packages[0])
        feedback_store = FeedbackStore()
        history_dir = Path(config.ingest.brief_history_dir).expanduser()
        brief_history = BriefHistory(history_dir, config.ingest.dedup_windows)
        agent = IngestAgent(feedback_store=feedback_store, brief_history=brief_history)
        output = _run_async(agent.run(package))

        # Save to cache
        if output:
            cache_path.write_text(output, encoding="utf-8")

        # Cleanup old cached briefs
        cutoff = (date.today() - timedelta(days=config.ingest.brief_cache_days)).isoformat()
        for f in output_dir.glob("*.md"):
            if f.stem < cutoff:
                f.unlink()

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


def search_web(query: str, max_results: int = 10) -> str:
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

        async def _search():
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(f"{base_url}/search", params=params, headers=headers)
                resp.raise_for_status()
                return resp.json()

        data = _run_async(_search())
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
