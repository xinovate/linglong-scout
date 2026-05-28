#!/usr/bin/env python3
"""Privacy checker for pre-commit hook.

Scans staged files for sensitive information: IP addresses, real domains,
API keys, and other private data that should not appear in the repo.

Exit code 1 blocks the commit if violations are found.

Usage:
  python scripts/privacy-check.py              # pre-commit hook
  python scripts/privacy-check.py --claude-hook # Claude PreToolUse hook
"""

import json
import re
import subprocess
import sys
from pathlib import Path

# Patterns that indicate sensitive information
_PATTERNS: list[tuple[str, re.Pattern, str]] = [
    (
        "IPv4 address",
        re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"),
        "Use 'localhost' or '192.168.x.x' examples",
    ),
    (
        "private domain",
        re.compile(r"\b(?:redacted-server-ip|redacted-domain)\b"),
        "Use descriptive placeholders instead of redacted-* tokens",
    ),
]

# Files/directories to skip
_SKIP_PREFIXES = (
    ".git/",
    "scripts/privacy-check.py",
    ".claude/rules/privacy.md",
)

# Allowlisted patterns (false positives)
_ALLOWLIST = (
    "127.0.0.1",
    "0.0.0.0",
    "255.255.255",
    "192.168.1.",
    "example.com",
    "localhost",
    "your-domain",
    "your-server",
    "your-secret",
    "api.example.com",
    "baidu.com",
    "redhat.com",
)


def get_staged_content() -> dict[str, str]:
    """Get staged file content via git show."""
    result = subprocess.run(
        ["git", "diff", "--staged", "--name-only"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return {}

    files = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
    content: dict[str, str] = {}

    for filepath in files:
        if any(filepath.startswith(skip) for skip in _SKIP_PREFIXES):
            continue
        if not filepath.endswith((".py", ".md", ".yml", ".yaml", ".txt", ".json", ".toml", ".cfg")):
            continue

        show = subprocess.run(
            ["git", "show", f":{filepath}"],
            capture_output=True,
            text=True,
        )
        if show.returncode == 0:
            content[filepath] = show.stdout

    return content


def scan(content: dict[str, str]) -> list[dict]:
    """Scan file contents for privacy violations."""
    violations = []

    for filepath, text in content.items():
        for line_num, line in enumerate(text.split("\n"), 1):
            for name, pattern, suggestion in _PATTERNS:
                for match in pattern.finditer(line):
                    value = match.group(0)
                    if any(allow in value for allow in _ALLOWLIST):
                        continue
                    # Skip common version numbers like Python version 3.12
                    if name == "IPv4 address" and re.match(r"\b\d+\.\d+\.\d+\b", value):
                        # Check if it's in a version-like context
                        context = line[max(0, match.start() - 10):match.end() + 10]
                        if re.search(r"python[.:]?\s*\d", context, re.IGNORECASE):
                            continue
                    violations.append({
                        "file": filepath,
                        "line": line_num,
                        "type": name,
                        "value": value,
                        "suggestion": suggestion,
                    })

    return violations


def main():
    claude_hook = "--claude-hook" in sys.argv

    content = get_staged_content()
    if not content:
        sys.exit(0)

    violations = scan(content)
    if not violations:
        sys.exit(0)

    if claude_hook:
        lines = [f"  {v['file']}:{v['line']} [{v['type']}] {v['value']}" for v in violations]
        msg = f"privacy-check: {len(violations)} violation(s) found\n" + "\n".join(lines)
        json.dump({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": msg,
            }
        }, sys.stdout)
    else:
        RED = "\033[31m"
        RESET = "\033[0m"
        print(f"{RED}privacy-check: {len(violations)} violation(s) found — commit BLOCKED{RESET}")
        for v in violations:
            print(f"  {RED}{v['file']}:{v['line']}{RESET} [{v['type']}] {v['value']}")
            print(f"    → {v['suggestion']}")

    sys.exit(1)


if __name__ == "__main__":
    main()
