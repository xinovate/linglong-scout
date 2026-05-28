"""IngestAgent — LLM-driven morning brief generator.

Pre-searches all keywords via SearXNG, then calls LLM once with the full
context to produce a structured morning brief in markdown.
"""

import asyncio
import json
import logging
import re
from datetime import UTC, date, timedelta
from pathlib import Path
from typing import Any

import feedparser
import httpx

from linglong.config import get_config
from linglong.scout.brief_history import BriefHistory, parse_sections
from linglong.scout.feedback import FeedbackStore
from linglong.scout.package import SourcePackage

logger = logging.getLogger(__name__)

_PROMPT_DIR = Path(__file__).parent / "prompts"
_DATA_DIR = Path(__file__).parent


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


_source_health = SourceHealth()

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


def _github_headers() -> dict[str, str]:
    """Return GitHub API headers with token from gh CLI if available."""
    headers = {"Accept": "application/vnd.github.v3+json"}
    try:
        import subprocess
        token = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
    except Exception:
        pass
    return headers


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


def _denormalize(items: list[dict[str, Any]], source: str) -> list[dict[str, str]]:
    """Convert normalized raw items back to source-specific format.

    Normalized items have extra fields in "extra" dict. This extracts
    them back to top-level so format functions can access them directly.
    """
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


_GITHUB_TOPICS = ["ai", "llm", "ai-agent", "machine-learning", "deep-learning"]
_OPENGITHUB_API = "https://api.github.com/repos/OpenGithubs"

# Period → (repo suffix, path builder, growth label)
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

    Priority: OpenGithubs (raw markdown) → wangchujiang.com (HTML) → GitHub Search API.

    Returns (repos, source) where source indicates the data origin.
    """
    if limits is None:
        config = get_config()
        limits = config.ingest.github_trending_limits

    # Source 1: OpenGithubs
    repos, source = await _fetch_opengithubs(limits)
    if repos:
        return repos, source

    # Source 2: wangchujiang.com (daily only)
    repos = await _fetch_trending_html(limits.get("daily", 10))
    if repos:
        return repos, "wangchujiang"

    # Source 3: GitHub Search API
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
    headers = _github_headers()

    for period, (repo, path_fn, growth_label) in _TREND_PERIODS.items():
        limit = limits.get(period, 0)
        if limit <= 0:
            continue

        path = path_fn(today)

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                # Try today, then yesterday for daily/weekly
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

    # Match table rows: | N | [owner/repo](url) | stars | 🔺growth |
    rows = re.findall(
        r'\|\s*\d+\s*\|\s*\[([^\]]+)\]\(([^)]+)\)\s*\|\s*([\d.k]+)\s*\|\s*🔺?(\d[\d,]*)\s*\|',
        md,
    )

    for full_name, url, total_stars, growth in rows:
        if full_name in seen:
            continue
        seen.add(full_name)

        # Extract description from detail sections below the table
        desc_match = re.search(
            rf"re.escape(full_name).*?项目描述[：:]\s*(.+?)(?:\n|$)",
            md,
            re.DOTALL,
        )
        desc = desc_match.group(1).strip() if desc_match else ""

        # Normalize star count (e.g. "21.7k" → "21700")
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
        headers = _github_headers()

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

    # Group by period
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


async def _fetch_rss_feeds() -> list[dict[str, str]]:
    """Fetch all configured RSS feeds concurrently, return [{title, url, snippet, source}]."""
    config = get_config()
    sem = asyncio.Semaphore(3)

    async def _fetch_one(src: dict[str, str]) -> list[dict[str, str]]:
        name = src.get("name", src.get("url", "unknown"))
        url = src.get("url", "")
        if not url:
            return []
        if config.ingest.rsshub_access_key and _is_rsshub_url(url):
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}key={config.ingest.rsshub_access_key}"
        async with sem:
            try:
                async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                    resp = await client.get(
                        url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
                    )
                    resp.raise_for_status()
                feed = feedparser.parse(resp.text)
                items: list[dict[str, str]] = []
                for entry in feed.entries[:30]:
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
                logger.warning("RSS fetch failed for %s: %s", name, e)
                return []

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


def _load_company_snapshot() -> dict[str, Any]:
    """Load company funding/valuation snapshot."""
    config = get_config()
    path = Path(config.ingest.company_snapshot_path).expanduser()
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


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

    async def collect(self, package: SourcePackage) -> dict[str, Any]:
        """Fetch all sources and return raw data dict (no LLM call).

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
            _source_health.record("SearXNG", False, 0)
            logger.warning("SearXNG search failed: %s", searxng_results)
        all_results = _dedup_results(raw_searxng)
        _source_health.record("SearXNG", not isinstance(searxng_results, Exception), len(all_results))
        logger.info("After dedup: %d unique SearXNG results", len(all_results))

        # Process GitHub results
        if isinstance(github_result, Exception):
            github_repos, github_source = [], "unavailable"
            _source_health.record("GitHub", False, 0)
            logger.warning("GitHub trending failed: %s", github_result)
        else:
            github_repos, github_source = github_result
            _source_health.record("GitHub", True, len(github_repos))

        # Process RSS results (cross-dedup against SearXNG)
        rss_items = rss_items_raw if not isinstance(rss_items_raw, Exception) else []
        if isinstance(rss_items_raw, Exception):
            _source_health.record("RSS", False, 0)
            logger.warning("RSS fetch failed: %s", rss_items_raw)
        else:
            _source_health.record("RSS", True, len(rss_items))
        searxng_urls = {r["url"] for r in all_results}
        rss_items = [r for r in rss_items if r["url"] not in searxng_urls]
        logger.info("RSS: %d items fetched (after cross-dedup)", len(rss_items))

        logger.info(_source_health.summary())

        return {
            "searxng": all_results,
            "github": github_repos,
            "github_source": github_source,
            "rss": rss_items,
        }

    async def run(self, package: SourcePackage) -> str:
        """Full pipeline: collect → store raw → format → LLM → brief."""
        raw = await self.collect(package)
        today = date.today().isoformat()

        from linglong.scout.raw_store import store_raw
        store_raw(
            target_date=today,
            searxng=raw["searxng"],
            github=raw["github"],
            rss=raw["rss"],
            github_source=raw["github_source"],
        )

        return self._generate(package, raw)

    def run_from_raw(self, package: SourcePackage, raw: dict[str, Any]) -> str:
        """Generate brief from pre-collected raw data (skip collection)."""
        return self._generate(package, raw)

    def _generate(self, package: SourcePackage, raw: dict[str, Any]) -> str:
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
            pref = self.feedback_store.get_preference_text()
            if pref:
                preference_section = f"\n## 用户偏好\n\n{pref}"

        history_section = ""
        if self.brief_history:
            history_text = self.brief_history.format_for_prompt()
            if history_text:
                history_section = f"\n{history_text}"

        snapshot = _load_company_snapshot()
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
