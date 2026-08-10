#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Claude hook adapter for Anton's shared Flux application contract."""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "lib"))

from flux_application_contract import validate_changed_path  # noqa: E402


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

    violations = validate_changed_path(path, REPO)
    if not violations:
        return 0

    print(
        "Blocked by Anton Flux application contract:\n"
        + "\n".join(violation.render(REPO) for violation in violations),
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
