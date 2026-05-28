#!/usr/bin/env python3
"""Doc sync checker for pre-commit and Claude Code hooks.

Checks staged files against docs/doc-map.yaml mappings. If code is
changed without corresponding doc updates, outputs a warning.

Exit code is always 0 — never blocks a commit.

Usage:
  python scripts/doc-check.py              # plain text (git hook)
  python scripts/doc-check.py --claude-hook # JSON (Claude hook)
"""

import json
import re
import subprocess
import sys
from pathlib import Path


def get_staged_files() -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--staged", "--name-only"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]


def parse_yaml_mappings(text: str) -> list[dict]:
    """Minimal YAML parser for doc-map.yaml flat structure."""
    mappings = []
    current = None

    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue

        m = re.match(r"[- ]*code:\s*(.*)", stripped)
        if m:
            current = {"code": m.group(1).strip(), "docs": []}
            mappings.append(current)
            continue

        if current is not None:
            m = re.match(r"-\s*(.+)", stripped)
            if m and not stripped.startswith("code:") and not stripped.startswith("docs:"):
                val = m.group(1).strip()
                current["docs"].append(val)

    return mappings


def load_doc_map() -> list[dict]:
    map_path = Path("docs/doc-map.yaml")
    if not map_path.exists():
        return []
    text = map_path.read_text()
    return parse_yaml_mappings(text)


def check(staged: list[str], mappings: list[dict]) -> list[str]:
    warnings = []
    staged_set = set(staged)

    for mapping in mappings:
        code_prefix = mapping["code"]
        doc_paths = mapping["docs"]

        if not code_prefix:
            continue

        code_hits = [f for f in staged if f.startswith(code_prefix)]
        if not code_hits:
            continue

        doc_staged = False
        for doc_path in doc_paths:
            if doc_path.endswith("/"):
                if any(f.startswith(doc_path) for f in staged_set):
                    doc_staged = True
                    break
            else:
                if doc_path in staged_set:
                    doc_staged = True
                    break

        if not doc_staged:
            code_files = ", ".join(code_hits[:3])
            if len(code_hits) > 3:
                code_files += f" (+{len(code_hits) - 3} more)"
            doc_list = ", ".join(doc_paths)
            warnings.append(
                f"  code changed: {code_files}\n"
                f"  → suggest checking: {doc_list}"
            )

    return warnings


def main():
    claude_hook = "--claude-hook" in sys.argv

    staged = get_staged_files()
    if not staged:
        sys.exit(0)

    code_extensions = {".py", ".ts", ".js", ".go", ".rs"}
    has_code = any(
        Path(f).suffix in code_extensions for f in staged
    )
    if not has_code:
        sys.exit(0)

    mappings = load_doc_map()
    if not mappings:
        sys.exit(0)

    warnings = check(staged, mappings)
    if not warnings:
        sys.exit(0)

    if claude_hook:
        msg = "doc-check: code changed without doc updates\n" + "\n".join(warnings)
        json.dump({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": msg,
            }
        }, sys.stdout)
    else:
        YELLOW = "\033[33m"
        RESET = "\033[0m"
        print(f"{YELLOW}doc-check: code changed without doc updates{RESET}")
        for w in warnings:
            print(f"{YELLOW}{w}{RESET}")

    sys.exit(0)


if __name__ == "__main__":
    main()
