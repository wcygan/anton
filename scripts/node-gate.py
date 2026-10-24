#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Read-only gate for one Anton node: before cordon, before uncordon, after uncordon.

Exit status: 0 when every check passes, 1 when any check fails (stop the
maintenance), 2 when the gate cannot start (bad arguments or unresolved target)
or cannot write its report.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "lib"))

import node_gate  # noqa: E402
from cluster_target_contract import expected_kube_context, load_inventory, resolve_talos_targets  # noqa: E402


class SetupError(ValueError):
    pass


def _names(values: list[str] | None) -> frozenset[str]:
    return frozenset(item.strip() for value in values or [] for item in value.split(",") if item.strip())


def parse_args(argv: list[str] | None, inventory: tuple[str, ...]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        epilog=(
            "Phases: pre runs before cordon; return runs after the reboot while the node is still "
            "cordoned; post runs after uncordon. Each must pass before the next step."
        ),
    )
    parser.add_argument("--node", required=True, choices=inventory)
    parser.add_argument("--phase", required=True, choices=node_gate.PHASES)
    parser.add_argument("--talos-version", help="expected Talos version (default: talos/talenv.yaml)")
    parser.add_argument("--kubernetes-version", help="expected Kubernetes version (default: talos/talenv.yaml)")
    parser.add_argument("--context", help="Kubernetes context (default: the Anton Tailscale operator proxy)")
    parser.add_argument("--talosconfig", help="talosconfig path (default: $TALOSCONFIG, then talos/clusterconfig/talosconfig)")
    parser.add_argument(
        "--rebooted", action="append", metavar="NODES",
        help="nodes rebooted earlier in this maintenance window; their reboot alerts are expected",
    )
    parser.add_argument(
        "--accept-alert", action="append", metavar="ALERTNAMES",
        help="alert names the operator has already assessed; they do not fail the gate",
    )
    parser.add_argument(
        "--wait", type=float, default=0.0, metavar="SECONDS",
        help="rerun failing checks every 20s until they pass or SECONDS elapse (default 0, at most 3600)",
    )
    parser.add_argument("--report", type=Path, help="write the JSON report to this path")
    args = parser.parse_args(argv)
    if not math.isfinite(args.wait) or not 0 <= args.wait <= 3600:
        parser.error("--wait must be between 0 and 3600 seconds")
    unknown = sorted(_names(args.rebooted) - set(inventory))
    if unknown:
        parser.error(f"--rebooted names nodes outside the inventory: {', '.join(unknown)}")
    return args


def main(argv: list[str] | None = None) -> int:
    try:
        inventory = tuple(str(node["name"]) for node in load_inventory(REPO)["talos"]["nodes"])
    except (OSError, ValueError, KeyError) as error:
        print(f"node-gate cannot start: cluster inventory unreadable: {error}", file=sys.stderr)
        return 2
    args = parse_args(argv, inventory)
    try:
        lan_ips = node_gate.talconfig_addresses(
            (REPO / "talos" / "talconfig.yaml").read_text(encoding="utf-8"), inventory
        )
        pinned_talos, pinned_kubernetes = node_gate.talenv_versions(
            (REPO / "talos" / "talenv.yaml").read_text(encoding="utf-8")
        )
        targets = resolve_talos_targets(REPO)
        context = args.context or expected_kube_context(REPO)
        talosconfig = args.talosconfig or os.environ.get("TALOSCONFIG") or str(
            REPO / "talos" / "clusterconfig" / "talosconfig"
        )
        if not Path(talosconfig).is_file():
            raise SetupError(f"talosconfig {talosconfig} does not exist; pass --talosconfig")
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
    except (OSError, ValueError) as error:
        print(f"node-gate cannot start: {node_gate.redact(str(error))}", file=sys.stderr)
        return 2

    plan = node_gate.Plan(
        node=args.node,
        phase=args.phase,
        inventory=inventory,
        lan_ips=lan_ips,
        talos_version=args.talos_version or pinned_talos,
        kubernetes_version=args.kubernetes_version or pinned_kubernetes,
        accepted_alerts=_names(args.accept_alert),
        rebooted=_names(args.rebooted),
    )
    addresses = {target.name: target.address for target in targets.nodes}
    # Reach Talos through a peer so the path matches the one used during the
    # reboot; the target's own endpoint is the last resort.
    order = [name for name in inventory if name != args.node] + [args.node]
    run = node_gate.gate(
        plan,
        runner=node_gate.run_command,
        context=context,
        talosconfig=talosconfig,
        endpoints=[(name, addresses[name]) for name in order],
        wait=args.wait,
        progress=lambda message: print(message, file=sys.stderr, flush=True),
    )
    print(node_gate.render(run), flush=True)
    if args.report:
        try:
            node_gate.write_report(args.report, node_gate.report(run, context=context, target_source=targets.source))
        except OSError as error:
            print(f"node-gate could not write its report: {error}", file=sys.stderr)
            return 2
        print(f"report: {args.report}")
    return 0 if run.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
