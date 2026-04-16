#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""SessionStart hook: inject the anton active-plan index by scanning plan files directly.

Globs `context/plans/NNNN-*.md`, parses YAML-ish frontmatter, keeps only active
statuses (Draft / In-progress / Blocked), and prints a trimmed markdown table to
stdout so it lands in the agent's initial context.

Fail-open: if no plan files exist or are unreadable, exits 0 with no output.
Never raises. Capped at MAX_BODY_LINES so it cannot bloat the session context.
"""
import os
import re
import sys
from datetime import date
from pathlib import Path

MAX_BODY_LINES = 25
PLAN_PATTERN = re.compile(r"^(\d{4})-(.+)\.md$")
ACTIVE_STATUSES = {"draft", "in-progress", "blocked"}


def project_root() -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent.parent


def parse_frontmatter(path: Path) -> dict[str, str] | None:
    """Extract YAML frontmatter fields and the H1 title from a plan file.

    Hand-rolls parsing to avoid a pyyaml dependency. Expects the standard
    frontmatter block delimited by --- lines.
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
            title = re.sub(r"^#\s*\d{4}\s*[—–-]\s*", "", line)
            meta["title"] = title
            break
        i += 1

    return meta if meta else None


def scan_plans() -> list[tuple[str, dict[str, str]]]:
    """Return (number, metadata) pairs sorted by plan number, active only."""
    plans_dir = project_root() / "context" / "plans"
    if not plans_dir.is_dir():
        return []

    results = []
    for p in sorted(plans_dir.iterdir()):
        m = PLAN_PATTERN.match(p.name)
        if not m:
            continue
        meta = parse_frontmatter(p)
        if meta is None:
            continue
        status = meta.get("status", "").strip().lower()
        if status not in ACTIVE_STATUSES:
            continue
        results.append((m.group(1), meta))
    return results


def review_flag(meta: dict[str, str]) -> str:
    """Return a warning marker if review-by is past due, else empty."""
    review = meta.get("review-by", "").strip()
    if not review or review.lower() in {"null", "none", ""}:
        return ""
    try:
        review_date = date.fromisoformat(review)
    except ValueError:
        return ""
    if review_date <= date.today():
        return " ⚠"
    return ""


def build_table(plans: list[tuple[str, dict[str, str]]]) -> list[str]:
    """Build a markdown table from scanned plan metadata."""
    header = "| # | Title | Status | Opened | Review-by | Related ADRs |"
    sep = "|---|---|---|---|---|---|"
    rows = []
    for num, meta in plans:
        title = meta.get("title", "(untitled)")
        status = meta.get("status", "?") + review_flag(meta)
        opened = meta.get("opened", "?")
        review = meta.get("review-by", "—") or "—"
        if review.lower() in {"null", "none", ""}:
            review = "—"
        adrs = meta.get("related-adrs", "[]")
        rows.append(f"| {num} | {title} | {status} | {opened} | {review} | {adrs} |")
    return [header, sep, *rows]


def trim(lines: list[str]) -> list[str]:
    """Cap table rows at MAX_BODY_LINES, dropping oldest rows first."""
    preamble = lines[:2]
    rows = lines[2:]
    max_rows = MAX_BODY_LINES - len(preamble) - 1
    if max_rows < 1:
        max_rows = 1
    if len(rows) <= max_rows:
        return lines
    truncated = len(rows) - max_rows
    marker = f"| … | _({truncated} older active entries omitted)_ |  |  |  |  |"
    return preamble + [marker] + rows[-max_rows:]


def main() -> int:
    plans = scan_plans()
    if not plans:
        return 0

    table = build_table(plans)
    table = trim(table)

    print("## Anton active plans (injected at session start)")
    print()
    for line in table:
        print(line)
    print()
    print(
        "Reminder: plans are mutable execution state. Use the `planner` skill "
        "(`/planner update`, `/planner close`) to change status or check off tasks. "
        "Closed plans (Done / Abandoned) are not shown — see `/planner list --all`."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
