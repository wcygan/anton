#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""PreToolUse guard: verify kubectl/talosctl/flux context is anton before mutating.

Read-only subcommands (get/describe/logs/etc.) always pass through. Mutating
subcommands require the current context to match the expected anton context.
Fails open (exit 0) if the context can't be resolved so local tooling bugs
don't block routine work — the other guards still apply.

Override via env vars:
  ANTON_KUBE_CONTEXT   (default: admin@anton)
  ANTON_TALOS_CONTEXT  (default: anton)
"""
import json
import os
import shutil
import subprocess
import sys

EXPECTED_KUBE = os.environ.get("ANTON_KUBE_CONTEXT", "admin@anton")
EXPECTED_TALOS = os.environ.get("ANTON_TALOS_CONTEXT", "anton")

READ_ONLY_KUBECTL = frozenset({
    "get", "describe", "logs", "top", "explain", "api-resources",
    "api-versions", "version", "cluster-info", "config", "auth",
    "events", "wait", "diff", "kustomize", "exec", "port-forward",
    "proxy", "cp",
})

READ_ONLY_TALOSCTL = frozenset({
    "get", "read", "list", "ls", "containers", "dmesg", "health",
    "logs", "memory", "processes", "ps", "service", "services",
    "stats", "time", "version", "config", "disks", "dashboard",
    "inspect", "interfaces", "pcap", "meta", "netstat", "rollback",
    "kubeconfig", "support",
})

READ_ONLY_FLUX = frozenset({
    "get", "stats", "version", "check", "tree", "trace",
    "events", "logs", "diff", "envsubst", "completion",
})


def run_stdout(cmd: list[str], timeout: int = 3) -> str | None:
    if not shutil.which(cmd[0]):
        return None
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (subprocess.SubprocessError, OSError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.strip()


def current_kube_context() -> str | None:
    return run_stdout(["kubectl", "config", "current-context"])


def current_talos_context() -> str | None:
    out = run_stdout(["talosctl", "config", "info"])
    if out is None:
        return None
    for line in out.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        if key.strip().lower() == "context":
            return value.strip()
    return None


def first_subcommand(tokens: list[str]) -> str | None:
    for t in tokens:
        if t.startswith("-") or "=" in t:
            continue
        return t
    return None


def strip_env_prefix(tokens: list[str]) -> list[str]:
    i = 0
    while i < len(tokens) and "=" in tokens[i] and not tokens[i].startswith("-"):
        i += 1
    return tokens[i:]


def block(binary: str, sub: str, actual: str, expected: str, fix: str) -> int:
    print(
        f"Blocked: {binary} {sub} against context '{actual}' (expected '{expected}').\n"
        f"→ {fix}\n"
        f"→ Override the expected name via ANTON_KUBE_CONTEXT / ANTON_TALOS_CONTEXT.",
        file=sys.stderr,
    )
    return 2


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    if data.get("tool_name") != "Bash":
        return 0

    cmd: str = data.get("tool_input", {}).get("command", "")
    if not cmd:
        return 0

    tokens = strip_env_prefix(cmd.split())
    if not tokens:
        return 0

    binary = tokens[0]
    rest = tokens[1:]

    if binary == "kubectl":
        sub = first_subcommand(rest)
        if sub is None or sub in READ_ONLY_KUBECTL:
            return 0
        ctx = current_kube_context()
        if ctx is None or ctx == EXPECTED_KUBE:
            return 0
        return block(
            "kubectl", sub, ctx, EXPECTED_KUBE,
            f"Switch context: kubectl config use-context {EXPECTED_KUBE}",
        )

    if binary == "talosctl":
        sub = first_subcommand(rest)
        if sub is None or sub in READ_ONLY_TALOSCTL:
            return 0
        ctx = current_talos_context()
        if ctx is None or ctx == EXPECTED_TALOS:
            return 0
        return block(
            "talosctl", sub, ctx, EXPECTED_TALOS,
            f"Switch context: talosctl config context {EXPECTED_TALOS}",
        )

    if binary == "flux":
        sub = first_subcommand(rest)
        if sub is None or sub in READ_ONLY_FLUX:
            return 0
        ctx = current_kube_context()
        if ctx is None or ctx == EXPECTED_KUBE:
            return 0
        return block(
            "flux", sub, ctx, EXPECTED_KUBE,
            f"flux reads the active kubectl context. Switch with "
            f"`kubectl config use-context {EXPECTED_KUBE}`.",
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
