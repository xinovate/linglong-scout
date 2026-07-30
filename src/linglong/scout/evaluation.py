"""Deterministic checks for generated morning briefs."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_SECTION_SPECS = {
    "关键人物": "table",
    "行业要闻": "table",
    "学术前沿": "table",
    "融资动态": "bullet",
    "政策动态": "bullet",
    "开源趋势": "ordered",
    "今日最有价值信息": "top5",
}
_HEADING_RE = re.compile(r"^#{2,3}\s+(.+?)\s*$")
_LINK_RE = re.compile(r"\[[^\]]+\]\((https?://[^)\s]+)\)")
_TABLE_SEPARATOR_RE = re.compile(r"^\|\s*:?-{3,}")
_BULLET_RE = re.compile(r"^\s*-\s+\S", re.MULTILINE)
_ORDERED_RE = re.compile(r"^\s*\d+\.\s+\S", re.MULTILINE)
_STAR_METRIC_RE = re.compile(r"([+]?\d[\d,.]*[kKmM]?)\s*⭐")
_CIRCLED_DIGITS = frozenset("①②③④⑤")
_IGNORED_QUERY_KEYS = frozenset({"f"})


@dataclass(frozen=True)
class CheckResult:
    """One deterministic evaluation result."""

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class EvaluationReport:
    """Evaluation results for one historical brief."""

    target_date: str
    checks: tuple[CheckResult, ...]

    @property
    def passed(self) -> bool:
        """Return whether all checks passed."""
        return all(check.passed for check in self.checks)

    def to_dict(self) -> dict[str, Any]:
        """Convert the report to a JSON-serializable dict."""
        return {
            "target_date": self.target_date,
            "passed": self.passed,
            "checks": [asdict(check) for check in self.checks],
        }


def load_raw_snapshot(raw_dir: str | Path, target_date: str) -> dict[str, Any]:
    """Load one cold-storage raw snapshot without Redis or network access."""
    base = Path(raw_dir).expanduser()
    result: dict[str, Any] = {"rss": [], "github": [], "github_source": ""}

    for source in ("rss", "github"):
        path = base / f"{target_date}_{source}.json"
        if path.exists():
            result[source] = json.loads(path.read_text(encoding="utf-8"))

    meta_path = base / f"{target_date}_meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        result["github_source"] = meta.get("github_source", "")

    return result


def evaluate_brief(
    output: str,
    raw: dict[str, Any],
    target_date: str,
) -> EvaluationReport:
    """Evaluate one generated brief against its frozen raw input."""
    evaluation_date = date.fromisoformat(target_date)
    sections = _split_sections(output)
    checks = [
        _check_required_sections(sections),
        _check_section_formats(sections),
        _check_section_limits(sections),
        _check_top5(sections),
        _check_link_provenance(output, raw),
        _check_link_timeliness(output, raw, evaluation_date),
        _check_cross_section_duplicates(sections),
        _check_github_input_quality(raw),
        _check_github_top8(sections, raw),
        _check_github_metric_fidelity(sections, raw),
    ]
    return EvaluationReport(target_date=target_date, checks=tuple(checks))


def _split_sections(output: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None

    for line in output.splitlines():
        heading = _HEADING_RE.match(line)
        if heading:
            current = _match_section(heading.group(1))
            if current:
                sections.setdefault(current, [])
            continue
        if current:
            sections[current].append(line)

    return {name: "\n".join(lines).strip() for name, lines in sections.items()}


def _match_section(heading: str) -> str | None:
    for name in _SECTION_SPECS:
        if name in heading:
            return name
    return None


def _check_required_sections(sections: dict[str, str]) -> CheckResult:
    missing = [name for name in _SECTION_SPECS if name not in sections]
    return CheckResult(
        "required_sections",
        not missing,
        "all sections present" if not missing else f"missing: {', '.join(missing)}",
    )


def _check_section_formats(sections: dict[str, str]) -> CheckResult:
    failures: list[str] = []
    for name, expected in _SECTION_SPECS.items():
        content = sections.get(name, "")
        if not content:
            continue
        if expected == "table" and _table_row_count(content) == 0:
            failures.append(f"{name}: no table rows")
        elif (
            expected == "bullet"
            and not _BULLET_RE.search(content)
            and "无重大动态" not in content
        ):
            failures.append(f"{name}: no bullet list")
        elif (
            expected == "ordered"
            and not _ORDERED_RE.search(content)
            and "无重大动态" not in content
        ):
            failures.append(f"{name}: no ordered list")
    return CheckResult(
        "section_formats",
        not failures,
        "formats valid" if not failures else "; ".join(failures),
    )


def _table_row_count(content: str) -> int:
    rows = [
        line
        for line in content.splitlines()
        if line.strip().startswith("|") and not _TABLE_SEPARATOR_RE.match(line.strip())
    ]
    return max(0, len(rows) - 1)


def _check_section_limits(sections: dict[str, str]) -> CheckResult:
    industry = _table_row_count(sections.get("行业要闻", ""))
    papers = _table_row_count(sections.get("学术前沿", ""))
    failures = []
    if industry > 12:
        failures.append(f"行业要闻={industry}>12")
    if papers > 8:
        failures.append(f"学术前沿={papers}>8")
    return CheckResult(
        "section_limits",
        not failures,
        "section limits valid" if not failures else "; ".join(failures),
    )


def _check_top5(sections: dict[str, str]) -> CheckResult:
    found = sorted(set(sections.get("今日最有价值信息", "")) & _CIRCLED_DIGITS)
    return CheckResult(
        "top5_complete",
        len(found) == 5,
        f"found {len(found)} of 5 entries",
    )


def _raw_url_map(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    items = [*raw.get("rss", []), *raw.get("github", [])]
    return {
        _canonical_url(item.get("url", "")): item
        for item in items
        if item.get("url")
    }


def _canonical_url(url: str) -> str:
    parts = urlsplit(url)
    hostname = (parts.hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    port = f":{parts.port}" if parts.port else ""
    query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if key.lower() not in _IGNORED_QUERY_KEYS
            and not key.lower().startswith("utm_")
        ]
    )
    return urlunsplit(
        (
            parts.scheme.lower(),
            f"{hostname}{port}",
            parts.path.rstrip("/") or "/",
            query,
            "",
        )
    )


def _check_link_provenance(output: str, raw: dict[str, Any]) -> CheckResult:
    output_urls = set(_LINK_RE.findall(output))
    raw_urls = _raw_url_map(raw)
    unknown = sorted(url for url in output_urls if _canonical_url(url) not in raw_urls)
    return CheckResult(
        "link_provenance",
        not unknown,
        "all links come from raw input"
        if not unknown
        else f"unknown links: {', '.join(unknown)}",
    )


def _check_link_timeliness(
    output: str,
    raw: dict[str, Any],
    target_date: date,
) -> CheckResult:
    earliest = target_date - timedelta(days=7)
    stale: list[str] = []
    url_map = _raw_url_map(raw)

    for url in set(_LINK_RE.findall(output)):
        published = url_map.get(_canonical_url(url), {}).get("published", "")
        if not published:
            continue
        try:
            published_date = date.fromisoformat(str(published)[:10])
        except ValueError:
            continue
        if published_date < earliest or published_date > target_date:
            stale.append(url)

    return CheckResult(
        "link_timeliness",
        not stale,
        "linked items are within 7 days"
        if not stale
        else f"out-of-window links: {', '.join(sorted(stale))}",
    )


def _check_cross_section_duplicates(sections: dict[str, str]) -> CheckResult:
    seen: dict[str, str] = {}
    duplicates: list[str] = []

    for name, content in sections.items():
        if name == "今日最有价值信息":
            continue
        for url in set(_LINK_RE.findall(content)):
            canonical_url = _canonical_url(url)
            if canonical_url in seen:
                duplicates.append(f"{url} ({seen[canonical_url]} / {name})")
            else:
                seen[canonical_url] = name

    return CheckResult(
        "cross_section_duplicates",
        not duplicates,
        "no cross-section duplicate links"
        if not duplicates
        else f"duplicates: {'; '.join(sorted(duplicates))}",
    )


def _check_github_top8(
    sections: dict[str, str],
    raw: dict[str, Any],
) -> CheckResult:
    expected = _github_daily_top8(raw)
    expected_urls = [item.get("url", "") for item in expected if item.get("url")]
    actual_urls = _LINK_RE.findall(sections.get("开源趋势", ""))
    passed = [_canonical_url(url) for url in actual_urls] == [
        _canonical_url(url) for url in expected_urls
    ]
    return CheckResult(
        "github_daily_top8",
        passed,
        f"expected {expected_urls}, got {actual_urls}",
    )


def _check_github_input_quality(raw: dict[str, Any]) -> CheckResult:
    expected = _github_daily_top8(raw)
    valid_growth = sum(
        _is_positive_star_value(_github_metric(item, "growth"))
        for item in expected
    )
    valid_stars = sum(
        _is_positive_star_value(_github_metric(item, "stars"))
        for item in expected
    )
    source = str(raw.get("github_source") or "unknown")
    passed = bool(expected) and valid_growth == len(expected) and valid_stars == len(expected)
    return CheckResult(
        "github_input_quality",
        passed,
        (
            f"source={source}, daily_items={len(expected)}, "
            f"growth_valid={valid_growth}/{len(expected)}, "
            f"total_stars_valid={valid_stars}/{len(expected)}"
        ),
    )


def _check_github_metric_fidelity(
    sections: dict[str, str],
    raw: dict[str, Any],
) -> CheckResult:
    expected = _github_daily_top8(raw)
    invalid_raw = [
        item.get("url", "")
        for item in expected
        if not _is_positive_star_value(_github_metric(item, "growth"))
        or not _is_positive_star_value(_github_metric(item, "stars"))
    ]
    if invalid_raw:
        return CheckResult(
            "github_metric_fidelity",
            False,
            f"raw metrics invalid: {', '.join(invalid_raw)}",
        )

    lines_by_url: dict[str, str] = {}
    for line in sections.get("开源趋势", "").splitlines():
        for url in _LINK_RE.findall(line):
            lines_by_url[_canonical_url(url)] = line

    failures: list[str] = []
    for item in expected:
        url = str(item.get("url", ""))
        line = lines_by_url.get(_canonical_url(url), "")
        actual = [
            _normalize_star_value(value)
            for value in _STAR_METRIC_RE.findall(line)
        ]
        expected_metrics = [
            _normalize_star_value(_github_metric(item, "growth")),
            _normalize_star_value(_github_metric(item, "stars")),
        ]
        if actual[:2] != expected_metrics:
            failures.append(f"{url}: expected {expected_metrics}, got {actual[:2]}")

    return CheckResult(
        "github_metric_fidelity",
        not failures,
        "GitHub growth and total stars match raw input"
        if not failures
        else "; ".join(failures),
    )


def _github_daily_top8(raw: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        (
            item
            for item in raw.get("github", [])
            if _github_period(item) == "日增长"
        ),
        key=_github_growth,
        reverse=True,
    )[:8]


def _github_period(item: dict[str, Any]) -> str:
    return str(item.get("extra", {}).get("period") or item.get("period") or "")


def _github_metric(item: dict[str, Any], name: str) -> str:
    return str(item.get("extra", {}).get(name) or item.get(name) or "").strip()


def _github_growth(item: dict[str, Any]) -> int:
    value = _github_metric(item, "growth")
    digits = re.sub(r"\D", "", value)
    return int(digits) if digits else 0


def _normalize_star_value(value: str) -> str:
    return value.lower().replace(",", "").lstrip("+")


def _is_positive_star_value(value: str) -> bool:
    normalized = _normalize_star_value(value)
    match = re.fullmatch(r"(\d+(?:\.\d+)?)[km]?", normalized)
    return bool(match and float(match.group(1)) > 0)


def main() -> None:
    """Evaluate a saved brief against one cold-storage raw snapshot."""
    parser = argparse.ArgumentParser(description="Evaluate a Scout morning brief")
    parser.add_argument("--brief", required=True, type=Path)
    parser.add_argument("--date", required=True)
    parser.add_argument("--raw-dir", default="~/linglong/data/raw")
    args = parser.parse_args()

    output = args.brief.read_text(encoding="utf-8")
    raw = load_raw_snapshot(args.raw_dir, args.date)
    report = evaluate_brief(output, raw, args.date)
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    raise SystemExit(0 if report.passed else 1)


if __name__ == "__main__":
    main()
