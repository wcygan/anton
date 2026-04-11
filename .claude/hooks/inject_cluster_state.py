#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""SessionStart hook: inject current cluster context + Flux health.

Prints a short status block to stdout so it lands in the agent's initial
context. Catches "I'm pointed at the wrong cluster" mistakes at turn 0 and
surfaces any Flux reconciliation errors so the agent doesn't start work on
top of latent breakage.
"""
import shutil
import subprocess
import sys


def run(cmd: list[str], timeout: int = 5) -> str:
    if not shutil.which(cmd[0]):
        return f"(missing binary: {cmd[0]})"
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.SubprocessError as exc:
        return f"(error: {exc})"
    out = (r.stdout or r.stderr).strip()
    return out or "(no output)"


def talos_context() -> str:
    raw = run(["talosctl", "config", "info"])
    for line in raw.splitlines():
        if ":" in line and line.strip().lower().startswith("context"):
            _, _, value = line.partition(":")
            return value.strip()
    return raw.splitlines()[0] if raw else "(unknown)"


def failing_flux_ks() -> str:
    raw = run(
        ["flux", "get", "ks", "-A", "--status-selector", "ready=false"],
        timeout=8,
    )
    if raw.startswith("("):
        return raw
    if not raw or "no resources found" in raw.lower():
        return "none"
    return raw


def main() -> int:
    kube_ctx = run(["kubectl", "config", "current-context"])
    talos_ctx = talos_context()
    failing = failing_flux_ks()

    print("## Anton cluster state (injected at session start)")
    print(f"- kubectl context: {kube_ctx}")
    print(f"- talosctl context: {talos_ctx}")
    print("- Failing Flux Kustomizations:")
    for line in failing.splitlines():
        print(f"    {line}")
    print()
    print(
        "Reminder: verify context before any mutating kubectl/talosctl/flux "
        "command. SOPS-encrypted files must be edited via `sops <file>`."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
