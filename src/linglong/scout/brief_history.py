"""BriefHistory — per-dimension dedup for morning briefs.

Stores each day's output sections in Redis, loads past N days per dimension
to inject as "already reported" context for the next run.
"""

import logging
import re
from datetime import date

from linglong.scout.cache import (
    cleanup_history,
    get_last_history,
    load_history,
    save_history,
)

logger = logging.getLogger(__name__)

_DEDUP_WINDOWS: dict[str, int] = {
    "关键人物": 14,
    "公司动态": 7,
    "政策动态": 14,
    "应用落地": 7,
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
    """Per-dimension brief history for deduplication, backed by Redis."""

    def __init__(
        self, history_dir: object = None, dedup_windows: dict[str, int] | None = None,
    ) -> None:
        self._dedup_windows = dedup_windows or _DEDUP_WINDOWS

    def load(self) -> dict[str, str]:
        """Load recent history per dimension.

        Returns {dimension: combined_text_with_dates} for dimensions that have history.
        """
        return load_history(self._dedup_windows)

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
        save_history(date_str, sections, self._dedup_windows)

    def cleanup(self) -> None:
        """Remove history older than retention window."""
        cleanup_history()

    def get_last_output(self) -> str | None:
        """Return the most recent history content for fallback."""
        return get_last_history()

    def check_overlap(self, new_sections: dict[str, str]) -> list[str]:
        """Check new output sections for overlap with recent history."""
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
    cleaned = re.sub(r"[|\\-─━]", " ", text)
    return {w for w in cleaned.split() if len(w) >= 2}
