"""Feedback store — user preference tracking for scout results."""

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS ingest_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_hash TEXT NOT NULL,
    feedback TEXT NOT NULL,
    tags TEXT,
    created_at TEXT NOT NULL
)
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_feedback_hash ON ingest_feedback(content_hash)
"""


class FeedbackStore:
    """Persist and query user feedback on scout results."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            db_path = Path.home() / "linglong" / "data" / "ingest_feedback.db"
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_table()

    def _ensure_table(self) -> None:
        with self._connect() as conn:
            conn.execute(_CREATE_TABLE_SQL)
            conn.execute(_CREATE_INDEX_SQL)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def record(
        self,
        content_hash: str,
        feedback: str,
        tags: list[str] | None = None,
    ) -> None:
        """Record feedback for an scout result.

        Args:
            content_hash: Hash identifying the news item.
            feedback: "useful" or "not_interested".
            tags: Tags associated with the news item.
        """
        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO ingest_feedback (content_hash, feedback, tags, created_at) "
                "VALUES (?, ?, ?, ?)",
                (content_hash, feedback, json.dumps(tags or []), now),
            )
            conn.commit()

        logger.info("Recorded feedback: %s for %s (tags=%s)", feedback, content_hash[:8], tags)

    def get_preferences(self) -> dict[str, float]:
        """Compute preference weights from feedback history.

        Returns:
            Tag → weight mapping. Positive = preferred, negative = avoided.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT feedback, tags FROM ingest_feedback"
            ).fetchall()

        tag_scores: dict[str, list[float]] = {}
        for row in rows:
            feedback = row["feedback"]
            tags = json.loads(row["tags"] or "[]")
            score = 1.0 if feedback == "useful" else -1.0
            for tag in tags:
                if tag not in tag_scores:
                    tag_scores[tag] = []
                tag_scores[tag].append(score)

        preferences: dict[str, float] = {}
        for tag, scores in tag_scores.items():
            # Normalize to [-1, 1]
            preferences[tag] = sum(scores) / len(scores) if scores else 0.0

        return preferences

    def get_preference_text(self) -> str:
        """Generate preference summary text for LLM prompt injection."""
        prefs = self.get_preferences()
        if not prefs:
            return ""

        lines = ["用户历史偏好："]
        # Sort by absolute weight (most opinionated first)
        for tag, weight in sorted(prefs.items(), key=lambda x: abs(x[1]), reverse=True)[:8]:
            useful = int(sum(1 for _ in []))  # placeholder
            if weight > 0:
                lines.append(f"- {tag} 类型：偏好（权重 {weight:.1f}）")
            elif weight < 0:
                lines.append(f"- {tag} 类型：不关心（权重 {weight:.1f}）")

        lines.append("请根据偏好调整精选权重。")
        return "\n".join(lines)
