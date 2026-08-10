#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Claude adapter for Anton's shared cluster mutation preflight."""

from __future__ import annotations

import json
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "lib"))

from cluster_target_contract import preflight_command  # noqa: E402


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    if data.get("tool_name") != "Bash":
        return 0
    command = data.get("tool_input", {}).get("command", "")
    if not isinstance(command, str) or not command:
        return 0

    violations = preflight_command(command, REPO)
    if not violations:
        return 0
    for violation in violations:
        print(
            f"Blocked: {violation.binary} {violation.subcommand or '<none>'}: "
            f"{violation.message}; actual={violation.actual!r}, expected={violation.expected!r}.",
            file=sys.stderr,
        )
    print("Resolve the target context before running this cluster mutation.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
