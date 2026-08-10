#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Claude adapter for Anton's shared tailnet-content policy."""

from __future__ import annotations

import json
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "lib"))

from agent_policy_contract import tailnet_content_violation  # noqa: E402


def payload_texts(data: dict) -> list[str]:
    tool = data.get("tool_name", "")
    tool_input = data.get("tool_input", {}) or {}
    if tool == "Write":
        return [tool_input.get("content") or ""]
    if tool == "Edit":
        return [tool_input.get("new_string") or ""]
    if tool == "MultiEdit":
        return [edit.get("new_string") or "" for edit in tool_input.get("edits", []) or []]
    if tool == "Bash":
        return [tool_input.get("command") or ""]
    return []


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    violation = tailnet_content_violation(payload_texts(data))
    if not violation:
        return 0
    print(f"Blocked tailnet literal.\n→ {violation.message}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
