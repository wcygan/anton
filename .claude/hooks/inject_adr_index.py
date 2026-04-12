#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""SessionStart hook: inject the anton ADR index by scanning ADR files directly.

Globs `context/adrs/NNNN-*.md`, parses YAML-ish frontmatter, and prints a
trimmed markdown table to stdout so it lands in the agent's initial context.

Fail-open: if no ADR files exist or are unreadable, exits 0 with no output.
Never raises. Capped at MAX_BODY_LINES so it cannot bloat the session context.
"""
import os
import re
import sys
from pathlib import Path

MAX_BODY_LINES = 40
ADR_PATTERN = re.compile(r"^(\d{4})-(.+)\.md$")


def project_root() -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent.parent


def parse_frontmatter(path: Path) -> dict[str, str] | None:
    """Extract YAML frontmatter fields and the H1 title from an ADR file.

    Hand-rolls parsing to avoid a pyyaml dependency. Expects the standard
    MADR frontmatter block delimited by --- lines.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None

    meta: dict[str, str] = {}
    i = 1
    while i < len(lines):
        line = lines[i].strip()
        if line == "---":
            i += 1
            break
        if ":" in line:
            key, _, val = line.partition(":")
            meta[key.strip()] = val.strip()
        i += 1

    # Extract H1 title from the body after frontmatter
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("# "):
            # Strip the "# NNNN — " prefix to get just the title
            title = re.sub(r"^#\s*\d{4}\s*[—–-]\s*", "", line)
            meta["title"] = title
            break
        i += 1

    return meta if meta else None


def scan_adrs() -> list[tuple[str, dict[str, str]]]:
    """Return (number, metadata) pairs sorted by ADR number."""
    adr_dir = project_root() / "context" / "adrs"
    if not adr_dir.is_dir():
        return []

    results = []
    for p in sorted(adr_dir.iterdir()):
        m = ADR_PATTERN.match(p.name)
        if not m:
            continue
        meta = parse_frontmatter(p)
        if meta is None:
            continue
        results.append((m.group(1), meta))
    return results


def build_table(adrs: list[tuple[str, dict[str, str]]]) -> list[str]:
    """Build a markdown table from scanned ADR metadata."""
    header = "| # | Title | Status | Date | Affects | Intent |"
    sep = "|---|---|---|---|---|---|"
    rows = []
    for num, meta in adrs:
        slug = meta.get("title", "(untitled)")
        status = meta.get("status", "?")
        date = meta.get("date", "?")
        affects = meta.get("affects", "?")
        intent = meta.get("intent", "?")
        rows.append(f"| {num} | {slug} | {status} | {date} | {affects} | {intent} |")
    return [header, sep, *rows]


def trim(lines: list[str]) -> list[str]:
    """Cap table rows at MAX_BODY_LINES, dropping oldest rows first."""
    preamble = lines[:2]  # header + separator
    rows = lines[2:]
    max_rows = MAX_BODY_LINES - len(preamble) - 1  # -1 for truncation marker
    if max_rows < 1:
        max_rows = 1
    if len(rows) <= max_rows:
        return lines
    truncated = len(rows) - max_rows
    marker = f"| … | _({truncated} older entries omitted)_ |  |  |  |  |"
    return preamble + [marker] + rows[-max_rows:]


def main() -> int:
    adrs = scan_adrs()
    if not adrs:
        return 0

    table = build_table(adrs)
    table = trim(table)

    print("## Anton ADR index (injected at session start)")
    print()
    for line in table:
        print(line)
    print()
    print(
        "Reminder: ADRs are immutable. Use the `adr` skill (`/adr supersede`) "
        "to revise a decision, never edit the body in place."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
