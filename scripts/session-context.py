#!/usr/bin/env python3
"""SessionStart hook: inject journal context + check today's log status."""

import json
import sys
from datetime import date
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
JOURNAL_README = PROJECT / "journal" / "README.md"


def main():
    lines = []

    # Journal index
    if JOURNAL_README.exists():
        lines.append(JOURNAL_README.read_text())

    # Today's log check
    today = date.today().isoformat()
    today_file = PROJECT / "journal" / f"{today}.md"
    if not today_file.exists():
        lines.append(f"\n**Reminder**: No journal entry for {today} yet. Create one before ending today's work.")
    else:
        lines.append(f"\nJournal entry for {today} exists.")

    output = "\n".join(lines)

    # SessionStart hook expects JSON format
    json.dump({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": output,
        }
    }, sys.stdout)


if __name__ == "__main__":
    main()
