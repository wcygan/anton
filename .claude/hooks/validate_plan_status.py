#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Claude adapter for Anton's shared plan-status policy."""

from __future__ import annotations

import json
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "lib"))

from agent_policy_contract import plan_status_violation  # noqa: E402


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    if data.get("tool_name") not in {"Edit", "Write", "MultiEdit"}:
        return 0
    file_path = (data.get("tool_input") or {}).get("file_path", "")
    if not isinstance(file_path, str) or not file_path:
        return 0
    root = Path(data.get("cwd") or REPO)
    violation = plan_status_violation(Path(file_path), root)
    if not violation:
        return 0
    print(f"Blocked invalid plan status.\n→ {violation.message}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
