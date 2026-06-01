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
    readme_file = PROJECT / "journal" / "README.md"
    commits = get_today_commits()

    if not commits:
        sys.exit(0)

    msg_parts = []

    # Check 1: detail file must exist
    if not today_file.exists():
        msg_parts.append(
            f"journal-check [REQUIRED]: journal/{today}.md does not exist. "
            f"Create it with task index and detail sections before pushing. "
            f"({len(commits)} commit(s) today)"
        )
    else:
        # Check 2: task count vs commit count
        content = today_file.read_text()
        task_count = content.count("### ")
        if task_count < len(commits):
            msg_parts.append(
                f"journal-check: Today's journal has {task_count} task(s) "
                f"but {len(commits)} commit(s) today. Consider updating."
            )

    # Check 3: README index must have today's entry
    if readme_file.exists():
        readme = readme_file.read_text()
        if today not in readme:
            msg_parts.append(
                f"journal-check [REQUIRED]: journal/README.md has no entry for {today}. "
                f"Add a summary row to the index table."
            )

    if not msg_parts:
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
        RED = "\033[31m"
        RESET = "\033[0m"
        color = RED if "[REQUIRED]" in msg else YELLOW
        print(f"{color}{msg}{RESET}")

    sys.exit(0)


if __name__ == "__main__":
    main()
