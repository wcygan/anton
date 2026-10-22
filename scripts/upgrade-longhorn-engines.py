#!/usr/bin/env python3
"""Plan, or explicitly execute, one adjacent V1 engine upgrade at a time.

Run through mise exec -- python3 scripts/upgrade-longhorn-engines.py --help.
The manager must already advertise the target image. Each volume requires a fresh
CSI snapshot carrying source-volume-uid/source-pvc-uid annotations in the
anton.wcygan.dev domain. No snapshots, backups, or exports are created here.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import re
import subprocess
import sys
import time


ANNOTATION = "anton.wcygan.dev/"
TARGETS = {"1.12.1", "1.13.0"}
IMAGE = re.compile(r"^(?:docker\.io/)?longhornio/longhorn-engine:v(1\.(?:11|12|13)\.\d+)$")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def version(image):
    match = IMAGE.fullmatch(image)
    require(match is not None, "Unrecognized engine image")
    return match[1]


def adjacent(old, target):
    require(target in TARGETS, "Target must be 1.12.1 or 1.13.0")
    current = version(old)
    require(current == target or (current.startswith("1.11.") and target == "1.12.1")
            or (current.startswith("1.12.") and target == "1.13.0"),
            "Only adjacent V1 engine upgrades are permitted")


def stamp(value):
    require(bool(value), "Missing snapshot creation timestamp")
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def fresh(value, now, max_age):
    age = now - stamp(value)
    return -60 <= age <= max_age


def snapshot_for(volume, pvs, pvcs, snapshots, contents, prefix, now, max_age):
    name = volume["metadata"]["name"]
    pvs = [p for p in pvs if p.get("spec", {}).get("csi", {}).get("driver") == "driver.longhorn.io"
           and p["spec"]["csi"].get("volumeHandle") == name]
    require(len(pvs) == 1, name + ": expected exactly one CSI PV")
    pv = pvs[0]
    claim = pv["spec"]["claimRef"]
    claims = [p for p in pvcs if p["metadata"]["uid"] == claim["uid"]
              and p["metadata"]["name"] == claim["name"]
              and p["metadata"]["namespace"] == claim["namespace"]
              and p.get("spec", {}).get("volumeName") == pv["metadata"]["name"]
              and p.get("status", {}).get("phase") == "Bound"]
    require(len(claims) == 1, name + ": source PVC identity mismatch")
    for snap in snapshots:
        meta, spec, status = snap["metadata"], snap.get("spec", {}), snap.get("status", {})
        annotations = meta.get("annotations", {})
        if not (meta["name"].startswith(prefix) and meta["namespace"] == claim["namespace"]
                and not meta.get("deletionTimestamp")
                and annotations.get(ANNOTATION + "source-volume-uid") == volume["metadata"]["uid"]
                and annotations.get(ANNOTATION + "source-pvc-uid") == claim["uid"]
                and spec.get("source", {}).get("persistentVolumeClaimName") == claim["name"]
                and spec.get("volumeSnapshotClassName") == "longhorn-wal-forensics"
                and status.get("readyToUse") is True and not status.get("error")):
            continue
        if not (fresh(meta.get("creationTimestamp"), now, max_age)
                and fresh(status.get("creationTime"), now, max_age)):
            continue
        for content in contents:
            cs, observed = content.get("spec", {}), content.get("status", {})
            ref = cs.get("volumeSnapshotRef", {})
            if (content["metadata"]["name"] == status.get("boundVolumeSnapshotContentName")
                    and not content["metadata"].get("deletionTimestamp")
                    and cs.get("driver") == "driver.longhorn.io"
                    and cs.get("deletionPolicy") == "Retain"
                    and cs.get("source", {}).get("volumeHandle") == name
                    and ref.get("uid") == meta["uid"] and ref.get("name") == meta["name"]
                    and ref.get("namespace") == meta["namespace"]
                    and observed.get("readyToUse") is True and not observed.get("error")):
                return {"namespace": meta["namespace"], "name": meta["name"], "uid": meta["uid"]}
    raise RuntimeError(name + ": no fresh ready snapshot bound to the exact source PVC/volume")


def healthy(volume, engines, replicas, expected_image=None):
    name, spec, status = volume["metadata"]["name"], volume["spec"], volume["status"]
    require(not volume["metadata"].get("deletionTimestamp"), name + ": volume deleting")
    require(spec.get("dataEngine") == "v1" and spec.get("numberOfReplicas") == 2,
            name + ": expected V1 with two replicas")
    require(status.get("state") == "attached" and status.get("robustness") == "healthy",
            name + ": volume is not attached and healthy")
    require(spec.get("image") == status.get("currentImage"), name + ": engine upgrade in progress")
    if expected_image:
        require(spec["image"] == expected_image, name + ": target image not active")
    require(not spec.get("migrationNodeID") and not status.get("currentMigrationNodeID")
            and spec.get("dataLocality") != "strict-local" and not status.get("restoreRequired"),
            name + ": migration, strict-local, or restore blocks upgrade")
    active = [e for e in engines if e.get("spec", {}).get("volumeName") == name
              and not e["metadata"].get("deletionTimestamp")]
    require(len(active) == 1, name + ": expected exactly one engine")
    engine = active[0]
    es = engine.get("status", {})
    require(es.get("currentState") == "running" and es.get("currentImage") == spec["image"],
            name + ": engine is not running the current image")
    modes = es.get("replicaModeMap", {})
    require(len(modes) == 2 and set(modes.values()) == {"RW"}, name + ": engine lacks two RW replicas")
    selected = [r for r in replicas if r.get("spec", {}).get("volumeName") == name
                and r["metadata"]["name"] in modes]
    require(len(selected) == 2, name + ": replica identities missing")
    for replica in selected:
        rs, state = replica["spec"], replica.get("status", {})
        require(not replica["metadata"].get("deletionTimestamp") and not rs.get("failedAt")
                and bool(rs.get("healthyAt")) and rs.get("active") is True
                and state.get("currentState") == "running" and state.get("currentImage") == spec["image"],
                name + ": replica is not active, healthy and running the current image")
    nodes = {status.get("currentNodeID"), *(r["spec"].get("nodeID") for r in selected)}
    require(None not in nodes and "" not in nodes and len({r["spec"]["nodeID"] for r in selected}) == 2,
            name + ": invalid node placement")
    return nodes


def images_ready(images, image, nodes):
    found = [e for e in images if e.get("spec", {}).get("image") == image]
    require(len(found) == 1, "Engine image missing or ambiguous: " + image)
    status = found[0].get("status", {})
    require(status.get("state") == "deployed" and all(status.get("nodeDeploymentMap", {}).get(n) is True for n in nodes),
            "Engine image unavailable on all engine/replica nodes: " + image)


def image_patch(volume, target):
    return [{"op": "test", "path": "/metadata/uid", "value": volume["metadata"]["uid"]},
            {"op": "test", "path": "/metadata/resourceVersion", "value": volume["metadata"]["resourceVersion"]},
            {"op": "test", "path": "/spec/image", "value": volume["spec"]["image"]},
            {"op": "replace", "path": "/spec/image", "value": target}]


class Cluster:
    def __init__(self, args):
        self.args = args

    def command(self, *args):
        result = subprocess.run(["mise", "exec", "--", "kubectl", "--kubeconfig", self.args.kubeconfig,
                                 "--context", self.args.context, "--request-timeout=20s", *args],
                                capture_output=True, text=True, timeout=40)
        error = re.sub(r"(?:[A-Za-z0-9-]+\.)+ts\.net", "<redacted>.ts.net", result.stderr)
        require(result.returncode == 0, "kubectl " + " ".join(args[:5]) + " failed: "
                + " ".join(error.split())[:240] + "; inspect cluster before retrying")
        return json.loads(result.stdout)

    def guard(self):
        namespace = self.command("get", "namespace", "kube-system", "-o", "json")
        require(namespace["metadata"]["uid"] == self.args.expected_kube_system_uid,
                "Unexpected kube-system UID")

    def items(self, resource, namespace="storage"):
        scope = ["-n", namespace] if namespace else ["-A"]
        return self.command("get", resource, *scope, "-o", "json")["items"]

    def state(self):
        self.guard()
        return {key: self.items(resource, namespace) for key, resource, namespace in [
            ("volumes", "volumes.longhorn.io", "storage"), ("engines", "engines.longhorn.io", "storage"),
            ("replicas", "replicas.longhorn.io", "storage"), ("images", "engineimages.longhorn.io", "storage"),
            ("nodes", "nodes.longhorn.io", "storage"),
            ("settings", "settings.longhorn.io", "storage"), ("pvs", "pv", ""),
            ("pvcs", "pvc", ""), ("snapshots", "volumesnapshots", ""),
            ("contents", "volumesnapshotcontents", "")]}


def preflight(state, args, expected_ids=None):
    volumes = sorted(state["volumes"], key=lambda v: v["metadata"]["name"])
    require(len(volumes) == args.expected_volume_count, "Unexpected volume count")
    identities = {v["metadata"]["name"]: v["metadata"]["uid"] for v in volumes}
    require(expected_ids is None or identities == expected_ids, "Volume fleet identities changed")
    settings = {s["metadata"]["name"]: s.get("value") for s in state["settings"]}
    target = settings.get("default-engine-image", "")
    require(version(target) == args.target, "Manager must advertise the target engine first")
    require(settings.get("concurrent-automatic-engine-upgrade-per-node-limit") == "0",
            "Automatic engine upgrades must be disabled for serial ownership")
    nodes = {node["metadata"]["name"] for node in state["nodes"]}
    require(bool(nodes) and all(not node["metadata"].get("deletionTimestamp") and any(
        condition.get("type") == "Ready" and condition.get("status") == "True"
        for condition in node.get("status", {}).get("conditions", [])) for node in state["nodes"]),
        "All Longhorn nodes must be ready")
    images_ready(state["images"], target, nodes)
    plan = []
    for volume in volumes:
        volume_nodes = healthy(volume, state["engines"], state["replicas"])
        require(volume_nodes <= nodes, "Volume refers to an unknown Longhorn node")
        adjacent(volume["spec"]["image"], args.target)
        images_ready(state["images"], volume["spec"]["image"], nodes)
        snap = snapshot_for(volume, state["pvs"], state["pvcs"], state["snapshots"], state["contents"],
                            args.snapshot_prefix, time.time(), args.snapshot_max_age_hours * 3600)
        plan.append({"volume": volume["metadata"]["name"], "uid": volume["metadata"]["uid"],
                     "from": volume["spec"]["image"], "to": target, "snapshot": snap,
                     "action": "complete" if volume["spec"]["image"] == target else "upgrade"})
    return identities, plan


def execute(cluster, args):
    identities, plan = preflight(cluster.state(), args)
    print(json.dumps({"execute": args.execute, "plan": plan}), flush=True)
    if not args.execute:
        return
    target = plan[0]["to"]
    for row in plan:
        state = cluster.state()
        _, current = preflight(state, args, identities)
        selected = next(v for v in state["volumes"] if v["metadata"]["name"] == row["volume"])
        if next(r for r in current if r["volume"] == row["volume"])["action"] == "complete":
            continue
        cluster.guard()
        cluster.command("-n", "storage", "patch", "volumes.longhorn.io", row["volume"], "--type=json",
                        "-p", json.dumps(image_patch(selected, target)), "-o", "json")
        deadline = time.monotonic() + args.timeout_seconds
        while True:
            observed = cluster.state()
            require({v["metadata"]["name"]: v["metadata"]["uid"] for v in observed["volumes"]} == identities,
                    "Volume fleet identities changed during upgrade")
            volume = next(v for v in observed["volumes"] if v["metadata"]["name"] == row["volume"])
            require(volume["spec"]["image"] == target, "Engine desired image changed externally")
            require(volume["status"].get("robustness") == "healthy"
                    and volume["status"].get("state") == "attached", "Volume degraded during upgrade; stop")
            for other in observed["volumes"]:
                if other["metadata"]["name"] != row["volume"]:
                    healthy(other, observed["engines"], observed["replicas"])
            try:
                healthy(volume, observed["engines"], observed["replicas"], target)
                break
            except RuntimeError:
                require(time.monotonic() < deadline, "Engine convergence timeout; no retry or rollback performed")
            time.sleep(min(5, max(0, deadline - time.monotonic())))
        print(json.dumps({"volume": row["volume"], "status": "verified", "image": target}), flush=True)
    preflight(cluster.state(), args, identities)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kubeconfig", required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--expected-kube-system-uid", required=True)
    parser.add_argument("--target", choices=sorted(TARGETS), required=True)
    parser.add_argument("--snapshot-prefix", required=True)
    parser.add_argument("--snapshot-max-age-hours", type=float, default=24)
    parser.add_argument("--expected-volume-count", type=int, default=18)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    require(bool(re.fullmatch(r"tailscale-operator\.[^.]+\.ts\.net", args.context)),
            "Expected Tailscale operator Kubernetes context")
    require(args.snapshot_prefix and args.snapshot_max_age_hours > 0 and args.timeout_seconds > 0
            and args.expected_volume_count > 0, "Invalid bounds")
    execute(Cluster(args), args)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
        print("Stopped: " + str(error), file=sys.stderr)
        sys.exit(1)
