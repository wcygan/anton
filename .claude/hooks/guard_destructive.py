#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Claude adapter for Anton's shared destructive-command policy."""

from __future__ import annotations

import json
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "lib"))

from agent_policy_contract import destructive_command_violation  # noqa: E402


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    if data.get("tool_name") != "Bash":
        return 0
    command = (data.get("tool_input") or {}).get("command", "")
    if not isinstance(command, str):
        return 0
    violation = destructive_command_violation(command)
    if not violation:
        return 0
    print(f"Blocked destructive command.\n→ {violation.message}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
