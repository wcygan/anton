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
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

WATCH_YAML_PREFIXES = ("kubernetes/", "talos/", "bootstrap/")
YAML_SUFFIXES = (".yaml", ".yml")
PLAN_PATTERN = re.compile(r"^\d{4}-.+\.md$")
PLAN_STATUS = {"draft", "in-progress", "blocked", "done", "abandoned"}
PROTECTED_BASENAMES = {
    "age.key",
    "github-deploy.key",
    "cloudflare-tunnel.json",
    "github-push-token.txt",
}

CMD_START = r"(?:^|[;&|\n]|\$\()\s*(?:\w+=\S+\s+)*"
TAIL = r"[^;&|\n`]{0,200}"

DESTRUCTIVE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(CMD_START + r"task\s+talos:reset\b(?!-)"),
        "task talos:reset wipes the cluster.",
    ),
    (
        re.compile(CMD_START + r"talosctl\b" + TAIL + r"\breset\b(?!-)"),
        "talosctl reset wipes a Talos node.",
    ),
    (
        re.compile(CMD_START + r"talosctl\b" + TAIL + r"\bapply-config\b"),
        "talosctl apply-config changes node configuration.",
    ),
    (
        re.compile(
            CMD_START
            + r"kubectl\b"
            + TAIL
            + r"\bdelete\b"
            + TAIL
            + r"\b(?:namespaces?|ns|pv|pvs|persistentvolumes?|pvc|pvcs|persistentvolumeclaims?|crds?|customresourcedefinitions?)\b"
        ),
        "kubectl delete of namespace, volume, or CRD can cascade.",
    ),
    (
        re.compile(
            CMD_START
            + r"kubectl\b"
            + TAIL
            + r"\bdrain\b"
            + TAIL
            + r"\s--(?:delete-emptydir-data|delete-local-data)(?=\s|=|$)"
        ),
        "kubectl drain with emptyDir deletion destroys local pod data.",
    ),
    (re.compile(CMD_START + r"helmfile\s+destroy\b"), "helmfile destroy removes bootstrap releases."),
    (re.compile(CMD_START + r"flux\s+uninstall\b"), "flux uninstall removes Flux."),
    (
        re.compile(CMD_START + r"flux\s+suspend\b(?!.*(?:\s-n\s+\S|\s--namespace(?:=|\s+)\S|\s-A\b|--all-namespaces\b))"),
        "unscoped flux suspend halts reconciliation.",
    ),
    (
        re.compile(
            CMD_START
            + r"rm\b"
            + r"(?:\s+(?:-[rfv]*[rf][rfv]*|--recursive|--force))+"
            + r"\s+(?:/(?:\s|$|\*)|~(?:/|\s|$)|\$HOME(?:/|\s|$)|/Users/[^/\s]+/?(?:\s|$))"
        ),
        "recursive rm at HOME or filesystem root is catastrophic.",
    ),
]

SECRET_SEGMENT_SEP = re.compile(r"&&|\|\||;|\||\n|\$\(")
KUBECTL_GET_SECRET = re.compile(
    r"^\s*(?:\w+=\S+\s+)*kubectl\b" + TAIL + r"\bget\b" + TAIL + r"\bsecrets?(?:\.v1)?(?:\b|/)"
)
DANGEROUS_SECRET_OUTPUT = re.compile(
    r"(?:^|\s)(?:-o\s*=?\s*|--output(?:\s*=\s*|\s+))"
    r"(?:yaml|json|jsonpath(?:-as-json|-file)?|go-template(?:-file)?|custom-columns(?:-file)?|template)\b"
)


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
    cwd = data.get("cwd")
    if isinstance(cwd, str) and cwd:
        return Path(cwd)
    return Path.cwd()


def check_tailnet(texts: Iterable[str]) -> int:
    tailnet = os.environ.get("ANTON_TAILNET_NAME", "").strip()
    if not tailnet:
        return 0
    needle = f"{tailnet}.ts.net"
    for text in texts:
        if needle and needle in text:
            return block(f"payload contains real tailnet name '{needle}'; use '<tailnet-name>.ts.net'.")
    return 0


def check_bash_policy(cmd: str) -> int:
    if not cmd:
        return 0
    if re.match(r"^\s*ANTON_DESTRUCTIVE_OK=1\s+", cmd):
        return 0
    for pattern, reason in DESTRUCTIVE_PATTERNS:
        if pattern.search(cmd):
            return block(f"{reason} Ask for explicit operator approval first.")
    if re.match(r"^\s*ANTON_ALLOW_SECRET_READ=1\s+", cmd):
        return 0
    for segment in SECRET_SEGMENT_SEP.split(cmd):
        if KUBECTL_GET_SECRET.search(segment) and DANGEROUS_SECRET_OUTPUT.search(segment):
            return block("kubectl Secret output would expose .data values; use describe or ExternalSecret status.")
    return 0


def extract_patch_paths(patch: str) -> list[str]:
    paths: list[str] = []
    prefixes = ("*** Add File: ", "*** Update File: ", "*** Delete File: ")
    for line in patch.splitlines():
        for prefix in prefixes:
            if line.startswith(prefix):
                paths.append(line[len(prefix) :].strip())
    return paths


def is_sops_path(path: Path) -> bool:
    return any(".sops." in part for part in path.parts)


def encrypted_sops_text(path: Path) -> bool:
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return False
    return "ENC[AES256" in text or bool(re.search(r"^sops:", text, re.MULTILINE))


def check_patch_pre(data: dict) -> int:
    patch = command(data)
    root = project_root(data)
    rc = check_tailnet([patch])
    if rc:
        return rc
    for rel in extract_patch_paths(patch):
        path = root / rel
        if path.name.lower() in PROTECTED_BASENAMES:
            return block(f"{rel} is a protected credential artifact.")
        if is_sops_path(path) and path.exists() and encrypted_sops_text(path):
            return block(f"{rel} is already SOPS-encrypted; edit it with sops and keep the footer intact.")
    return 0


def changed_paths_for_post(data: dict) -> list[Path]:
    root = project_root(data)
    return [root / rel for rel in extract_patch_paths(command(data))]


def relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def validate_yaml(path: Path, root: Path) -> int:
    rel = relative(path, root)
    if not path.exists() or not rel.endswith(YAML_SUFFIXES) or ".sops." in path.name:
        return 0
    if not any(rel.startswith(prefix) for prefix in WATCH_YAML_PREFIXES):
        return 0
    if not shutil.which("yq"):
        return 0
    result = subprocess.run(["yq", ".", str(path)], capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        return block(f"YAML syntax error in {rel}: {result.stderr.strip()}")
    return 0


def app_root_for(path: Path, root: Path) -> Path | None:
    rel = relative(path, root)
    parts = Path(rel).parts
    if len(parts) < 5 or parts[0] != "kubernetes" or parts[1] != "apps":
        return None
    return root / parts[0] / parts[1] / parts[2] / parts[3]


def kustomization_has_entries(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return bool(re.search(r"^\s*-\s+\S", text, re.MULTILINE))


def validate_flux_app(path: Path, root: Path) -> int:
    app_root = app_root_for(path, root)
    if app_root is None or not app_root.exists():
        return 0
    required = [app_root / "ks.yaml", app_root / "app" / "kustomization.yaml"]
    missing = [p for p in required if not p.exists()]
    helmrelease = app_root / "app" / "helmrelease.yaml"
    source_options = [
        app_root / "app" / "ocirepository.yaml",
        app_root / "app" / "helmrepository.yaml",
        app_root / "app" / "gitrepository.yaml",
    ]
    if helmrelease.exists() and not any(p.exists() for p in source_options):
        missing.append(app_root / "app" / "ocirepository.yaml or helmrepository.yaml or gitrepository.yaml")
    if not helmrelease.exists():
        app_kust = app_root / "app" / "kustomization.yaml"
        if app_kust.exists() and not kustomization_has_entries(app_kust):
            missing.append(app_kust)
    if missing:
        rels = ", ".join(relative(p, root) for p in missing)
        return block(f"Flux app {relative(app_root, root)} is missing required scaffold: {rels}.")
    return 0


def validate_plan_status(path: Path, root: Path) -> int:
    rel = relative(path, root)
    if not rel.startswith("context/plans/") or path.parent.name != "plans" or not PLAN_PATTERN.match(path.name):
        return 0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return 0
    if not lines or lines[0].strip() != "---":
        return 0
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            return 0
        if stripped.startswith("status:"):
            status = stripped.partition(":")[2].strip().lower()
            if status and status not in PLAN_STATUS:
                return block(f"Plan {path.name} has invalid status '{status}'.")
            return 0
    return 0


def run_pre(data: dict) -> int:
    tool = data.get("tool_name")
    if tool == "Bash":
        rc = check_tailnet([command(data)])
        return rc or check_bash_policy(command(data))
    if tool == "apply_patch":
        return check_patch_pre(data)
    return 0


def run_post(data: dict) -> int:
    if data.get("tool_name") != "apply_patch":
        return 0
    root = project_root(data)
    for path in changed_paths_for_post(data):
        for check in (validate_yaml, validate_flux_app, validate_plan_status):
            rc = check(path, root)
            if rc:
                return rc
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
