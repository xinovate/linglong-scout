"""BriefHistory — per-dimension dedup for morning briefs.

Stores each day's output sections as JSON, loads past N days per dimension
to inject as "already reported" context for the next run.
"""

import json
import logging
import re
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

_DEDUP_WINDOWS: dict[str, int] = {
    "关键人物": 14,
    "公司动态": 7,
    "政策动态": 14,
    "应用落地": 7,
}

_DIMENSION_KEYS: dict[str, str] = {
    "关键人物": "关键人物",
    "公司动态": "公司动态",
    "政策动态": "政策动态",
    "应用落地": "应用落地",
}


def parse_sections(output: str) -> dict[str, str]:
    """Parse LLM output into per-dimension sections by ## headers."""
    sections: dict[str, str] = {}
    current_dim: str | None = None
    current_lines: list[str] = []

    for line in output.split("\n"):
        if line.startswith("## "):
            if current_dim and current_lines:
                sections[current_dim] = "\n".join(current_lines).strip()
            dim = line[3:].strip()
            # Normalize: strip emoji prefix for matching
            for key in _DEDUP_WINDOWS:
                if key in dim:
                    current_dim = key
                    break
            else:
                current_dim = dim
            current_lines = []
        elif line.startswith("━━"):
            if current_dim and current_lines:
                sections[current_dim] = "\n".join(current_lines).strip()
            break
        elif current_dim:
            current_lines.append(line)

    if current_dim and current_lines:
        sections[current_dim] = "\n".join(current_lines).strip()

    return sections


class BriefHistory:
    """Per-dimension brief history for deduplication."""

    def __init__(self, history_dir: Path, dedup_windows: dict[str, int] | None = None) -> None:
        self.history_dir = history_dir
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self._dedup_windows = dedup_windows or _DEDUP_WINDOWS

    def load(self) -> dict[str, str]:
        """Load recent history per dimension.

        Returns {dimension: combined_text_with_dates} for dimensions that have history.
        """
        today = date.today()
        result: dict[str, str] = {}

        for dim, window in self._dedup_windows.items():
            sections: list[str] = []
            for i in range(1, window + 1):
                d = today - timedelta(days=i)
                path = self.history_dir / f"{d.isoformat()}.json"
                if not path.exists():
                    continue
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if dim in data and data[dim]:
                        sections.append(f"【{d.isoformat()}】\n{data[dim]}")
                except Exception as e:
                    logger.warning("Failed to read history %s: %s", path, e)

            if sections:
                result[dim] = "\n\n".join(sections)

        return result

    def format_for_prompt(self) -> str:
        """Format history as prompt injection text."""
        history = self.load()
        if not history:
            return ""

        lines = ["## 近期已播报内容（请勿重复报道相同事件）", ""]
        for dim, text in history.items():
            window = self._dedup_windows.get(dim, 7)
            lines.append(f"### {dim}（近 {window} 天）")
            lines.append(text)
            lines.append("")

        return "\n".join(lines)

    def save(self, date_str: str, sections: dict[str, str]) -> None:
        """Save per-dimension sections for a given date."""
        path = self.history_dir / f"{date_str}.json"
        path.write_text(
            json.dumps(sections, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Brief history saved: %s (%d dimensions)", path, len(sections))

    def cleanup(self, max_days: int = 16) -> None:
        """Remove history files older than max_days."""
        cutoff = (date.today() - timedelta(days=max_days)).isoformat()
        removed = 0
        for f in self.history_dir.glob("*.json"):
            if f.stem < cutoff:
                f.unlink()
                removed += 1
        if removed:
            logger.info("Cleaned up %d old history files", removed)

    def get_last_output(self) -> str | None:
        """Return the most recent history file's raw content for fallback."""
        files = sorted(self.history_dir.glob("*.json"), reverse=True)
        if not files:
            return None
        try:
            data = json.loads(files[0].read_text(encoding="utf-8"))
            return "\n\n".join(f"## {k}\n{v}" for k, v in data.items() if v)
        except Exception:
            return None

    def check_overlap(self, new_sections: dict[str, str]) -> list[str]:
        """Check new output sections for overlap with recent history.

        Returns a list of warnings for dimensions with high overlap.
        Uses simple token overlap (jaccard-like) for lightweight detection.
        """
        history = self.load()
        warnings: list[str] = []

        for dim, new_text in new_sections.items():
            old_text = history.get(dim)
            if not old_text or not new_text:
                continue
            new_tokens = _extract_tokens(new_text)
            old_tokens = _extract_tokens(old_text)
            if not new_tokens or not old_tokens:
                continue
            overlap = new_tokens & old_tokens
            ratio = len(overlap) / min(len(new_tokens), len(old_tokens))
            if ratio > 0.4:
                warnings.append(
                    f"{dim}: {ratio:.0%} token overlap ({len(overlap)} shared), "
                    f"possible重复"
                )
        if warnings:
            logger.warning("Dedup check: %s", "; ".join(warnings))
        return warnings


def _extract_tokens(text: str) -> set[str]:
    """Extract meaningful tokens from text for overlap comparison."""
    # Remove markdown table formatting, keep content
    cleaned = re.sub(r"[|\\-─━]", " ", text)
    # Split into words, keep tokens >= 2 chars (catches both en/cn)
    tokens = {w for w in cleaned.split() if len(w) >= 2}
    return tokens
