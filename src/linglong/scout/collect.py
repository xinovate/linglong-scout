"""Data collection — GitHub trending, RSS feeds."""

import asyncio
import logging
import os
import re
from datetime import date, timedelta
from typing import Any

import feedparser
import httpx

from linglong.config import get_config

logger = logging.getLogger(__name__)


class SourceHealth:
    """Track health of each data source (success rate, consecutive failures)."""

    def __init__(self, warn_threshold: int = 3) -> None:
        self._warn_threshold = warn_threshold
        self._stats: dict[str, dict[str, Any]] = {}

    def record(self, source: str, success: bool, item_count: int = 0) -> None:
        if source not in self._stats:
            self._stats[source] = {
                "total": 0, "success": 0, "consecutive_failures": 0, "last_items": 0,
            }
        s = self._stats[source]
        s["total"] += 1
        s["last_items"] = item_count
        if success:
            s["success"] += 1
            s["consecutive_failures"] = 0
        else:
            s["consecutive_failures"] += 1
            if s["consecutive_failures"] >= self._warn_threshold:
                logger.warning(
                    "Source '%s' failed %d times in a row", source, s["consecutive_failures"],
                )

    def summary(self) -> str:
        if not self._stats:
            return ""
        lines = ["Source health report:"]
        for name, s in sorted(self._stats.items()):
            rate = s["success"] / s["total"] * 100 if s["total"] else 0
            lines.append(
                f"  {name}: {rate:.0f}% success ({s['success']}/{s['total']}), "
                f"last: {s['last_items']} items"
            )
        return "\n".join(lines)


source_health = SourceHealth()


def _resolve_source_url(source: dict[str, str]) -> str:
    """Resolve a source config to a fetchable URL.

    If 'route' is present, prepend rsshub_url and inject access_key.
    If 'url' is present, return as-is.
    """
    if "route" in source:
        config = get_config()
        base = (config.ingest.rsshub_url or "").rstrip("/")
        path = source["route"].lstrip("/")
        url = f"{base}/{path}"
        if config.ingest.rsshub_access_key:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}key={config.ingest.rsshub_access_key}"
        return url
    return source["url"]


async def _github_headers() -> dict[str, str]:
    """Return GitHub API headers with token from env or gh CLI."""
    headers = {"Accept": "application/vnd.github.v3+json"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        try:
            proc = await asyncio.create_subprocess_exec(
                "gh", "auth", "token",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            token = stdout.decode().strip()
        except Exception:
            pass
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


# --- GitHub Trending ---

_GITHUB_TOPICS = ["ai", "llm", "ai-agent", "machine-learning", "deep-learning"]
_OPENGITHUB_API = "https://api.github.com/repos/OpenGithubs"

_TREND_PERIODS: dict[str, tuple[str, Any, str]] = {
    "daily": (
        "github-daily-rank",
        lambda d: f"{d.year}/{d.month:02d}/{d.strftime('%Y%m%d')}.md",
        "日增长",
    ),
    "weekly": (
        "github-weekly-rank",
        lambda d: f"{d.year}/{d.month:02d}/{d.strftime('%Y%m%d')}.md",
        "周增长",
    ),
    "monthly": (
        "github-monthly-rank",
        lambda d: f"{d.year}/{d.month:02d}.md",
        "月增长",
    ),
}


async def _github_trending(
    limits: dict[str, int] | None = None,
) -> tuple[list[dict[str, str]], str]:
    """Fetch GitHub trending repos across daily/weekly/monthly periods.

    Priority: OpenGithubs → wangchujiang.com → GitHub Search API.

    Returns (repos, source) where source indicates the data origin.
    """
    if limits is None:
        config = get_config()
        limits = config.ingest.github_trending_limits

    repos, source = await _fetch_opengithubs(limits)
    if repos:
        return repos, source

    repos = await _fetch_trending_html(limits.get("daily", 10))
    if repos:
        return repos, "wangchujiang"

    logger.info("All trending sources unavailable, falling back to GitHub Search API")
    config = get_config()
    fb = config.ingest.github_search_fallback
    repos = await _github_search_fallback(
        since_days=fb.get("since_days", 30),
        min_stars=fb.get("min_stars", 500),
        limit=sum(limits.values()),
    )
    return repos, "search-api"


async def _fetch_opengithubs(
    limits: dict[str, int],
) -> tuple[list[dict[str, str]], str]:
    """Fetch trending data from OpenGithubs via GitHub Contents API."""
    import base64

    today = date.today()
    all_repos: list[dict[str, str]] = []
    seen: set[str] = set()
    headers = await _github_headers()

    for period, (repo, path_fn, growth_label) in _TREND_PERIODS.items():
        limit = limits.get(period, 0)
        if limit <= 0:
            continue

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                if period == "monthly":
                    file_path = path_fn(today)
                    url = f"{_OPENGITHUB_API}/{repo}/contents/{file_path}"
                    response = await client.get(url, headers=headers)
                else:
                    # daily/weekly: list directory and pick latest file
                    dir_path = path_fn(today).rsplit("/", maxsplit=1)[0]
                    dir_url = f"{_OPENGITHUB_API}/{repo}/contents/{dir_path}"
                    dir_resp = await client.get(dir_url, headers=headers)
                    dir_resp.raise_for_status()
                    files = dir_resp.json()
                    md_files = sorted(
                        [f["name"] for f in files if f["name"].endswith(".md")],
                        reverse=True,
                    )
                    if not md_files:
                        raise LookupError(f"No .md files in {dir_path}")
                    latest = md_files[0]
                    file_url = f"{_OPENGITHUB_API}/{repo}/contents/{dir_path}/{latest}"
                    response = await client.get(file_url, headers=headers)

                response.raise_for_status()

            data = response.json()
            md = base64.b64decode(data["content"]).decode("utf-8")
            repos = _parse_opengithub_table(md, growth_label, limit, seen)
            all_repos.extend(repos)
            logger.info("OpenGithubs %s: %d repos", period, len(repos))
        except Exception as e:
            logger.warning("OpenGithubs %s fetch failed: %s", period, e)

    if all_repos:
        return all_repos, "opengithubs"
    return [], ""


def _extract_detail_descriptions(md: str) -> dict[str, str]:
    """Extract per-repo descriptions from <h3> detail sections."""
    descs: dict[str, str] = {}
    sections = re.split(r"<h3[^>]*>", md)
    for section in sections:
        url_match = re.search(
            r"https://github\.com/([a-zA-Z0-9_.\-]+/[a-zA-Z0-9_.\-]+)", section,
        )
        if not url_match:
            continue
        full_name = url_match.group(1)
        desc_match = re.search(r"项目描述[：:]\s*(.+)", section)
        desc = desc_match.group(1).strip() if desc_match else ""
        if desc:
            descs[full_name] = desc
    return descs


def _parse_opengithub_table(
    md: str,
    growth_label: str,
    limit: int,
    seen: set[str],
) -> list[dict[str, str]]:
    """Parse markdown table from OpenGithubs rank file."""
    repos: list[dict[str, str]] = []
    rows = re.findall(
        r'\|\s*\d+\s*\|\s*\[([^\]]+)\]\(([^)]+)\)\s*\|\s*([\d.k]+)\s*\|\s*🔺?(\d[\d,]*)\s*\|',
        md,
    )
    descriptions = _extract_detail_descriptions(md)

    for full_name, url, total_stars, growth in rows:
        if full_name in seen:
            continue

        desc = descriptions.get(full_name, "")

        raw_growth = growth.replace(",", "")

        repos.append({
            "title": f"{full_name} (+{raw_growth}⭐ {growth_label})",
            "url": url,
            "snippet": desc[:200],
            "stars": total_stars,
            "growth": raw_growth,
            "period": growth_label,
        })

    selected = repos[:limit]
    seen.update(r["title"].split(" ")[0] for r in selected)
    return selected


async def _fetch_trending_html(max_results: int) -> list[dict[str, str]]:
    """Parse trending repos from wangchujiang.com HTML."""
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                "https://wangchujiang.com/github-rank/trending.html",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            response.raise_for_status()

        html = response.text
        li_blocks = re.findall(r'<li>\s*(.*?)\s*</li>', html, re.DOTALL)
        repos: list[dict[str, str]] = []

        for block in li_blocks:
            name_match = re.search(
                r'href="https://github\.com/([a-zA-Z0-9_.\-]+/[a-zA-Z0-9_.\-]+)"', block
            )
            if not name_match or 'topics/' in name_match.group(1):
                continue
            full_name = name_match.group(1)

            desc_match = re.search(r'<div class="details">\s*(.*?)\s*</div>', block, re.DOTALL)
            desc = re.sub(r'<[^>]+>', '', desc_match.group(1)).strip() if desc_match else ''

            total_match = re.search(r'(\d[\d,]*)\s*stars total', block)
            total_stars = total_match.group(1).replace(',', '') if total_match else '0'

            stars_match = re.search(r'([\d,]+)\s*stars today', block)
            today_stars = stars_match.group(1).replace(',', '') if stars_match else None

            if today_stars:
                repos.append({
                    "title": f"{full_name} (+{today_stars}⭐ 日增长)",
                    "url": f"https://github.com/{full_name}",
                    "snippet": re.sub(r'&[#\w]+;', '', desc)[:200],
                    "stars": total_stars,
                    "growth": today_stars,
                    "period": "日增长",
                })

        repos.sort(key=lambda r: int(r.get("growth", "0")), reverse=True)
        repos = repos[:max_results]
        logger.info("GitHub Trending (wangchujiang): %d repos", len(repos))
        return repos
    except Exception as e:
        logger.warning("Trending HTML fetch failed: %s", e)
        return []


async def _github_search_fallback(since_days: int, min_stars: int, limit: int) -> list[dict[str, str]]:
    """Fallback: search GitHub for recently created AI repos."""
    cutoff = (date.today() - timedelta(days=since_days)).isoformat()
    all_repos: list[dict[str, str]] = []
    seen: set[str] = set()

    for topic in _GITHUB_TOPICS:
        query = f"created:>{cutoff} stars:>{min_stars} topic:{topic}"
        params = {
            "q": query,
            "sort": "stars",
            "order": "desc",
            "per_page": "10",
        }
        headers = await _github_headers()

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(
                    "https://api.github.com/search/repositories",
                    params=params,
                    headers=headers,
                )
                response.raise_for_status()

            for item in response.json().get("items", []):
                full_name = item.get("full_name", "")
                if full_name in seen:
                    continue
                seen.add(full_name)
                stars = item.get("stargazers_count", 0)
                created = item.get("created_at", "")[:10]
                all_repos.append({
                    "title": f"{full_name} ({stars}⭐, created {created})",
                    "url": item.get("html_url", ""),
                    "snippet": item.get("description") or "",
                    "stars": str(stars),
                    "growth": str(stars),
                    "period": "总星",
                })
        except Exception as e:
            logger.warning("GitHub search failed for topic '%s': %s", topic, e)

    all_repos.sort(key=lambda r: int(r.get("stars", "0")), reverse=True)
    logger.info("GitHub Search fallback: %d unique repos", len(all_repos))
    return all_repos[:limit]


# --- RSS ---


def _validate_feed_url(url: str, *, allow_internal: bool = False) -> None:
    """Validate URL to prevent SSRF attacks.

    Args:
        url: Feed URL to validate.
        allow_internal: Skip private-network checks. Use only for
            admin-configured sources (not user-supplied URLs).

    Raises:
        ValueError: If URL uses disallowed scheme or targets internal network.
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"URL scheme not allowed: {parsed.scheme} (only http/https)")
    if allow_internal:
        return
    host = parsed.hostname or ""
    if not host:
        raise ValueError("URL must have a hostname")
    # Block internal/private network addresses
    if (
        host in ("localhost", "127.0.0.1", "0.0.0.0", "::1")
        or host.startswith("192.168.")
        or host.startswith("10.")
        or (
            host.startswith("172.")
            and host.count(".") >= 2
            and 16 <= int(host.split(".")[1]) <= 31
        )
        or host.endswith(".local")
        or host.endswith(".internal")
    ):
        raise ValueError(f"URL targets internal network: {host}")


async def fetch_single_feed(url: str, name: str = "", max_items: int = 30, *, allow_internal: bool = False) -> list[dict[str, str]]:
    """Fetch and parse a single RSS/Atom feed."""
    _validate_feed_url(url, allow_internal=allow_internal)
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(
                url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
            )
            resp.raise_for_status()
        feed = feedparser.parse(resp.text)
        items: list[dict[str, str]] = []
        for entry in feed.entries[:max_items]:
            link = getattr(entry, "link", "")
            if not link:
                continue
            summary = getattr(entry, "summary", "") or getattr(entry, "description", "")
            clean = re.sub(r"<[^>]+>", "", summary)[:300]
            items.append({
                "title": getattr(entry, "title", ""),
                "url": link,
                "snippet": clean,
                "source": name,
            })
        return items
    except Exception as e:
        logger.warning("RSS fetch failed for %s: %s", name or url, e)
        return []


async def _fetch_rss_feeds() -> list[dict[str, str]]:
    """Fetch all configured RSS feeds concurrently, return [{title, url, snippet, source}]."""
    config = get_config()
    sem = asyncio.Semaphore(3)

    async def _fetch_one(src: dict[str, str]) -> list[dict[str, str]]:
        name = src.get("name", "unknown")
        url = _resolve_source_url(src)
        if not url:
            return []
        async with sem:
            return await fetch_single_feed(url, name=name, allow_internal=True)

    results = await asyncio.gather(*[_fetch_one(src) for src in config.ingest.rss_sources])

    all_items: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for batch in results:
        for item in batch:
            if item["url"] not in seen_urls:
                seen_urls.add(item["url"])
                all_items.append(item)

    logger.info("RSS: %d items from %d sources", len(all_items), len(config.ingest.rss_sources))
    return all_items


# --- Collect orchestrator ---

async def collect() -> dict[str, Any]:
    """Fetch all sources and return raw data dict.

    Returns {"github": [...], "github_source": str, "rss": [...]}.
    """
    github_result, rss_items_raw = await asyncio.gather(
        _github_trending(),
        _fetch_rss_feeds(),
        return_exceptions=True,
    )

    # Process GitHub results
    if isinstance(github_result, Exception):
        github_repos, github_source = [], "unavailable"
        source_health.record("GitHub", False, 0)
        logger.warning("GitHub trending failed: %s", github_result)
    else:
        github_repos, github_source = github_result
        source_health.record("GitHub", True, len(github_repos))

    # Process RSS results
    rss_items = rss_items_raw if not isinstance(rss_items_raw, Exception) else []
    if isinstance(rss_items_raw, Exception):
        source_health.record("RSS", False, 0)
        logger.warning("RSS fetch failed: %s", rss_items_raw)
    else:
        source_health.record("RSS", True, len(rss_items))

    logger.info(source_health.summary())

    return {
        "github": github_repos,
        "github_source": github_source,
        "rss": rss_items,
    }
