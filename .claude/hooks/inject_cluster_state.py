#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""SessionStart hook: inject current cluster context.

Prints a short status block to stdout so it lands in the agent's initial
context. Catches "I'm pointed at the wrong cluster" mistakes at turn 0.

Flux health is intentionally *not* checked here — the API call through the
Tailscale-operator proxy takes ~8s and this hook must run in <1s. For Flux
status, invoke the `anton-cluster-health` skill or run
`kubectl get kustomizations.kustomize.toolkit.fluxcd.io -A` on demand.
"""
import os
import shlex
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TALOSCONFIG = REPO_ROOT / "talos" / "clusterconfig" / "talosconfig"


def run(cmd: list[str], timeout: int = 3) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        return f"(error: {exc})"
    out = (r.stdout or r.stderr).strip()
    return out or "(no output)"


def talos_context() -> str:
    # Per anton-remote-access: always point at the repo-generated talosconfig.
    # ~/.talos/config is intentionally empty on remote workstations.
    args = ["talosctl"]
    if TALOSCONFIG.is_file():
        args += ["--talosconfig", str(TALOSCONFIG)]
    args += ["config", "info"]
    raw = run(args)
    for line in raw.splitlines():
        stripped = line.strip().lower()
        if ":" in line and (
            stripped.startswith("context") or stripped.startswith("current context")
        ):
            _, _, value = line.partition(":")
            return value.strip()
    return raw.splitlines()[0] if raw else "(unknown)"


def export_talosconfig() -> None:
    # Persist TALOSCONFIG for bare `talosctl` invocations in subsequent Bash
    # tool calls. The settings.json `env` block does not shell-expand
    # ${CLAUDE_PROJECT_DIR}, but hooks run with it properly set.
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    if env_file and TALOSCONFIG.is_file():
        with open(env_file, "a") as f:
            f.write(f"export TALOSCONFIG={shlex.quote(str(TALOSCONFIG))}\n")


def main() -> int:
    export_talosconfig()
    kube_ctx = run(["kubectl", "config", "current-context"])
    talos_ctx = talos_context()

    print("## Anton cluster state (injected at session start)")
    print(f"- kubectl context: {kube_ctx}")
    print(f"- talosctl context: {talos_ctx}")
    print()
    print(
        "Reminder: verify context before any mutating kubectl/talosctl/flux "
        "command. SOPS-encrypted files must be edited via `sops <file>`. "
        "Flux health is not checked here — use the `anton-cluster-health` "
        "skill or `kubectl get kustomizations.kustomize.toolkit.fluxcd.io -A` "
        "when needed."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
