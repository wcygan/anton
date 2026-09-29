#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Validate Anton's shared target resolution and preflight adapters."""

from __future__ import annotations

import re
import ipaddress
import json
import tempfile
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "lib"))

from cluster_target_contract import classify_command, resolve_talos_targets  # noqa: E402


def main() -> int:
    failures: list[str] = []
    inventory = json.loads((REPO / "scripts/cluster-targets.json").read_text())
    if any(set(node) != {"name"} for node in inventory["talos"]["nodes"]):
        failures.append("public Talos inventory must contain names only")
    # Validation must work in clean checkouts without private operator state.
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "scripts").mkdir()
        (root / ".private").mkdir()
        (root / "scripts/cluster-targets.json").write_text(json.dumps(inventory))
        private = {"schema": 1, "talos": {"nodes": [
            {"name": node["name"], "tailscale_ipv4": f"192.0.2.{i}"}
            for i, node in enumerate(inventory["talos"]["nodes"], 1)
        ]}}
        (root / ".private/cluster-targets.json").write_text(json.dumps(private))
        fallback = resolve_talos_targets(root, source="fallback", environ={})
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
    for path in pointer_files:
        text = path.read_text(encoding="utf-8")
        if "scripts/cluster-targets.py" not in text:
            failures.append(f"missing target resolver pointer: {path.relative_to(REPO)}")

    # Detect node-address copies without depending on the operator's private file.
    tailnet_range = ipaddress.ip_network("100.64.0.0/10")
    for path in (*pointer_files, REPO / "scripts/cluster-targets.json"):
        text = path.read_text(encoding="utf-8")
        for literal in re.findall(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b", text):
            try:
                address = ipaddress.ip_address(literal)
            except ValueError:
                continue
            if address in tailnet_range:
                failures.append(f"private node address in public guidance: {path.relative_to(REPO)}")

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
