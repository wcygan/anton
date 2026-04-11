#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""PostToolUse validator: sanity-check YAML under kubernetes/, talos/, bootstrap/.

Shells out to `yq` (already the preferred tool in CLAUDE.md) to parse the
file after an edit. Surfaces syntax errors immediately with exit 2 so the
error is fed back to the agent instead of silently breaking Flux.

No-op if yq is not on PATH, or if the edited file is outside the watched
manifest trees.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

WATCH_PREFIXES = ("kubernetes/", "talos/", "bootstrap/")
YAML_SUFFIXES = (".yaml", ".yml")


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    if data.get("tool_name") not in {"Edit", "Write", "MultiEdit"}:
        return 0

    file_path = data.get("tool_input", {}).get("file_path", "")
    if not file_path or not file_path.endswith(YAML_SUFFIXES):
        return 0

    # Ignore SOPS-encrypted files — parsing them is meaningless until decrypted.
    if ".sops." in Path(file_path).name:
        return 0

    cwd = data.get("cwd") or ""
    try:
        rel = str(Path(file_path).resolve().relative_to(Path(cwd).resolve()))
    except (ValueError, OSError):
        rel = file_path
    if not any(rel.startswith(p) for p in WATCH_PREFIXES):
        return 0

    if not shutil.which("yq"):
        return 0

    try:
        result = subprocess.run(
            ["yq", "eval-all", ".", file_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        print(f"validate_yaml: could not run yq ({exc})", file=sys.stderr)
        return 0

    if result.returncode != 0:
        print(
            f"YAML syntax error in {rel}:\n{result.stderr.strip()}\n"
            f"→ Fix before running `task configure` — Flux will reject this manifest.",
            file=sys.stderr,
        )
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
