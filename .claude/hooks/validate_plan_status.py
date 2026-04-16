#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""PostToolUse check: enforce canonical `status:` values in anton plan frontmatter.

Triggers on Edit/Write/MultiEdit under `context/plans/NNNN-*.md`. Parses the
frontmatter, compares `status:` to the canonical enum at
`.claude/skills/planner/references/statuses.txt`, and exits non-zero (hook
feedback) if the value is off-enum.

TEMPLATE.md and non-numbered files are skipped.

Shares the same fail-open philosophy as the SessionStart index hook: if the
enum file is unreadable, falls back to a hardcoded default rather than
blocking writes on missing infrastructure.
"""
import json
import re
import sys
from pathlib import Path

PLAN_PATTERN = re.compile(r"^\d{4}-.+\.md$")

FALLBACK_ENUM = {"draft", "in-progress", "blocked", "done", "abandoned"}


def load_enum(project_root: Path) -> set[str]:
    path = project_root / ".claude" / "skills" / "planner" / "references" / "statuses.txt"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return FALLBACK_ENUM
    values: set[str] = set()
    for raw in text.split("\n"):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        values.add(line.lower())
    return values or FALLBACK_ENUM


def read_status(path: Path) -> str | None:
    """Return the raw `status:` value from frontmatter, or None if absent."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        s = line.strip()
        if s == "---":
            return None
        if s.startswith("status:"):
            return s.partition(":")[2].strip()
    return None


def project_root_from_path(path: Path) -> Path:
    """Best-effort: find the anton repo root by walking up to `context/plans/`."""
    for parent in path.parents:
        if (parent / "context" / "plans").is_dir() and (parent / ".claude").is_dir():
            return parent
    return path.parent


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    if data.get("tool_name") not in {"Edit", "Write", "MultiEdit"}:
        return 0

    file_path = data.get("tool_input", {}).get("file_path", "")
    if not file_path:
        return 0

    try:
        path = Path(file_path).resolve()
    except OSError:
        return 0

    parts = path.parts
    try:
        idx = parts.index("plans")
    except ValueError:
        return 0
    if idx == 0 or parts[idx - 1] != "context":
        return 0
    if path.parent.name != "plans":
        return 0
    if not PLAN_PATTERN.match(path.name):
        return 0

    raw = read_status(path)
    if raw is None:
        return 0

    enum = load_enum(project_root_from_path(path))
    if raw.lower() in enum:
        return 0

    sorted_enum = sorted(enum)
    pretty = ", ".join(s.capitalize() if s != "in-progress" else "In-progress" for s in sorted_enum)
    print(
        f"Plan {path.name} has non-canonical status: `{raw}`.\n"
        f"Canonical enum: {pretty}.\n"
        f"Active statuses (shown in SessionStart index): Draft, In-progress, Blocked.\n"
        f"Terminal statuses (hidden from index): Done, Abandoned.\n"
        f"→ Source of truth: .claude/skills/planner/references/statuses.txt",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
