#!/usr/bin/env python3
"""Journal check for git push hook.

Reminds to update today's journal before pushing code.
Exit code is always 0 — never blocks a push.

Usage:
  python scripts/journal-check.py              # plain text
  python scripts/journal-check.py --claude-hook # JSON (Claude hook)
"""

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent


def get_today_commits() -> list[str]:
    """Get commit messages from today."""
    today = date.today().isoformat()
    result = subprocess.run(
        ["git", "log", "--since", today, "--oneline", "--no-merges"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]


def main():
    claude_hook = "--claude-hook" in sys.argv
    today = date.today().isoformat()
    today_file = PROJECT / "journal" / f"{today}.md"
    commits = get_today_commits()

    if not commits:
        sys.exit(0)

    msg_parts = []
    if not today_file.exists():
        msg_parts.append(
            f"journal-check: No journal entry for {today}. "
            f"You have {len(commits)} commit(s) today. "
            f"Consider creating journal/{today}.md before pushing."
        )
    else:
        content = today_file.read_text()
        task_count = content.count("### ")
        if task_count < len(commits):
            msg_parts.append(
                f"journal-check: Today's journal has {task_count} task(s) "
                f"but {len(commits)} commit(s) today. Consider updating."
            )
        else:
            sys.exit(0)

    msg = "\n".join(msg_parts)

    if claude_hook:
        json.dump({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": msg,
            }
        }, sys.stdout)
    else:
        YELLOW = "\033[33m"
        RESET = "\033[0m"
        print(f"{YELLOW}{msg}{RESET}")

    sys.exit(0)


if __name__ == "__main__":
    main()
