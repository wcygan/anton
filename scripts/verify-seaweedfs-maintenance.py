#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Read-only audit of SeaweedFS volume placement for one-node maintenance."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


CONTEXT_RE = re.compile(r"^tailscale-operator\.[^.]+\.ts\.net$")
NAMESPACE = "storage"
SEAWEED_NAME = "seaweedfs"
VOLUME_SERVICE = "seaweedfs-volume-peer"
TOTAL_TIMEOUT = 15
REQUEST_TIMEOUT = "10s"


class AuditError(ValueError):
    pass


def _items(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, dict) or not isinstance(value.get("items"), list):
        raise AuditError(f"malformed {label}: expected items array")
    if not all(isinstance(item, dict) for item in value["items"]):
        raise AuditError(f"malformed {label}: item is not an object")
    return value["items"]


def parse_replica_placement(value: Any) -> str:
    """Decode SeaweedFS's native ReplicaPlacement JSON fields to its 3-digit form."""
    if not isinstance(value, dict):
        raise AuditError("malformed native ReplicaPlacement")
    counts = []
    for field in ("DiffDataCenterCount", "DiffRackCount", "SameRackCount"):
        count = value.get(field, 0)
        if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= 9:
            raise AuditError("malformed native ReplicaPlacement count")
        counts.append(count)
    return "".join(str(count) for count in counts)


def redact_tailnet(value: Any) -> Any:
    """Redact MagicDNS names from every JSON string, including status messages."""
    if isinstance(value, str):
        return re.sub(r"(?:[A-Za-z0-9-]+\.)+ts\.net", "<redacted>.ts.net", value)
    if isinstance(value, list):
        return [redact_tailnet(item) for item in value]
    if isinstance(value, dict):
        return {key: redact_tailnet(item) for key, item in value.items()}
    return value


def analyze(
    *,
    context: str,
    expected_context: str | None,
    kube_system: dict[str, Any],
    expected_kube_system_uid: str | None,
    seaweed: dict[str, Any],
    expected_seaweed_uid: str | None,
    statefulset: dict[str, Any],
    pods_response: dict[str, Any],
    nodes_response: dict[str, Any],
    pvcs_response: dict[str, Any],
    dir_status: dict[str, Any],
    vol_status: dict[str, Any],
    collection_filter: set[str] | None = None,
    observation_started_at: str | None = None,
) -> dict[str, Any]:
    """Analyze API responses without kubectl, network access, or mutable state."""
    if not isinstance(dir_status, dict) or not isinstance(dir_status.get("Topology"), dict):
        raise AuditError("malformed master /dir/status response")
    volumes = vol_status.get("Volumes") if isinstance(vol_status, dict) else None
    if not isinstance(volumes, dict) or not isinstance(volumes.get("DataCenters"), dict):
        raise AuditError("malformed master /vol/status response")

    context_shape_ok = bool(CONTEXT_RE.fullmatch(context))
    exact_context_match = expected_context is None or context == expected_context
    kube_uid = kube_system.get("metadata", {}).get("uid")
    seaweed_uid = seaweed.get("metadata", {}).get("uid")
    seaweed_namespace_ok = seaweed.get("metadata", {}).get("namespace") == NAMESPACE
    statefulset_namespace_ok = statefulset.get("metadata", {}).get("namespace") == NAMESPACE
    identity = {
        "contextShape": "tailscale-operator.<redacted>.ts.net" if context_shape_ok else "unexpected",
        "contextShapeValid": context_shape_ok,
        "expectedContextProvided": expected_context is not None,
        "exactContextMatch": exact_context_match,
        "kubeSystemUID": kube_uid,
        "expectedKubeSystemUIDProvided": expected_kube_system_uid is not None,
        "kubeSystemUIDMatch": expected_kube_system_uid is None or kube_uid == expected_kube_system_uid,
        "seaweedUID": seaweed_uid,
        "seaweedNamespaceMatch": seaweed_namespace_ok,
        "statefulsetNamespaceMatch": statefulset_namespace_ok,
        "expectedSeaweedUIDProvided": expected_seaweed_uid is not None,
        "seaweedUIDMatch": expected_seaweed_uid is None or seaweed_uid == expected_seaweed_uid,
    }
    identity_ok = (
        context_shape_ok and exact_context_match and bool(kube_uid) and bool(seaweed_uid)
        and identity["kubeSystemUIDMatch"] and identity["seaweedUIDMatch"]
        and seaweed_namespace_ok and statefulset_namespace_ok
    )

    statefulset_uid = statefulset.get("metadata", {}).get("uid")
    sts_owner_uids = {owner.get("uid") for owner in statefulset.get("metadata", {}).get("ownerReferences", [])}
    sts_owner_ok = bool(seaweed_uid and seaweed_uid in sts_owner_uids and seaweed_namespace_ok and statefulset_namespace_ok)
    nodes = {}
    for node in _items(nodes_response, "nodes"):
        name = node.get("metadata", {}).get("name")
        if name:
            nodes[name] = not node.get("metadata", {}).get("deletionTimestamp") and any(
                condition.get("type") == "Ready" and condition.get("status") == "True"
                for condition in node.get("status", {}).get("conditions", [])
            )
    pods: dict[str, dict[str, Any]] = {}
    pod_ips: dict[str, str] = {}
    for pod in _items(pods_response, "volume pods"):
        name = pod.get("metadata", {}).get("name")
        if not name:
            continue
        owners = pod.get("metadata", {}).get("ownerReferences", [])
        pod_owner_uids = {owner.get("uid") for owner in owners}
        pod_owner_ok = bool(statefulset_uid and statefulset_uid in pod_owner_uids and sts_owner_ok)
        node_name = pod.get("spec", {}).get("nodeName")
        pod_ready = not pod.get("metadata", {}).get("deletionTimestamp") and any(
            condition.get("type") == "Ready" and condition.get("status") == "True"
            for condition in pod.get("status", {}).get("conditions", [])
        )
        pods[name] = {
            "node": node_name,
            "namespace": pod.get("metadata", {}).get("namespace"),
            "nodeReady": bool(node_name and nodes.get(node_name)),
            "podReady": pod_ready,
            "ownerUIDValid": pod_owner_ok,
            "podIP": pod.get("status", {}).get("podIP"),
            "pvcClaims": [
                volume.get("persistentVolumeClaim", {}).get("claimName")
                for volume in pod.get("spec", {}).get("volumes", [])
                if volume.get("persistentVolumeClaim", {}).get("claimName")
            ],
        }
        if pod.get("status", {}).get("podIP"):
            pod_ips[pod["status"]["podIP"]] = name
    pvcs = {pvc.get("metadata", {}).get("name"): pvc for pvc in _items(pvcs_response, "PVCs")}

    topology = dir_status["Topology"]
    topology_nodes: dict[str, dict[str, Any]] = {}
    for dc in topology.get("DataCenters", []):
        for rack in dc.get("Racks", []):
            for server in rack.get("DataNodes", []):
                url = server.get("Url")
                if url:
                    topology_nodes[url] = {
                        "max": server.get("Max"), "used": server.get("Volumes"),
                        "rack": rack.get("Id"), "dataCenter": dc.get("Id"),
                    }

    layouts: dict[int, tuple[str, str]] = {}
    for layout in topology.get("Layouts", []):
        if not isinstance(layout, dict) or not isinstance(layout.get("writables"), list):
            raise AuditError("malformed master /dir/status layout")
        collection = layout.get("collection", "")
        replication = layout.get("replication")
        if not isinstance(collection, str) or not isinstance(replication, str):
            raise AuditError("malformed layout collection or replication")
        for volume_id in layout["writables"]:
            if not isinstance(volume_id, int):
                raise AuditError("malformed layout volume id")
            if volume_id in layouts and layouts[volume_id] != (collection, replication):
                raise AuditError(f"conflicting layout for volume {volume_id}")
            layouts[volume_id] = (collection, replication)

    physical: dict[int, list[dict[str, Any]]] = {}
    server_status: dict[str, dict[str, Any]] = {}
    unmapped: list[str] = []
    unready: list[str] = []
    unmapped_owners: list[str] = []
    for dc_name, data_centers in volumes["DataCenters"].items():
        if not isinstance(data_centers, dict):
            raise AuditError("malformed /vol/status data center")
        for rack_name, servers in data_centers.items():
            if not isinstance(servers, dict):
                raise AuditError("malformed /vol/status rack")
            for url, entries in servers.items():
                if not isinstance(entries, list):
                    raise AuditError("malformed /vol/status server volume list")
                host = url.split(":", 1)[0]
                dns_match = re.fullmatch(
                    rf"(seaweedfs-volume-\d+)\.{VOLUME_SERVICE}\.storage(?:\.svc(?:\.cluster\.local)?)?",
                    host,
                )
                pod_name = dns_match.group(1) if dns_match else pod_ips.get(host)
                pod = pods.get(pod_name)
                if pod and pod["namespace"] != NAMESPACE:
                    pod = None
                if not pod:
                    unmapped.append(url)
                    continue
                topology_active = url in topology_nodes
                if not topology_active:
                    unmapped.append(url)
                pvc_name = f"mount0-{pod_name}"
                pvc = pvcs.get(pvc_name)
                pvc_bound = bool(
                    pvc_name in pod["pvcClaims"] and pvc
                    and pvc.get("metadata", {}).get("namespace") == NAMESPACE
                    and pvc.get("status", {}).get("phase") == "Bound"
                )
                owner_ok = bool(pod["ownerUIDValid"] and sts_owner_ok and pvc_bound)
                server_status[url] = {
                    "pod": pod_name,
                    "node": pod["node"],
                    "nodeReady": pod["nodeReady"],
                    "podReady": pod["podReady"],
                    "activeTopology": topology_active,
                    "pvc": pvc_name,
                    "pvcBound": pvc_bound,
                    "pvcCapacity": pvc.get("status", {}).get("capacity", {}).get("storage") if pvc else None,
                    "ownerUIDValid": owner_ok,
                    "rack": rack_name,
                    "dataCenter": dc_name,
                }
                if not owner_ok:
                    unmapped_owners.append(url)
                if not (pod["nodeReady"] and pod["podReady"]):
                    unready.append(url)
                for entry in entries:
                    if not isinstance(entry, dict) or not isinstance(entry.get("Id"), int) or not isinstance(entry.get("Size"), int):
                        raise AuditError("malformed physical volume entry")
                    placement = parse_replica_placement(entry.get("ReplicaPlacement", {}))
                    physical.setdefault(entry["Id"], []).append({
                        "server": url, "pod": pod_name, "node": pod["node"],
                        "nodeReady": pod["nodeReady"], "podReady": pod["podReady"],
                        "activeTopology": topology_active,
                        "ownerUIDValid": owner_ok, "sizeBytes": entry["Size"],
                        "collection": entry.get("Collection", ""),
                        "replicaPlacement": placement,
                        "readOnly": entry.get("ReadOnly"),
                        "rack": rack_name,
                    })

    all_ids = sorted(physical)
    selected_ids = [
        volume_id for volume_id in all_ids
        if collection_filter is None or (
            layouts[volume_id][0] if volume_id in layouts else physical[volume_id][0]["collection"]
        ) in collection_filter
    ]
    collections: dict[str, dict[str, Any]] = {}
    volume_reports = []
    copy_safe: list[bool] = []
    for volume_id in selected_ids:
        copies = physical[volume_id]
        active_copies = [copy for copy in copies if copy["activeTopology"]]
        layout = layouts.get(volume_id)
        collection = layout[0] if layout else (active_copies or copies)[0]["collection"]
        placements = {copy["replicaPlacement"] for copy in active_copies}
        replication = next(iter(placements)) if len(placements) == 1 else None
        layout_matches = layout is None or layout == (collection, replication)
        ready_nodes = sorted({
            copy["node"] for copy in active_copies
            if copy["node"] and copy["nodeReady"] and copy["podReady"] and copy["ownerUIDValid"]
        })
        nodes_with_copies = sorted({copy["node"] for copy in active_copies if copy["node"]})
        sizes = {copy["sizeBytes"] for copy in active_copies}
        copy_collections = {copy["collection"] for copy in active_copies}
        collections_agree = copy_collections == {collection}
        placement_survives = (
            len(active_copies) >= 2 and len(ready_nodes) >= 2 and len(placements) == 1
            and layout_matches and collections_agree and len(sizes) == 1
            and replication is not None and replication != "000"
        )
        copy_safe.append(placement_survives)
        report = {
            "id": volume_id,
            "collection": collection,
            "currentReplication": replication,
            "copyCount": len(active_copies),
            "observedCopyCount": len(copies),
            "distinctNodeCount": len(nodes_with_copies),
            "distinctReadyNodeCount": len(ready_nodes),
            "nodes": nodes_with_copies,
            "readyNodes": ready_nodes,
            "writableLayoutReplication": layout[1] if layout else None,
            "writableLayoutPresent": layout is not None,
            "copyPlacementsAgree": len(placements) == 1,
            "layoutMatchesCopies": layout_matches,
            "reportedVolumeBytes": next(iter(sizes)) if len(sizes) == 1 else None,
            "copyReportedVolumeBytes": sum(copy["sizeBytes"] for copy in active_copies),
            "copySizesAgree": len(sizes) == 1,
            "copyCollectionsAgree": collections_agree,
            "hasCopiesSurvivingAnyOneNode": placement_survives,
            "copies": copies,
        }
        volume_reports.append(report)
        group = collections.setdefault(collection, {
            "volumeIDs": [], "reportedVolumeBytes": 0, "copyReportedVolumeBytes": 0,
        })
        group["volumeIDs"].append(volume_id)
        group["copyReportedVolumeBytes"] += report["copyReportedVolumeBytes"]
        if report["reportedVolumeBytes"] is not None:
            group["reportedVolumeBytes"] += report["reportedVolumeBytes"]

    slots = []
    for url, limits in topology_nodes.items():
        status = server_status.get(url)
        if not status:
            unmapped.append(url)
        used, maximum = limits["used"], limits["max"]
        if not isinstance(used, int) or not isinstance(maximum, int):
            raise AuditError("malformed topology slot counts")
        slots.append({
            "server": url,
            "pod": status.get("pod") if status else None,
            "node": status.get("node") if status else None,
            "used": used,
            "max": maximum,
            "free": maximum - used,
            "withinLimit": 0 <= used <= maximum,
        })

    # Each physical server is also represented in the volume map; retain topology
    # rows even when the master reports zero volumes on a server.
    known_urls = set(topology_nodes) | set(server_status)
    for url in sorted(known_urls):
        server_status.setdefault(url, {"pod": None, "node": None, "nodeReady": False, "podReady": False,
                                       "pvc": None, "pvcBound": False, "ownerUIDValid": False})

    without_writable_layout = sorted(set(selected_ids) - set(layouts))
    extra_layout_ids = sorted(set(layouts) - set(all_ids))
    issues = []
    if not identity_ok:
        issues.append("identity mismatch or invalid context")
    if unmapped:
        issues.append("unmapped volume server")
    if unready:
        issues.append("unready volume server")
    if unmapped_owners:
        issues.append("unmapped owner or unbound PVC")
    if any(not volume["copyPlacementsAgree"] or not volume["layoutMatchesCopies"] for volume in volume_reports):
        issues.append("per-copy replica placements disagree with each other or the writable layout")
    if any(not volume["copySizesAgree"] for volume in volume_reports):
        issues.append("replica copies report different volume sizes")
    if selected_ids and not all(copy_safe):
        issues.append("selected volumes lack observed nonzero two-node replica placement")
    if extra_layout_ids:
        issues.append("layout references missing physical volume")
    if any(not row["withinLimit"] for row in slots):
        issues.append("logical volume slot count outside configured limit")
    if not selected_ids:
        issues.append("selection contains no physical volumes")
    placement_survives = bool(selected_ids) and len(copy_safe) == len(selected_ids) and all(copy_safe)
    return {
        "observationStartedAtUTC": observation_started_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "observationCompletedAtUTC": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "identity": identity,
        "seaweedReady": seaweed.get("status", {}).get("conditions", []),
        "selection": {
            "collections": sorted(collection_filter) if collection_filter is not None else "all",
            "selectedVolumeIDs": selected_ids,
            "excludedVolumeIDs": sorted(set(all_ids) - set(selected_ids)),
            "allExistingVolumeIDs": all_ids,
        },
        "topology": {
            "max": topology.get("Max"),
            "free": topology.get("Free"),
            "used": topology.get("Max", 0) - topology.get("Free", 0),
            "racks": sorted({row["rack"] for row in topology_nodes.values()}),
            "servers": slots,
            "withinSlotLimits": bool(slots) and all(row["withinLimit"] for row in slots),
        },
        "collections": collections,
        "volumes": volume_reports,
        "serverMappings": server_status,
        "unmappedVolumeServers": sorted(set(unmapped)),
        "unreadyVolumeServers": sorted(set(unready)),
        "unmappedOwners": sorted(set(unmapped_owners)),
        "volumesWithoutWritableLayoutIDs": without_writable_layout,
        "layoutWithoutPhysicalVolumeIDs": extra_layout_ids,
        "hasCopiesSurvivingAnyOneNode": placement_survives and identity_ok and not unmapped and not unready and not unmapped_owners,
        "bytesAndCacheBehavior": "not_assessed; reported volume bytes and copy placement do not prove GET availability, cache freshness, or data integrity",
        "writesAvailability": "not_assessed; copy placement alone does not establish write availability",
        "auditPass": placement_survives and identity_ok and not unmapped and not unready and not unmapped_owners
                    and not extra_layout_ids and bool(slots)
                    and all(row["withinLimit"] for row in slots),
        "issues": issues,
    }


def kubectl_json(context: str, deadline: float, *args: str) -> dict[str, Any]:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise AuditError("read-only audit exceeded its 15 second deadline")
    command = ["mise", "exec", "--", "kubectl", f"--context={context}",
               f"--request-timeout={REQUEST_TIMEOUT}", *args]
    try:
        result = subprocess.run(command, cwd=Path.cwd(), text=True, capture_output=True,
                                check=True, timeout=min(remaining, TOTAL_TIMEOUT))
        value = json.loads(result.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError) as error:
        raise AuditError(f"read-only kubectl request failed: {args[0]}") from error
    if not isinstance(value, dict):
        raise AuditError(f"malformed kubectl response: {args[0]}")
    return value


def run_live(args: argparse.Namespace) -> dict[str, Any]:
    observation_started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    deadline = time.monotonic() + TOTAL_TIMEOUT
    try:
        context = subprocess.run(
            ["mise", "exec", "--", "kubectl", f"--request-timeout={REQUEST_TIMEOUT}", "config", "current-context"],
            cwd=Path.cwd(), text=True, capture_output=True, check=True,
            timeout=min(TOTAL_TIMEOUT, max(0, deadline - time.monotonic())),
        ).stdout.strip()
    except subprocess.SubprocessError as error:
        raise AuditError("could not identify the current Kubernetes context within the audit deadline") from error
    if not CONTEXT_RE.fullmatch(context) or (args.expected_context and context != args.expected_context):
        raise AuditError("current Kubernetes context failed the expected Tailscale identity check")
    kube_system = kubectl_json(context, deadline, "get", "namespace", "kube-system", "-o", "json")
    kube_uid = kube_system.get("metadata", {}).get("uid")
    if args.expected_kube_system_uid and kube_uid != args.expected_kube_system_uid:
        raise AuditError("kube-system UID did not match the expected cluster identity")
    seaweed = kubectl_json(context, deadline, "-n", NAMESPACE, "get", "seaweed", SEAWEED_NAME, "-o", "json")
    seaweed_uid = seaweed.get("metadata", {}).get("uid")
    if args.expected_seaweed_uid and seaweed_uid != args.expected_seaweed_uid:
        raise AuditError("Seaweed resource UID did not match the expected owner identity")
    statefulset = kubectl_json(context, deadline, "-n", NAMESPACE, "get", "statefulset", "seaweedfs-volume", "-o", "json")
    pods = kubectl_json(context, deadline, "-n", NAMESPACE, "get", "pods", "-l", "app.kubernetes.io/component=volume", "-o", "json")
    nodes = kubectl_json(context, deadline, "get", "nodes", "-o", "json")
    pvcs = kubectl_json(context, deadline, "-n", NAMESPACE, "get", "pvc", "-o", "json")
    dir_status = kubectl_json(context, deadline, "get", "--raw", "/api/v1/namespaces/storage/services/http:seaweedfs-master:9333/proxy/dir/status")
    vol_status = kubectl_json(context, deadline, "get", "--raw", "/api/v1/namespaces/storage/services/http:seaweedfs-master:9333/proxy/vol/status")
    return analyze(
        context=context, expected_context=args.expected_context,
        kube_system=kube_system, expected_kube_system_uid=args.expected_kube_system_uid,
        seaweed=seaweed, expected_seaweed_uid=args.expected_seaweed_uid,
        statefulset=statefulset, pods_response=pods, nodes_response=nodes,
        pvcs_response=pvcs, dir_status=dir_status, vol_status=vol_status,
        collection_filter=set(args.collection) if args.collection else None,
        observation_started_at=observation_started_at,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-context", help="exact context to require; output always redacts its tailnet")
    parser.add_argument("--expected-kube-system-uid")
    parser.add_argument("--expected-seaweed-uid")
    parser.add_argument("--collection", action="append", help="explicitly limit the report to this collection; repeatable")
    args = parser.parse_args()
    try:
        report = run_live(args)
    except (AuditError, subprocess.SubprocessError) as error:
        print(json.dumps({"capturedAtUTC": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                          "auditPass": False, "error": str(error)}), file=sys.stderr)
        return 2
    print(json.dumps(redact_tailnet(report), indent=2, sort_keys=True))
    return 0 if report["auditPass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
