#!/usr/bin/env python3
"""Inventory node images without pulling, deleting or restarting anything."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import subprocess
import sys

from lib.node_image_inventory import classify, gc_eligibility, parse_table, workload_references

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=90)
    if result.returncode:
        # Talos stderr may contain endpoint addresses. Keep failures private.
        raise RuntimeError(f"{args[0]} read failed (exit {result.returncode})")
    return result.stdout


def collect() -> dict:
    context = run("kubectl", "config", "current-context").strip()
    if not (context.startswith("tailscale-operator.") and context.endswith(".ts.net")):
        raise RuntimeError("unexpected Kubernetes context")
    targets = json.loads(run(sys.executable, "scripts/cluster-targets.py", "resolve",
                             "--format", "json", "--show-addresses"))["nodes"]
    # Resolver itself fails closed on incomplete inventory; require three nodes.
    if len(targets) != 3 or len({n["name"] for n in targets}) != 3:
        raise RuntimeError("incomplete or duplicate node inventory")
    workloads = json.loads(run("kubectl", "get", "pods,deployments,statefulsets,daemonsets,jobs,cronjobs,replicasets",
                               "-A", "-o", "json"))
    desired = workload_references(workloads["items"])
    # ReplicaSets preserve controller rollback references. Extra explicit pins
    # can be supplied without assuming that unused == safe to delete.
    report = {"measured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
              "authority": "read-only", "nodes": [], "workload_reference_count": len(desired)}
    for target in targets:
        node, address = target["name"], target["address"]
        talos = ("talosctl", "--talosconfig", str(ROOT / "talos/clusterconfig/talosconfig"),
                 "-e", address, "-n", address)
        images = parse_table(run(*talos, "image", "list", "--namespace", "cri"),
                             ("NODE", "IMAGE", "DIGEST", "SIZE", "LABELS", "CREATED"))
        runtime = parse_table(run(*talos, "containers", "--namespace", "cri"),
                              ("NODE", "NAMESPACE", "ID", "IMAGE", "PID", "STATUS"))
        for row in images + runtime:
            row.pop("NODE")
        result = classify(images, runtime, desired)
        result["node"] = node
        result["gc_window"] = gc_eligibility(run(*talos, "service", "kubelet"), dt.datetime.now(dt.timezone.utc))
        prefix = f"/api/v1/nodes/{node}/proxy/"
        config = json.loads(run("kubectl", "get", "--raw", prefix + "configz"))["kubeletconfig"]
        result["gc_policy"] = {k: config.get(k) for k in ["imageMaximumGCAge", "imageMinimumGCAge",
                                                        "imageGCHighThresholdPercent", "imageGCLowThresholdPercent"]}
        if result["gc_policy"]["imageMaximumGCAge"] != "168h0m0s" or \
                (config.get("imageGCHighThresholdPercent"), config.get("imageGCLowThresholdPercent")) != (85, 80):
            raise RuntimeError(f"unexpected image GC policy on {node}")
        stats = json.loads(run("kubectl", "get", "--raw", prefix + "stats/summary"))["node"]
        result["image_fs"] = stats["runtime"]["imageFs"]
        result["node_fs"] = stats["fs"]
        # containerFs may equal imageFs; deliberately do not sum it.
        report["nodes"].append(result)
    report["image_fs_used_bytes"] = sum(n["image_fs"]["usedBytes"] for n in report["nodes"])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Private, ignored JSON evidence path")
    parser.add_argument("--compare", type=Path, help="Previous private inventory JSON")
    args = parser.parse_args()
    if args.output and not args.output.resolve().is_relative_to(ROOT / ".private"):
        parser.error("evidence must be under .private to preserve inventory privacy")
    report = collect()
    if args.compare:
        previous = json.loads(args.compare.read_text())
        old = {n["node"]: n for n in previous["nodes"]}
        report["comparison"] = [{"node": n["node"],
                                 "image_fs_used_change_bytes": n["image_fs"]["usedBytes"] - old[n["node"]]["image_fs"]["usedBytes"],
                                 "node_fs_available_change_bytes": n["node_fs"]["availableBytes"] - old[n["node"]]["node_fs"]["availableBytes"],
                                 "digest_count_change": n["unique_digest_count"] - old[n["node"]]["unique_digest_count"]}
                                for n in report["nodes"]]
    if args.output:
        args.output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
        args.output.chmod(0o600)
    summary = {"measured_at": report["measured_at"], "image_fs_used_bytes": report["image_fs_used_bytes"],
               "nodes": [{k: n[k] for k in ["node", "reference_count", "unique_digest_count",
                                          "cri_managed_reference_count", "runtime_record_count",
                                          "candidate_reference_count", "candidate_unique_digest_count", "gc_window", "gc_policy"]}
                         for n in report["nodes"]]}
    if "comparison" in report:
        summary["comparison"] = report["comparison"]
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
