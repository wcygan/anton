#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Validate Anton's shared target resolution and preflight adapters."""

from __future__ import annotations

import re
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "lib"))

from cluster_target_contract import classify_command, resolve_talos_targets  # noqa: E402


def main() -> int:
    failures: list[str] = []
    fallback = resolve_talos_targets(REPO, source="fallback", environ={})
    if fallback.source != "fallback" or len(fallback.nodes) != 3:
        failures.append("fallback inventory must resolve exactly three nodes")
    if fallback.addresses() != ",".join(node.address for node in fallback.nodes):
        failures.append("address-list adapter must preserve resolved node order")
    if any(node["address"] != "<redacted>" for node in fallback.evidence()["nodes"]):
        failures.append("default target evidence must redact addresses")

    port_forward = classify_command("mise exec -- kubectl -n observability port-forward svc/loki 3100:3100")
    if not port_forward or port_forward[0].classification != "cluster-mutation":
        failures.append("kubectl port-forward must classify as a cluster mutation")

    adapters = (
        REPO / ".claude" / "hooks" / "guard_k8s_context.py",
        REPO / ".codex" / "hooks" / "anton_policy.py",
        REPO / "scripts" / "talos-health.sh",
    )
    for path in adapters:
        text = path.read_text(encoding="utf-8")
        if "cluster_target_contract" not in text and "cluster-targets.py" not in text:
            failures.append(f"adapter does not consume target contract: {path.relative_to(REPO)}")

    pointer_files = (
        REPO / "docs" / "docs" / "runbooks" / "talos-health.md",
        REPO / ".agents" / "skills" / "anton-remote-access" / "SKILL.md",
        REPO / ".claude" / "skills" / "anton-remote-access" / "SKILL.md",
        REPO / ".agents" / "skills" / "talos-inspect" / "SKILL.md",
        REPO / ".agents" / "skills" / "talos-inspect" / "references" / "health.md",
        REPO / ".agents" / "skills" / "talos-inspect" / "references" / "disks.md",
        REPO / ".agents" / "skills" / "talos-inspect" / "references" / "network.md",
        REPO / ".claude" / "skills" / "talos-inspect" / "SKILL.md",
        REPO / ".claude" / "skills" / "talos-inspect" / "references" / "health.md",
        REPO / ".claude" / "skills" / "talos-inspect" / "references" / "disks.md",
        REPO / ".claude" / "skills" / "talos-inspect" / "references" / "network.md",
    )
    fallback_addresses = {node.address for node in fallback.nodes}
    for path in pointer_files:
        text = path.read_text(encoding="utf-8")
        if "scripts/cluster-targets.py" not in text:
            failures.append(f"missing target resolver pointer: {path.relative_to(REPO)}")
        for address in fallback_addresses:
            if address in text:
                failures.append(f"copied fallback address outside inventory: {path.relative_to(REPO)}")

    task_guidance = (
        REPO / "AGENTS.md",
        REPO / "scripts" / "AGENTS.md",
        REPO / "docs" / "docs" / "runbooks" / "talos-health.md",
    )
    bare_task = re.compile(r"(?m)(?:^[ \t]*|`)task\s+(?:--list|reconcile|[a-z0-9_-]+:[a-z0-9_-]+)\b")
    for path in task_guidance:
        if bare_task.search(path.read_text(encoding="utf-8")):
            failures.append(f"task command must use 'mise exec --': {path.relative_to(REPO)}")

    if failures:
        for failure in failures:
            print(f"[targets.preflight] {failure}", file=sys.stderr)
        return 1
    print("Cluster target contract: PASS (live/fallback resolution + redaction + mutation preflight)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
