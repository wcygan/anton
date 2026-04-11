#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""PreToolUse guard: prevent the real tailnet name from entering repository files.

anton's CLAUDE.md requires the literal placeholder `<tailnet-name>.ts.net` in
committed files. This hook blocks any Edit/Write/Bash payload that contains
the real tailnet name.

Set ANTON_TAILNET_NAME in your shell (e.g., `export ANTON_TAILNET_NAME=my-net`).
Without that env var the hook is a no-op — we deliberately never hardcode the
real name in this file.
"""
import json
import os
import sys


def main() -> int:
    tailnet = os.environ.get("ANTON_TAILNET_NAME", "").strip()
    if not tailnet:
        return 0

    needle = f"{tailnet}.ts.net"

    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    tool = data.get("tool_name", "")
    tool_input = data.get("tool_input", {}) or {}

    texts: list[str] = []
    if tool == "Write":
        texts.append(tool_input.get("content") or "")
    elif tool == "Edit":
        texts.append(tool_input.get("new_string") or "")
    elif tool == "MultiEdit":
        for edit in tool_input.get("edits", []) or []:
            texts.append(edit.get("new_string") or "")
    elif tool == "Bash":
        texts.append(tool_input.get("command") or "")
    else:
        return 0

    for text in texts:
        if needle in text:
            print(
                f"Blocked: payload contains the real tailnet name '{needle}'.\n"
                f"→ anton's CLAUDE.md requires the placeholder "
                f"'<tailnet-name>.ts.net' in committed files.\n"
                f"→ Replace the literal before writing.",
                file=sys.stderr,
            )
            return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
