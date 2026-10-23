#!/usr/bin/env python3
"""Remove explicitly released maintenance snapshots through their CSI owner."""
import datetime
import importlib.util
import json
from pathlib import Path
import sys
import time
import uuid

source = Path(__file__).with_name("run.py")
if not source.exists():
    source = Path(__file__).with_name("cluster-recovery-checkpoints.py")
spec = importlib.util.spec_from_file_location("recovery", source)
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)
require = recovery.require

RELEASE = "retention.anton.wcygan.dev/released-uid"
AFTER = "retention.anton.wcygan.dev/delete-after"
CLASS = "longhorn-wal-forensics"
BOUND = "snapshot.storage.kubernetes.io/volumesnapshot-bound-protection"
NAMESPACES = ("storage", "observability", "registries")
CONTENT = "/apis/snapshot.storage.k8s.io/v1/volumesnapshotcontents/"
LONGHORN = "/apis/longhorn.io/v1beta2/namespaces/storage/"


def released(snapshot, now):
    metadata = snapshot["metadata"]
    annotations = metadata.get("annotations", {})
    if RELEASE not in annotations and AFTER not in annotations:
        return False
    require(annotations.get(RELEASE) == metadata["uid"], "Release UID mismatch")
    require(snapshot["spec"].get("volumeSnapshotClassName") == CLASS, "Only maintenance snapshots may be released")
    labels = metadata.get("labels", {})
    require(recovery.OWNER not in labels and recovery.GEN not in labels, "Recovery checkpoints are protected")
    expiry = datetime.datetime.fromisoformat(annotations.get(AFTER, "").replace("Z", "+00:00"))
    require(expiry.tzinfo is not None, "Deletion time must include timezone")
    return expiry <= now


def binding(snapshot, content, pvcs):
    metadata = snapshot["metadata"]
    require(content is not None, "Snapshot content is missing")
    ref = content["spec"]["volumeSnapshotRef"]
    require((ref.get("namespace"), ref.get("name"), ref.get("uid")) ==
            (metadata["namespace"], metadata["name"], metadata["uid"]), "Snapshot content binding mismatch")
    require(content["spec"].get("volumeSnapshotClassName") == CLASS and
            content["spec"].get("driver") == "driver.longhorn.io", "Unexpected snapshot driver/class")
    require(content["spec"]["deletionPolicy"] in ("Retain", "Delete"), "Unexpected deletion policy")
    handle = content.get("status", {}).get("snapshotHandle", "")
    parts = handle.split("/")
    require(len(parts) == 4 and parts[:2] == ["snap:", ""] and all(parts[2:]), "Not a native Longhorn snapshot")
    require(content["spec"].get("source", {}).get("volumeHandle") == parts[2], "Snapshot volume mismatch")
    for pvc in pvcs:
        for key in ("dataSource", "dataSourceRef"):
            data = pvc["spec"].get(key) or {}
            namespace = data.get("namespace") or pvc["metadata"]["namespace"]
            require(not (data.get("kind") == "VolumeSnapshot" and data.get("name") == metadata["name"] and
                         namespace == metadata["namespace"]), "Snapshot has a restore consumer")
    return parts[2], parts[3]


def health(api):
    journal = api.get("storage", "configmaps", "cluster-recovery-journal")["data"]
    require(journal.get("phase") == "complete" and journal.get("verified_report"), "Recovery journal is not complete")
    generations = {journal.get("verified"), journal.get("previous_verified")}
    require(len(generations) == 2 and None not in generations and "" not in generations, "Two verified generations required")
    snapshots = [s for namespace in NAMESPACES for s in api.list(namespace, "volumesnapshots")]
    for generation in generations:
        protected = [s for s in snapshots if s["metadata"].get("labels", {}).get(recovery.GEN) == generation
                     and s["metadata"].get("labels", {}).get(recovery.OWNER) == recovery.NAME]
        require(len(protected) == 6 and all(s.get("status", {}).get("readyToUse") and
                not s["metadata"].get("deletionTimestamp") for s in protected), "Verified snapshots are not all Ready")
    volumes = api.request("GET", LONGHORN + "volumes")["items"]
    require(volumes and all(v.get("status", {}).get("robustness") == "healthy" and
                           v.get("status", {}).get("state") == "attached" for v in volumes), "Longhorn volumes are not healthy/attached")
    return snapshots


def wait_absent(api, path, uid):
    end = time.monotonic() + 240
    while True:
        current = api.request("GET", path)
        if current is None:
            return
        require(current["metadata"]["uid"] == uid, "Object was replaced while waiting for deletion")
        require(time.monotonic() < end, "CSI deletion timed out; stop and inspect before retry")
        time.sleep(2)


def remove(api, candidate, now):
    namespace, name, uid = (candidate["metadata"][k] for k in ("namespace", "name", "uid"))
    current = api.get(namespace, "volumesnapshots", name)
    if current is None:
        return
    require(current["metadata"]["uid"] == uid, "Snapshot UID changed")
    require(released(current, now), "Snapshot release was revoked or deferred")
    content_name = current.get("status", {}).get("boundVolumeSnapshotContentName")
    require(content_name, "Snapshot is not bound")
    path = CONTENT + content_name
    content = api.request("GET", path)
    pvcs = api.request("GET", "/api/v1/persistentvolumeclaims")["items"]
    volume, backend = binding(current, content, pvcs)
    if content["spec"]["deletionPolicy"] == "Retain":
        content["spec"]["deletionPolicy"] = "Delete"
        updated = api.request("PUT", path, content)
        require(updated is not None and updated["metadata"]["uid"] == content["metadata"]["uid"] and
                updated["spec"]["deletionPolicy"] == "Delete", "Content policy update was not confirmed")
    end = time.monotonic() + 240
    while True:
        current = api.get(namespace, "volumesnapshots", name)
        if current is None:
            break
        require(current["metadata"]["uid"] == uid, "Snapshot changed after policy update")
        require(released(current, now), "Snapshot release was revoked after policy update")
        require(current.get("status", {}).get("boundVolumeSnapshotContentName") == content_name,
                "Snapshot binding changed after policy update")
        if BOUND in current["metadata"].get("finalizers", []):
            api.request("DELETE", api.path(namespace, "volumesnapshots", name), {
                "apiVersion": "v1", "kind": "DeleteOptions", "preconditions": {
                    "uid": uid, "resourceVersion": current["metadata"]["resourceVersion"]}})
            break
        require(time.monotonic() < end, "CSI has not installed Delete-policy protection")
        time.sleep(2)
    wait_absent(api, api.path(namespace, "volumesnapshots", name), uid)
    wait_absent(api, path, content["metadata"]["uid"])
    end = time.monotonic() + 240
    while True:
        snapshot = api.request("GET", LONGHORN + "snapshots/" + backend)
        if snapshot is None:
            break
        require(snapshot["spec"]["volume"] == volume, "Backend snapshot volume changed")
        if snapshot.get("status", {}).get("markRemoved"):
            break
        require(time.monotonic() < end, "Backend retirement timed out")
        time.sleep(2)
    print(json.dumps({"deleted": namespace + "/" + name, "uid": uid, "backend": backend}), flush=True)


def main(apply=False):
    api = recovery.API()
    holder = "retention-" + uuid.uuid4().hex
    lease = None
    try:
        if apply:
            now = datetime.datetime.now(datetime.timezone.utc)
            lease = api.get("storage", "leases", recovery.NAME)
            require(lease is not None, "Missing recovery Lease")
            previous = lease.get("spec", {})
            if previous.get("holderIdentity"):
                expiry = datetime.datetime.fromisoformat(previous["renewTime"].replace("Z", "+00:00")) + datetime.timedelta(seconds=previous["leaseDurationSeconds"])
                require(expiry < now, "Recovery run is active")
            lease["spec"] = {"holderIdentity": holder, "leaseDurationSeconds": 4200, "renewTime": now.isoformat()}
            lease = api.request("PUT", api.path("storage", "leases", recovery.NAME), lease)
        now = datetime.datetime.now(datetime.timezone.utc)
        candidates = sorted((s for s in health(api) if released(s, now)), key=lambda s: (s["metadata"]["creationTimestamp"], s["metadata"]["name"]))
        print(json.dumps({"mode": "apply" if apply else "plan", "candidates": [{k: s["metadata"][k] for k in ("namespace", "name", "uid")} for s in candidates]}), flush=True)
        for snapshot in candidates:
            if apply:
                health(api)
                remove(api, snapshot, now)
        if apply:
            health(api)
        print(json.dumps({"complete": True, "count": len(candidates), "mode": "apply" if apply else "plan"}), flush=True)
    finally:
        if lease:
            current = api.get("storage", "leases", recovery.NAME)
            if current and current.get("spec", {}).get("holderIdentity") == holder:
                current["spec"]["holderIdentity"] = ""
                api.request("PUT", api.path("storage", "leases", recovery.NAME), current)


if __name__ == "__main__":
    require(sys.argv[1:] in ([], ["apply"]), "Usage: snapshot-retention.py [apply]")
    main(sys.argv[1:] == ["apply"])
