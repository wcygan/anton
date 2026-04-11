#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""SessionStart hook: inject the anton ADR index.

Reads `context/adrs/INDEX.md` and prints a trimmed version to stdout so it
lands in the agent's initial context. Lets every Claude Code session (and every
spawned subagent) see prior decisions at turn 0 without the operator typing
them in.

Fail-open: if the index file is missing, empty, or unreadable, the hook exits
0 with no output. Never raises. Capped at 40 body lines so it cannot bloat
the session context window.
"""
import os
import sys
from pathlib import Path

MAX_BODY_LINES = 40


def project_root() -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent.parent


def read_index() -> list[str]:
    path = project_root() / "context" / "adrs" / "INDEX.md"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    return [line for line in text.splitlines() if line.strip()]


def trim(lines: list[str]) -> list[str]:
    """Keep header + table; cap total body length at MAX_BODY_LINES."""
    if len(lines) <= MAX_BODY_LINES:
        return lines

    # Preserve the H1, the "Generated:" line, the header row, and the
    # separator row at the top; truncate the oldest table rows from the middle.
    table_start = next(
        (i for i, line in enumerate(lines) if line.startswith("| #")),
        None,
    )
    if table_start is None:
        return lines[:MAX_BODY_LINES]

    preamble = lines[: table_start + 2]  # header row + separator row
    rows = lines[table_start + 2 :]
    keep_rows = MAX_BODY_LINES - len(preamble) - 1  # -1 for the truncation marker
    if keep_rows < 1:
        keep_rows = 1
    truncated = len(rows) - keep_rows
    if truncated <= 0:
        return lines
    kept = rows[-keep_rows:]
    marker = f"| … | _({truncated} older entries omitted)_ |  |  |  |  |"
    return preamble + [marker] + kept


def main() -> int:
    lines = read_index()
    if not lines:
        return 0

    print("## Anton ADR index (injected at session start)")
    print()
    for line in trim(lines):
        print(line)
    print()
    print(
        "Reminder: ADRs are immutable. Use the `adr` skill (`/adr supersede`) "
        "to revise a decision, never edit the body in place."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
