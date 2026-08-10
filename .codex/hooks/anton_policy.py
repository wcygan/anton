#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Codex hook adapter for Anton safety policy.

Use as:
  python3 .codex/hooks/anton_policy.py pre
  python3 .codex/hooks/anton_policy.py post

The hook reads Codex hook JSON from stdin. `Bash` and `apply_patch` both place
their payload in `tool_input.command`, so this adapter checks shell commands
and patch bodies without depending on Claude-specific Edit/Write tool shapes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "lib"))

from agent_policy_contract import (  # noqa: E402
    destructive_command_violation,
    plan_status_violation,
    protected_edit_violation,
    secret_output_violation,
    tailnet_content_violation,
    yaml_file_violation,
)
from cluster_target_contract import preflight_command  # noqa: E402
from flux_application_contract import validate_changed_path  # noqa: E402


def block(message: str) -> int:
    print(f"Blocked by Anton Codex policy: {message}", file=sys.stderr)
    return 2


def load_event() -> dict:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def command(data: dict) -> str:
    tool_input = data.get("tool_input") or {}
    if isinstance(tool_input, dict):
        value = tool_input.get("command")
        return value if isinstance(value, str) else ""
    return ""


def project_root(data: dict) -> Path:
    start = event_cwd(data)
    for candidate in (start, *start.parents):
        if (candidate / "scripts" / "cluster-targets.json").is_file() and (
            candidate / ".codex"
        ).is_dir():
            return candidate
    return start


def event_cwd(data: dict) -> Path:
    cwd = data.get("cwd")
    return Path(cwd) if isinstance(cwd, str) and cwd else Path.cwd()


def patch_path(data: dict, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else event_cwd(data) / path


def check_bash_policy(cmd: str, root: Path) -> int:
    if not cmd:
        return 0
    for check in (destructive_command_violation, secret_output_violation):
        violation = check(cmd)
        if violation:
            return block(violation.message)
    violations = preflight_command(cmd, root)
    if violations:
        violation = violations[0]
        return block(
            f"{violation.binary} {violation.subcommand or '<none>'}: {violation.message}; "
            f"actual={violation.actual!r}, expected={violation.expected!r}."
        )
    return 0


def extract_patch_paths(patch: str) -> list[str]:
    paths: list[str] = []
    prefixes = ("*** Add File: ", "*** Update File: ", "*** Delete File: ")
    for line in patch.splitlines():
        for prefix in prefixes:
            if line.startswith(prefix):
                paths.append(line[len(prefix) :].strip())
    return paths


def check_patch_pre(data: dict) -> int:
    patch = command(data)
    content_violation = tailnet_content_violation([patch])
    if content_violation:
        return block(content_violation.message)
    for rel in extract_patch_paths(patch):
        path = patch_path(data, rel)
        violation = protected_edit_violation(path)
        if violation:
            return block(violation.message)
    return 0


def changed_paths_for_post(data: dict) -> list[Path]:
    return [patch_path(data, rel) for rel in extract_patch_paths(command(data))]


def run_pre(data: dict) -> int:
    tool = data.get("tool_name")
    if tool == "Bash":
        content_violation = tailnet_content_violation([command(data)])
        return (
            block(content_violation.message)
            if content_violation
            else check_bash_policy(command(data), project_root(data))
        )
    if tool == "apply_patch":
        return check_patch_pre(data)
    return 0


def run_post(data: dict) -> int:
    if data.get("tool_name") != "apply_patch":
        return 0
    root = project_root(data)
    for path in changed_paths_for_post(data):
        for check in (yaml_file_violation, plan_status_violation):
            violation = check(path, root)
            if violation:
                return block(violation.message)
        violations = validate_changed_path(path, root)
        if violations:
            return block(violations[0].render(root))
    return 0


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    data = load_event()
    if mode == "pre":
        return run_pre(data)
    if mode == "post":
        return run_post(data)
    print("usage: anton_policy.py pre|post", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
