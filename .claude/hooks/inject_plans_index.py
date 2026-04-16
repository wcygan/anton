#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""SessionStart hook: inject the anton active-plan index by scanning plan files directly.

Globs `context/plans/NNNN-*.md`, parses YAML-ish frontmatter, keeps only active
statuses (Draft / In-progress / Blocked), and prints a trimmed markdown table to
stdout so it lands in the agent's initial context.

Any plan whose status is NOT in the canonical enum is reported in a separate
warning block above the table — silent drops were the failure mode that
motivated the enum-drift hardening.

Canonical enum lives at `.claude/skills/planner/references/statuses.txt`. This
hook reads it at session start so the enum has a single source of truth.

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

# Fallback used only if statuses.txt is missing or unreadable. Keeps the hook
# fail-open while still catching the common case. Keep in sync with statuses.txt.
FALLBACK_ACTIVE = {"draft", "in-progress", "blocked"}
FALLBACK_TERMINAL = {"done", "abandoned"}


def project_root() -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent.parent


def load_statuses() -> tuple[set[str], set[str]]:
    """Load (active, terminal) status sets from the canonical enum file.

    The file uses a blank line to separate active (top) from terminal (bottom).
    Comments (# ...) and empty groups fall back to the hardcoded defaults.
    """
    path = project_root() / ".claude" / "skills" / "planner" / "references" / "statuses.txt"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return FALLBACK_ACTIVE, FALLBACK_TERMINAL

    groups: list[list[str]] = [[]]
    for raw in text.split("\n"):
        line = raw.strip()
        if line.startswith("#"):
            continue
        if not line:
            if groups[-1]:
                groups.append([])
            continue
        groups[-1].append(line.lower())

    groups = [g for g in groups if g]
    if len(groups) < 2:
        return FALLBACK_ACTIVE, FALLBACK_TERMINAL
    return set(groups[0]), set(groups[1])


def parse_frontmatter(path: Path) -> dict[str, str] | None:
    """Extract YAML frontmatter fields and the H1 title from a plan file."""
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

    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("# "):
            title = re.sub(r"^#\s*\d{4}\s*[—–-]\s*", "", line)
            meta["title"] = title
            break
        i += 1

    return meta if meta else None


def scan_plans(active: set[str], terminal: set[str]) -> tuple[list[tuple[str, dict[str, str]]], list[tuple[str, str, str]]]:
    """Return (active_plans, drift) where:

    - active_plans is (number, metadata) pairs for plans whose status is active
    - drift is (number, filename, bad_status) for plans whose status is outside
      the canonical enum — these were the silent-drop failure mode.
    """
    plans_dir = project_root() / "context" / "plans"
    if not plans_dir.is_dir():
        return [], []

    active_plans: list[tuple[str, dict[str, str]]] = []
    drift: list[tuple[str, str, str]] = []
    for p in sorted(plans_dir.iterdir()):
        m = PLAN_PATTERN.match(p.name)
        if not m:
            continue
        meta = parse_frontmatter(p)
        if meta is None:
            continue
        raw_status = meta.get("status", "").strip()
        status = raw_status.lower()
        if status in active:
            active_plans.append((m.group(1), meta))
        elif status in terminal:
            continue
        else:
            drift.append((m.group(1), p.name, raw_status or "(empty)"))
    return active_plans, drift


def review_flag(meta: dict[str, str]) -> str:
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


def print_drift(drift: list[tuple[str, str, str]], active: set[str], terminal: set[str]) -> None:
    print("## ⚠ Anton plan-status drift (injected at session start)")
    print()
    print("The following plan files have non-canonical `status:` values and are")
    print("being silently excluded from the active-plan index. Fix with `/planner`")
    print("or edit frontmatter directly.")
    print()
    for num, name, bad in drift:
        print(f"- `{name}` — status: `{bad}`")
    print()
    canonical = sorted(active) + sorted(terminal)
    print(f"Canonical enum: {', '.join(s.capitalize() if s != 'in-progress' else 'In-progress' for s in canonical)}")
    print()


def main() -> int:
    active, terminal = load_statuses()
    plans, drift = scan_plans(active, terminal)

    if drift:
        print_drift(drift, active, terminal)

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
