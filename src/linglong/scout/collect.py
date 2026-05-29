"""Data collection — SearXNG search, GitHub trending, RSS feeds."""

import asyncio
import logging
import re
from datetime import date, timedelta
from typing import Any

import feedparser
import httpx

from linglong.config import get_config
from linglong.scout.package import SourcePackage

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

# Domains that rarely contain actual news
_NOISE_DOMAINS = {
    "baike.baidu.com", "baidu.com", "zdic.net", "wikipedia.org",
    "zhihu.com", "csdn.net", "w3school.com.cn", "iciba.com",
    "collinsdictionary.com", "cambridge.org", "google.com",
    "google.com.hk", "support.google.com", "about.google",
    "m.baidu.com", "baike.com", "m.baike.com",
}


def _is_noise_url(url: str) -> bool:
    """Check if a URL is likely a noise result (dictionary, homepage, etc.)."""
    host = url.split("/")[2] if "//" in url else ""
    return any(host == d or host.endswith("." + d) for d in _NOISE_DOMAINS)


def _is_rsshub_url(url: str) -> bool:
    """Check if a URL points to our RSSHub instance (port 1200)."""
    return ":1200/" in url or url.rstrip("/").endswith(":1200")


async def _github_headers() -> dict[str, str]:
    """Return GitHub API headers with token from gh CLI if available."""
    headers = {"Accept": "application/vnd.github.v3+json"}
    try:
        proc = await asyncio.create_subprocess_exec(
            "gh", "auth", "token",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        token = stdout.decode().strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
    except Exception:
        pass
    return headers


# --- SearXNG ---

async def _searxng_search(query: str, max_results: int = 15) -> list[dict[str, str]]:
    """Search via SearXNG, return [{title, url, snippet}]."""
    config = get_config()
    base_url = config.ingest.searxng_url.rstrip("/")
    timeout = config.ingest.search_timeout

    params: dict[str, Any] = {
        "q": query,
        "format": "json",
        "categories": "general",
    }
    headers: dict[str, str] = {}
    if config.ingest.searxng_api_key:
        headers["Authorization"] = f"Bearer {config.ingest.searxng_api_key}"

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(f"{base_url}/search", params=params, headers=headers)
        response.raise_for_status()

    data = response.json()
    results = []
    for r in data.get("results", [])[:max_results]:
        title = r.get("title", "").strip()
        url = r.get("url", "").strip()
        snippet = r.get("content", "").strip()
        if not title or not url or _is_noise_url(url):
            continue
        results.append({"title": title, "url": url, "snippet": snippet})

    logger.info("SearXNG '%s': %d results (after noise filter)", query, len(results))
    return results


def _dedup_results(results: list[dict[str, str]]) -> list[dict[str, str]]:
    """Deduplicate by URL."""
    seen: set[str] = set()
    deduped: list[dict[str, str]] = []
    for r in results:
        url = r["url"]
        if url not in seen:
            seen.add(url)
            deduped.append(r)
    return deduped


async def _search_all_keywords(package: SourcePackage) -> list[dict[str, str]]:
    """Search all keywords concurrently with semaphore rate limiting."""
    sem = asyncio.Semaphore(5)

    async def _search_one(keyword: str, max_results: int) -> list[dict[str, str]]:
        async with sem:
            try:
                return await _searxng_search(keyword, max_results)
            except Exception as e:
                logger.warning("Search failed for '%s': %s", keyword, e)
                return []

    tasks: list[asyncio.Task] = []
    for query_group in package.search_queries:
        for keyword in query_group.keywords:
            tasks.append(
                asyncio.create_task(
                    _search_one(keyword, query_group.max_results * 2)
                )
            )

    results = await asyncio.gather(*tasks)
    all_results: list[dict[str, str]] = []
    for batch in results:
        all_results.extend(batch)
    return all_results


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
                for attempt_date in [today, today - timedelta(days=1)]:
                    if attempt_date != today and period == "monthly":
                        break
                    file_path = path_fn(attempt_date)
                    url = f"{_OPENGITHUB_API}/{repo}/contents/{file_path}"
                    response = await client.get(url, headers=headers)
                    if response.status_code == 200:
                        break

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

    for full_name, url, total_stars, growth in rows:
        if full_name in seen:
            continue
        seen.add(full_name)

        escaped = re.escape(full_name)
        desc_match = re.search(
            rf"{escaped}.*?项目描述[：:]\s*(.+?)(?:\n|$)",
            md,
            re.DOTALL,
        )
        desc = desc_match.group(1).strip() if desc_match else ""

        raw_growth = growth.replace(",", "")
        raw_stars = total_stars
        if total_stars.endswith("k"):
            raw_stars = str(int(float(total_stars[:-1]) * 1000))

        repos.append({
            "title": f"{full_name} (+{raw_growth}⭐ {growth_label})",
            "url": url,
            "snippet": desc[:200],
            "stars": raw_stars,
            "growth": raw_growth,
            "period": growth_label,
        })

    return repos[:limit]


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

            stars_match = re.search(r'([\d,]+)\s*stars today', block)
            today_stars = stars_match.group(1).replace(',', '') if stars_match else None

            if today_stars:
                repos.append({
                    "title": f"{full_name} (+{today_stars}⭐ 日增长)",
                    "url": f"https://github.com/{full_name}",
                    "snippet": re.sub(r'&[#\w]+;', '', desc)[:200],
                    "stars": today_stars,
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

async def fetch_single_feed(url: str, name: str = "", max_items: int = 30) -> list[dict[str, str]]:
    """Fetch and parse a single RSS/Atom feed."""
    config = get_config()
    if config.ingest.rsshub_access_key and _is_rsshub_url(url):
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}key={config.ingest.rsshub_access_key}"
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
        name = src.get("name", src.get("url", "unknown"))
        url = src.get("url", "")
        if not url:
            return []
        async with sem:
            return await fetch_single_feed(url, name=name)

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

async def collect(package: SourcePackage) -> dict[str, Any]:
    """Fetch all sources and return raw data dict.

    Returns {"searxng": [...], "github": [...], "github_source": str, "rss": [...]}.
    """
    searxng_results, github_result, rss_items_raw = await asyncio.gather(
        _search_all_keywords(package),
        _github_trending(),
        _fetch_rss_feeds(),
        return_exceptions=True,
    )

    # Process SearXNG results
    raw_searxng = searxng_results if not isinstance(searxng_results, Exception) else []
    if isinstance(searxng_results, Exception):
        source_health.record("SearXNG", False, 0)
        logger.warning("SearXNG search failed: %s", searxng_results)
    all_results = _dedup_results(raw_searxng)
    source_health.record("SearXNG", not isinstance(searxng_results, Exception), len(all_results))
    logger.info("After dedup: %d unique SearXNG results", len(all_results))

    # Process GitHub results
    if isinstance(github_result, Exception):
        github_repos, github_source = [], "unavailable"
        source_health.record("GitHub", False, 0)
        logger.warning("GitHub trending failed: %s", github_result)
    else:
        github_repos, github_source = github_result
        source_health.record("GitHub", True, len(github_repos))

    # Process RSS results (cross-dedup against SearXNG)
    rss_items = rss_items_raw if not isinstance(rss_items_raw, Exception) else []
    if isinstance(rss_items_raw, Exception):
        source_health.record("RSS", False, 0)
        logger.warning("RSS fetch failed: %s", rss_items_raw)
    else:
        source_health.record("RSS", True, len(rss_items))
    searxng_urls = {r["url"] for r in all_results}
    rss_items = [r for r in rss_items if r["url"] not in searxng_urls]
    logger.info("RSS: %d items fetched (after cross-dedup)", len(rss_items))

    logger.info(source_health.summary())

    return {
        "searxng": all_results,
        "github": github_repos,
        "github_source": github_source,
        "rss": rss_items,
    }
