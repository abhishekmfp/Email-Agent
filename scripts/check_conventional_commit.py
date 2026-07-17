#!/usr/bin/env python
"""Validate that a commit message follows Conventional Commits.

M8 hardening gate (Q4): local + CI enforcement, Python-native (no Node/commitlint).
Used by:
  * a pre-commit `commit-msg` hook (`.pre-commit-config.yaml`)
  * CI (GitHub Actions step calls this against each PR commit)

Conventional Commits spec (summary):
    <type>[optional scope]: <description>
    [optional body]
    [optional footer(s)]

Types: feat, fix, docs, style, refactor, perf, test, build, ci, chore, revert.
Merge/squash/revert GitHub auto-messages are allowed through.

Usage:
    python scripts/check_conventional_commit.py <path-to-commit-message-file>
    echo "$MSG" | python scripts/check_conventional_commit.py -
Exit 0 = valid, 1 = invalid (prints the reason to stderr).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Allowed primary types (Conventional Commits + common extensions).
ALLOWED_TYPES = {
    "feat", "fix", "docs", "style", "refactor", "perf",
    "test", "build", "ci", "chore", "revert",
}

# GitHub-generated messages that are not conventional but must pass CI.
NON_CONVENTIONAL_ALLOWED = re.compile(
    r"^(Merge (branch|pull request)|Revert \"|Squash (merge|PR)|This reverts commit )",
    re.IGNORECASE,
)

# Header: type[optional scope]: description
HEADER_RE = re.compile(
    r"^(?P<type>[a-z]+)"          # type
    r"(?P<scope>\([^\n]+\))?"      # optional (scope)
    r"(?P<break>!)?"               # optional breaking-change marker
    r":\s+(?P<desc>\S.*)$",        # colon + space + description
)


def validate(message: str) -> tuple[bool, str]:
    """Return (ok, reason). reason is empty when ok."""
    # Normalize: strip a trailing comment block (git may append # comments
    # in some flows, though commit-msg hook input usually has them stripped).
    lines = [ln for ln in message.splitlines() if not ln.startswith("#")]
    if not lines:
        return False, "empty commit message"

    header = lines[0].strip()
    if not header:
        return False, "empty commit message (first line is blank)"

    if NON_CONVENTIONAL_ALLOWED.match(header):
        return True, ""

    m = HEADER_RE.match(header)
    if not m:
        return False, (
            f"header {header!r} is not Conventional Commits. "
            "Expected: <type>[optional scope]: <description>"
        )

    ctype = m.group("type")
    if ctype not in ALLOWED_TYPES:
        return False, (
            f"type {ctype!r} not in allowed set {sorted(ALLOWED_TYPES)}"
        )

    desc = m.group("desc")
    if len(desc) < 3:
        return False, "description is too short (min 3 chars)"

    if desc.endswith("."):
        return False, "description must not end with a period"

    # Body/footer lines (if any) — free form, just ensure no stray header re-use.
    return True, ""


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_conventional_commit.py <file> | -", file=sys.stderr)
        return 2

    arg = argv[1]
    if arg == "-":
        message = sys.stdin.read()
    else:
        message = Path(arg).read_text(encoding="utf-8", errors="replace")

    ok, reason = validate(message)
    if ok:
        print("commit message OK")
        return 0
    print(f"INVALID commit message: {reason}", file=sys.stderr)
    print(
        "Example:  feat(m8): add per-layer coverage gate",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
