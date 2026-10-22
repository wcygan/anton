#!/usr/bin/env python3
"""Cluster-only checkpoint coordinator and sealed, read-only restore sampler.

No production writes or quiescence. Success is a sampled crash-recovery rehearsal,
not a coordinated Harbor/Postgres restore or a full S3 integrity audit.
"""
import datetime
from email.utils import parsedate_to_datetime
import hashlib
import json
import os
import re
from pathlib import Path
import ssl
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

OWNER = "recovery.anton.wcygan.dev/owner"
GEN = "recovery.anton.wcygan.dev/generation"
NAME = "cluster-recovery"
PYTHON = "docker.io/library/python:3.14-alpine@sha256:f6a589d43c42b9e7f7dc67a12d37132491f362859a5d750607710cc56da3bc72"
WEED = "docker.io/chrislusf/seaweedfs:4.48@sha256:aba492e2a4e4c90bff795745e8e660affa1f09e7650f5981bd7bccd1a06cd931"
SCRIPT_SOURCE = Path(__file__).read_text()
INDEX_BUDGET = 16 * 2**20
BASES = {"pods": "/api/v1", "persistentvolumeclaims": "/api/v1", "configmaps": "/api/v1",
         "jobs": "/apis/batch/v1", "networkpolicies": "/apis/networking.k8s.io/v1",
         "volumesnapshots": "/apis/snapshot.storage.k8s.io/v1", "leases": "/apis/coordination.k8s.io/v1"}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def quantity(value):
    for suffix, scale in (("Ti", 2**40), ("Gi", 2**30), ("Mi", 2**20), ("Ki", 2**10)):
        if str(value).endswith(suffix):
            return int(float(str(value)[:-len(suffix)]) * scale)
    return int(value)


def sources(pods, pvcs):
    """Resolve mounted PVCs from actual owning pods, never historical PVC IDs."""
    found = []
    for namespace, component, count in (("storage", "volume", 3), ("storage", "filer", 2), ("observability", "loki", 1)):
        matching = []
        for pod in pods[namespace]:
            labels = pod["metadata"].get("labels", {})
            if component == "loki":
                selected = labels.get("app.kubernetes.io/name") == "loki" and pod["metadata"]["name"] == "loki-0"
            else:
                selected = labels.get("app.kubernetes.io/instance") == "seaweedfs" and labels.get("app.kubernetes.io/component") == component
            if selected and not pod["metadata"].get("deletionTimestamp"):
                require(any(c["type"] == "Ready" and c["status"] == "True" for c in pod.get("status", {}).get("conditions", [])), "Source pod is not Ready")
                matching.append(pod)
        require(len(matching) == count, "Unexpected source pod topology: " + component)
        for index, pod in enumerate(sorted(matching, key=lambda p: p["metadata"]["name"])):
            claims = [v["persistentVolumeClaim"]["claimName"] for v in pod["spec"]["volumes"] if "persistentVolumeClaim" in v]
            require(len(claims) == 1, "Ambiguous source data volume")
            pvc = pvcs[(namespace, claims[0])]
            require(pvc["status"]["phase"] == "Bound" and pvc["spec"].get("storageClassName") == "longhorn", "Source is not a Bound Longhorn PVC")
            found.append({"namespace": namespace, "pvc": claims[0], "uid": pvc["metadata"]["uid"], "pv": pvc["spec"]["volumeName"],
                          "size": pvc["spec"]["resources"]["requests"]["storage"], "label": component + str(index)})
    return found


def latest_index(path):
    require(path.stat().st_size % 16 == 0, "Truncated Seaweed index")
    require(path.stat().st_size < 256 * 2**20, "Index exceeds verifier memory budget")
    return {key: (offset, size) for key, offset, size in struct.iter_unpack(">QIi", path.read_bytes())}


def ready(conditions):
    return any(c.get("type") == "Ready" and c.get("status") == "True" for c in conditions)


def capacity_gate(nodes, selected):
    needed = sum(quantity(s["size"]) for s in selected)
    largest = max(quantity(s["size"]) for s in selected)
    eligible = []
    for node in nodes:
        if not node.get("spec", {}).get("allowScheduling") or not ready(node.get("status", {}).get("conditions", [])):
            continue
        if any(c.get("type") == "Schedulable" and c.get("status") != "True" for c in node.get("status", {}).get("conditions", [])):
            continue
        disks = []
        for name, spec in node.get("spec", {}).get("disks", {}).items():
            status = node.get("status", {}).get("diskStatus", {}).get(name, {})
            if spec.get("allowScheduling") and ready(status.get("conditions", [])) and not any(c.get("type") == "Schedulable" and c.get("status") != "True" for c in status.get("conditions", [])):
                disks.append(max(0, status.get("storageAvailable", 0) - spec.get("storageReserved", 0)))
        if disks and sum(disks) > needed * 1.2 and max(disks) > largest * 1.2:
            eligible.append(node["metadata"]["name"])
    require(len(set(eligible)) >= 2, "Two Ready schedulable nodes lack full restore-replica headroom after disk reserves plus 20 percent")


def payload(path, key, offset, size, cookie=None):
    require(offset > 0 and 4 <= size <= 64 * 2**20, "Invalid or oversized live record")
    with path.open("rb") as stream:
        stream.seek(offset * 8)
        header = stream.read(16)
        require(len(header) == 16, "Truncated Seaweed header")
        actual_cookie, actual_key, actual_size = struct.unpack(">IQi", header)
        require(actual_key == key and actual_size == size and (cookie is None or cookie == actual_cookie), "Seaweed header identity mismatch")
        body = stream.read(size)
        require(len(body) == size, "Truncated Seaweed payload")
        length = struct.unpack(">I", body[:4])[0]
        require(length + 4 <= size, "Seaweed payload length exceeds record")
        return body[4:4 + length]


def chunk_identity(chunk):
    fid = chunk.get("fid") or chunk.get("Fid")
    if fid:
        return int(fid.get("volume_id", fid.get("volumeId", 0))), int(fid.get("file_key", fid.get("fileKey", 0))), int(fid.get("cookie", 0))
    volume, tail = chunk.get("file_id", chunk.get("fileId", "")).split(",")
    require(len(tail) > 8, "Malformed filer chunk identity")
    return int(volume), int(tail[:-8], 16), int(tail[-8:], 16)


def local_json(port, path):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(urllib.request.Request("http://127.0.0.1:" + str(port) + path, headers={"Accept": "application/json"}), timeout=15) as response:
        return json.load(response)


def verify(root):
    """Hash real restored records plus filer-referenced Harbor/Loki payloads."""
    root = Path(root)
    if (root / "loki0").exists():
        files = sorted(p for p in (root / "loki0").rglob("*") if p.is_file() and not p.is_symlink() and p.stat().st_size)
        require(files, "Restored Loki PVC is empty")
        h = hashlib.sha256()
        sampled = 0
        for path in files[:32]:
            with path.open("rb") as stream:
                data = stream.read(2**20)
            h.update(data)
            sampled += len(data)
        return {"coverage": "Loki PVC filesystem sample; no Loki WAL replay", "files": min(32, len(files)), "bytes": sampled, "sha256": h.hexdigest()}
    indexes = {}
    checked = 0
    paths_by_volume = {label: list((root / label).rglob("*.idx")) for label in ("volume0", "volume1", "volume2")}
    require(sum(path.stat().st_size for paths in paths_by_volume.values() for path in paths) <= INDEX_BUDGET, "Total restored index bytes exceed memory budget")
    for label, paths in paths_by_volume.items():
        require(paths, "Restored volume has no Seaweed indexes")
        for path in paths:
            vid = int(path.stem.rsplit("_", 1)[-1])
            entries = latest_index(path)
            indexes.setdefault(vid, []).append((path, entries))
            live = [(k, o, s) for k, (o, s) in entries.items() if o > 0 and s > 0]
            for key, offset, size in live[:4]:
                hashlib.sha256(payload(path.with_suffix(".dat"), key, offset, size)).hexdigest()
                checked += 1
    require(checked, "No restored live Seaweed records")
    samples = {}
    unavailable = 0
    deadline = time.monotonic() + 900
    for port in (8888, 8889):
        while True:
            try:
                local_json(port, "/?limit=1")
                break
            except (OSError, ValueError):
                require(time.monotonic() < deadline, "Isolated filer startup deadline")
                time.sleep(2)
        for bucket in ("harbor", "loki"):
            pending = ["/buckets/" + bucket]
            inspected = 0
            sample = None
            while pending and sample is None:
                directory = pending.pop()
                cursor = ""
                while True:
                    require(time.monotonic() < deadline and inspected < 100000, "Filer sample search budget exhausted")
                    query = urllib.parse.urlencode({"limit": 1000, "lastFileName": cursor})
                    page = local_json(port, urllib.parse.quote(directory.rstrip("/") + "/", safe="/") + "?" + query)
                    for entry in page.get("Entries") or []:
                        inspected += 1
                        full = entry["FullPath"]
                        if int(entry.get("Mode", 0)) & (1 << 31):
                            pending.append(full)
                            continue
                        metadata = local_json(port, urllib.parse.quote(full, safe="/") + "?metadata=true")
                        chunks = metadata.get("chunks") or metadata.get("Chunks") or []
                        candidates = [c for c in chunks if not c.get("is_chunk_manifest", c.get("isChunkManifest", False)) and not c.get("cipher_key", c.get("cipherKey"))]
                        expected_digest = None
                        if bucket == "harbor":
                            match = re.search(r"/blobs/sha256/[0-9a-f]{2}/([0-9a-f]{64})/data$", full)
                            if not match or len(chunks) != 1 or len(candidates) != 1 or candidates[0].get("is_compressed", candidates[0].get("isCompressed", False)):
                                continue
                            expected_digest = match.group(1)
                        if not candidates:
                            continue
                        chunk = candidates[0]
                        vid, key, cookie = chunk_identity(chunk)
                        copies = indexes.get(vid, [])
                        hashes = []
                        for path, entries in copies:
                            offset, size = entries.get(key, (0, -1))
                            if offset == 0 or size <= 0:
                                continue
                            hashes.append(hashlib.sha256(payload(path.with_suffix(".dat"), key, offset, size, cookie)).hexdigest())
                        if not hashes:
                            unavailable += 1
                            continue
                        require(len(set(hashes)) == 1, "Referenced restored sample has divergent payload copies")
                        if expected_digest:
                            require(hashes[0] == expected_digest, "Restored Harbor blob failed its content-addressed SHA256")
                            if len(hashes) != 2:
                                unavailable += 1
                                continue
                        sample = {"payload_sha256": hashes[0], "path_sha256": hashlib.sha256(full.encode()).hexdigest(), "copies": len(hashes), "content_addressed_hash_checked": bool(expected_digest)}
                        break
                    if sample or not page.get("ShouldDisplayLoadMore"):
                        break
                    next_cursor = page.get("LastFileName")
                    require(next_cursor and next_cursor != cursor, "Filer pagination did not advance")
                    cursor = next_cursor
            require(sample, "No real referenced sample for " + bucket)
            samples[str(port) + "/" + bucket] = sample
    return {"coverage": "sampled Seaweed headers/payloads and two restored filer metadata stores; not full-reference audit or application-consistent restore", "record_samples": checked, "unavailable_reference_candidates": unavailable, "referenced_samples": samples}


class API:
    def __init__(self):
        token_root = Path("/var/run/secrets/kubernetes.io/serviceaccount")
        require(token_root.is_dir() and os.getenv("KUBERNETES_SERVICE_HOST"), "Coordinator must run inside cluster; no external exports")
        self.token = (token_root / "token").read_text().strip()
        self.base = "https://" + os.environ["KUBERNETES_SERVICE_HOST"] + ":" + os.environ.get("KUBERNETES_SERVICE_PORT", "443")
        self.ssl = ssl.create_default_context(cafile=str(token_root / "ca.crt"))

    def request(self, method, path, data=None):
        request = urllib.request.Request(self.base + path, data=None if data is None else json.dumps(data).encode(), method=method,
                                         headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(request, context=self.ssl, timeout=30) as response:
                    return json.load(response)
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    error.close()
                    return None
                status = {}
                try:
                    body = json.loads(error.read(4096))
                    if isinstance(body, dict) and body.get("kind") == "Status":
                        status = body
                except (ValueError, UnicodeError):
                    pass
                finally:
                    error.close()
                if method == "GET" and error.code == 429 and attempt < 3:
                    details = status.get("details") or {}
                    value = error.headers.get("Retry-After", str(details.get("retryAfterSeconds", 1)))
                    try:
                        delay = float(value)
                    except (ValueError, TypeError):
                        try:
                            delay = (parsedate_to_datetime(value) - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
                        except (ValueError, TypeError, OverflowError):
                            delay = 1
                    time.sleep(max(0, min(5, delay if delay == delay else 1)))
                    continue
                reason = str(status.get("reason", "HTTPError"))[:80]
                message = str(status.get("message", "No Kubernetes Status detail"))[:240]
                raise RuntimeError("Kubernetes API " + method + " " + path + " returned HTTP " + str(error.code) + " " + reason + ": " + message) from None

    def path(self, namespace, kind, name=""):
        return BASES[kind] + "/namespaces/" + namespace + "/" + kind + ("/" + name if name else "")

    def get(self, namespace, kind, name):
        return self.request("GET", self.path(namespace, kind, name))

    def list(self, namespace, kind, owned=False):
        query = "?labelSelector=" + urllib.parse.quote(OWNER + "=" + NAME) if owned else ""
        return self.request("GET", self.path(namespace, kind) + query)["items"]

    def create(self, namespace, kind, body):
        return self.request("POST", self.path(namespace, kind), body)

    def delete_owned(self, namespace, kind, obj):
        require(obj["metadata"].get("labels", {}).get(OWNER) == NAME, "Cleanup ownership mismatch")
        current = self.get(namespace, kind, obj["metadata"]["name"])
        if current is None:
            return
        require(current["metadata"]["uid"] == obj["metadata"]["uid"] and current["metadata"].get("labels", {}).get(OWNER) == NAME, "Cleanup UID mismatch")
        self.request("DELETE", self.path(namespace, kind, obj["metadata"]["name"]), {"apiVersion": "v1", "kind": "DeleteOptions", "preconditions": {"uid": obj["metadata"]["uid"]}, "propagationPolicy": "Foreground"})
        end = time.monotonic() + 240
        while self.get(namespace, kind, obj["metadata"]["name"]):
            require(time.monotonic() < end, "Cleanup deadline; retaining journal for retry")
            time.sleep(3)


def coordinate():
    api = API()
    generation = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:6]
    now = datetime.datetime.now(datetime.timezone.utc)
    lease = api.get("storage", "leases", NAME)
    require(lease is not None, "Missing operator-owned Lease")
    previous = lease.get("spec", {})
    if previous.get("holderIdentity"):
        expiry = datetime.datetime.fromisoformat(previous["renewTime"].replace("Z", "+00:00")) + datetime.timedelta(seconds=previous["leaseDurationSeconds"])
        require(expiry < now, "Another checkpoint run holds the Lease")
    lease["spec"] = {"holderIdentity": generation, "leaseDurationSeconds": 4200, "renewTime": now.isoformat().replace("+00:00", "Z")}
    api.request("PUT", api.path("storage", "leases", NAME), lease)
    journal = api.get("storage", "configmaps", NAME + "-journal")
    require(journal is not None, "Missing checkpoint journal")
    last_verified = journal.get("data", {}).get("verified", "")
    previous_verified = journal.get("data", {}).get("previous_verified", "")
    resources = []
    registry = json.loads(journal.get("data", {}).get("registry", "[]"))

    def save(phase, **extra):
        journal["data"] = {**journal.get("data", {}), "verified": last_verified, "previous_verified": previous_verified, "run": generation, "phase": phase, "resources": json.dumps(resources), "registry": json.dumps(registry), **extra}
        updated = api.request("PUT", api.path("storage", "configmaps", journal["metadata"]["name"]), journal)
        journal.update(updated)

    def clean(except_generation):
        for namespace in ("storage", "observability"):
            for kind in ("jobs", "persistentvolumeclaims", "networkpolicies", "configmaps", "volumesnapshots"):
                for obj in api.list(namespace, kind, owned=True):
                    if GEN not in obj["metadata"].get("labels", {}) or (kind == "volumesnapshots" and obj["metadata"]["labels"][GEN] in except_generation):
                        continue
                    identity = {"namespace": namespace, "kind": kind, "name": obj["metadata"]["name"], "uid": obj["metadata"]["uid"]}
                    require(identity in registry, "Unknown owned resource UID; refusing cleanup until operator review")
                    api.delete_owned(namespace, kind, obj)
                    registry.remove(identity)

    def create(namespace, kind, body):
        body["metadata"].setdefault("labels", {}).update({OWNER: NAME, GEN: generation})
        created = api.create(namespace, kind, body)
        identity = {"namespace": namespace, "kind": kind, "name": created["metadata"]["name"], "uid": created["metadata"]["uid"]}
        resources.append(identity)
        registry.append(identity)
        save("running")
        return created

    def wait(namespace, kind, name, predicate, timeout=600):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            obj = api.get(namespace, kind, name)
            if obj and predicate(obj):
                return obj
            time.sleep(5)
        raise RuntimeError("Deadline waiting for owned " + kind)

    failure = None
    uncertain_generations = set()
    try:
        clean({last_verified, previous_verified})
        save("preflight")
        pods = {ns: api.list(ns, "pods") for ns in ("storage", "observability")}
        pvcs = {(ns, pvc["metadata"]["name"]): pvc for ns in pods for pvc in api.list(ns, "persistentvolumeclaims")}
        selected = sources(pods, pvcs)
        volumes = api.request("GET", "/apis/longhorn.io/v1beta2/namespaces/storage/volumes")["items"]
        source_volumes = [v for v in volumes if v["metadata"]["name"] in {s["pv"] for s in selected}]
        require(len(source_volumes) == 6 and all(v.get("status", {}).get("robustness") == "healthy" for v in source_volumes), "Source Longhorn health gate failed")
        nodes = api.request("GET", "/apis/longhorn.io/v1beta2/namespaces/storage/nodes")["items"]
        capacity_gate(nodes, selected)
        for source in selected:
            current = api.get(source["namespace"], "persistentvolumeclaims", source["pvc"])
            require(current["metadata"]["uid"] == source["uid"] and current["spec"]["volumeName"] == source["pv"], "Source PVC identity changed")
            name = "recovery-" + generation + "-" + source["label"]
            snapshot = create(source["namespace"], "volumesnapshots", {"apiVersion": "snapshot.storage.k8s.io/v1", "kind": "VolumeSnapshot", "metadata": {"name": name}, "spec": {"volumeSnapshotClassName": "longhorn-recurring-recovery", "source": {"persistentVolumeClaimName": source["pvc"]}}})
            ready = wait(source["namespace"], "volumesnapshots", name, lambda o: o.get("status", {}).get("readyToUse") is True)
            require(ready["metadata"]["uid"] == snapshot["metadata"]["uid"], "Snapshot UID changed")
            content = api.request("GET", "/apis/snapshot.storage.k8s.io/v1/volumesnapshotcontents/" + ready["status"]["boundVolumeSnapshotContentName"])
            pv = api.request("GET", "/api/v1/persistentvolumes/" + source["pv"])
            require(pv["spec"]["claimRef"]["uid"] == source["uid"], "PV claim UID binding mismatch")
            require(content["spec"]["source"]["volumeHandle"] == pv["spec"]["csi"]["volumeHandle"] and content["spec"]["volumeSnapshotRef"]["uid"] == snapshot["metadata"]["uid"], "Snapshot source binding mismatch")
            source["clone"] = name + "-restore"
            clone = create(source["namespace"], "persistentvolumeclaims", {"apiVersion": "v1", "kind": "PersistentVolumeClaim", "metadata": {"name": source["clone"]}, "spec": {"accessModes": ["ReadWriteOnce"], "storageClassName": "longhorn", "resources": {"requests": {"storage": source["size"]}}, "dataSource": {"apiGroup": "snapshot.storage.k8s.io", "kind": "VolumeSnapshot", "name": name}}})
            source["clone_uid"] = clone["metadata"]["uid"]
        summaries = {}
        for namespace in ("storage", "observability"):
            name = "recovery-" + generation
            create(namespace, "configmaps", {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": name}, "immutable": True, "data": {"run.py": SCRIPT_SOURCE}})
            gate = create(namespace, "configmaps", {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": name + "-gate"}, "data": {"ready": "wait"}})
            create(namespace, "networkpolicies", {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy", "metadata": {"name": name}, "spec": {"podSelector": {"matchLabels": {GEN: generation}}, "policyTypes": ["Ingress", "Egress"], "ingress": [], "egress": []}})
            job = create(namespace, "jobs", reader_job(name, generation, [s for s in selected if s["namespace"] == namespace]))
            for source in [s for s in selected if s["namespace"] == namespace]:
                def healthy_clone(obj):
                    require(obj["metadata"]["uid"] == source["clone_uid"], "Clone PVC identity changed")
                    if obj.get("status", {}).get("phase") != "Bound":
                        return False
                    volume = api.request("GET", "/apis/longhorn.io/v1beta2/namespaces/storage/volumes/" + obj["spec"]["volumeName"])
                    return volume and volume.get("status", {}).get("robustness") == "healthy" and volume["status"].get("state") == "attached"
                wait(namespace, "persistentvolumeclaims", source["clone"], healthy_clone)
            gate_current = api.get(namespace, "configmaps", name + "-gate")
            require(gate_current["metadata"]["uid"] == gate["metadata"]["uid"], "Verifier gate identity changed")
            gate_current["data"]["ready"] = "allow"
            api.request("PUT", api.path(namespace, "configmaps", name + "-gate"), gate_current)
            def finished(obj):
                conditions = obj.get("status", {}).get("conditions", [])
                if any(c["type"] == "Failed" and c["status"] == "True" for c in conditions):
                    messages = []
                    for pod in api.list(namespace, "pods"):
                        if any(owner.get("uid") == job["metadata"]["uid"] for owner in pod["metadata"].get("ownerReferences", [])):
                            for container in pod.get("status", {}).get("containerStatuses", []) + pod.get("status", {}).get("initContainerStatuses", []):
                                terminated = container.get("state", {}).get("terminated", {})
                                if terminated.get("message"):
                                    messages.append(terminated["message"][:240])
                    raise RuntimeError("Isolated restored-data verifier failed: " + "; ".join(messages)[:240])
                return any(c["type"] == "Complete" and c["status"] == "True" for c in conditions)
            wait(namespace, "jobs", name, finished, 1500)
            completed_pods = [p for p in api.list(namespace, "pods") if any(o.get("uid") == job["metadata"]["uid"] for o in p["metadata"].get("ownerReferences", []))]
            require(len(completed_pods) == 1, "Ambiguous verifier Pod evidence")
            terminated = next(c["state"]["terminated"] for c in completed_pods[0]["status"]["containerStatuses"] if c["name"] == "reader")
            require(terminated["exitCode"] == 0, "Verifier reader did not succeed")
            summaries[namespace] = json.loads(terminated["message"])
        save("verified", verified=generation, previous_verified=last_verified, verified_report=json.dumps(summaries), sources=json.dumps(selected))
        previous_verified, last_verified = last_verified, generation
        clean({last_verified, previous_verified})
        save("complete", verified_report=json.dumps(summaries), sources=json.dumps(selected))
        print(json.dumps({"generation": generation, "verified": True, "coverage": "sampled crash-consistent in-cluster restores; no coordinated application recovery"}))
    except Exception as error:
        failure = error
        try:
            durable = api.get("storage", "configmaps", NAME + "-journal")
            require(durable is not None, "Checkpoint journal disappeared")
            journal.update(durable)
            if durable.get("data", {}).get("verified") == generation:
                require(durable["data"].get("verified_report"), "Published checkpoint lacks verification evidence")
                last_verified = generation
                previous_verified = durable["data"].get("previous_verified", "")
        except Exception:
            # If a journal PUT committed but its response/read failed, retain the
            # candidate until a later run can establish the durable truth.
            uncertain_generations.add(generation)
        try:
            save("failed", error=str(error)[:240])
        except Exception:
            print(json.dumps({"journal_update_failed": True, "run": generation}), flush=True)
        raise
    finally:
        try:
            clean({last_verified, previous_verified} | uncertain_generations)
            try:
                save("failed" if failure else "complete")
            except Exception:
                if not failure:
                    raise
        except Exception as cleanup_error:
            if not failure:
                raise
            print(json.dumps({"cleanup_failed": True, "run": generation, "error": str(cleanup_error)[:240]}), flush=True)
        finally:
            try:
                current = api.get("storage", "leases", NAME)
                if current and current.get("spec", {}).get("holderIdentity") == generation:
                    current["spec"]["holderIdentity"] = ""
                    api.request("PUT", api.path("storage", "leases", NAME), current)
            except Exception:
                if not failure:
                    raise
                print(json.dumps({"lease_release_failed": True, "run": generation}), flush=True)


def reader_job(name, generation, selected):
    security = {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]}, "seccompProfile": {"type": "RuntimeDefault"}}
    volumes = [{"name": "code", "configMap": {"name": name}}, {"name": "gate", "configMap": {"name": name + "-gate"}}, {"name": "work", "emptyDir": {"sizeLimit": "8Gi"}}]
    mounts = [{"name": "code", "mountPath": "/code", "readOnly": True}, {"name": "gate", "mountPath": "/gate", "readOnly": True}, {"name": "work", "mountPath": "/work"}]
    for source in selected:
        volumes.append({"name": source["label"], "persistentVolumeClaim": {"claimName": source["clone"], "readOnly": True}})
        mounts.append({"name": source["label"], "mountPath": "/restore/" + source["label"], "readOnly": True})
    reader = {"name": "reader", "image": PYTHON, "command": ["python3", "-u", "/code/run.py", "verify", "/restore"], "volumeMounts": mounts, "securityContext": security, "resources": {"requests": {"cpu": "100m", "memory": "128Mi"}, "limits": {"cpu": "500m", "memory": "1Gi"}}}
    wait_container = {"name": "wait-for-healthy-clones", "image": PYTHON, "command": ["python3", "/code/run.py", "wait"], "volumeMounts": mounts, "securityContext": security, "resources": {"requests": {"cpu": "1m", "memory": "16Mi"}, "limits": {"cpu": "10m", "memory": "32Mi"}}}
    spec = {"automountServiceAccountToken": False, "restartPolicy": "Never", "securityContext": {"runAsUser": 0, "seccompProfile": {"type": "RuntimeDefault"}}, "volumes": volumes, "containers": [reader], "initContainers": [wait_container]}
    if any(s["label"] == "filer0" for s in selected):
        spec["initContainers"] += [{"name": "copy-filers", "image": PYTHON, "command": ["python3", "/code/run.py", "copy"], "volumeMounts": mounts, "securityContext": security, "resources": {"requests": {"cpu": "100m", "memory": "64Mi"}, "limits": {"cpu": "500m", "memory": "256Mi"}}},
                                  {"name": "sealed-filers", "image": WEED, "restartPolicy": "Always", "command": ["/bin/sh", "-ec", "weed master -ip=127.0.0.1 -ip.bind=127.0.0.1 -mdir=/work/master -peers=127.0.0.1:9333 -telemetry=false >/work/master.log 2>&1 & cd /work/filer0; weed filer -master=127.0.0.1:9333 -ip=127.0.0.1 -ip.bind=127.0.0.1 -port=8888 -filerGroup=recovery0 -localSocket=/work/f0.sock >/work/f0.log 2>&1 & cd /work/filer1; weed filer -master=127.0.0.1:9333 -ip=127.0.0.1 -ip.bind=127.0.0.1 -port=8889 -filerGroup=recovery1 -localSocket=/work/f1.sock >/work/f1.log 2>&1 & wait"], "volumeMounts": [{"name": "work", "mountPath": "/work"}], "securityContext": security, "resources": {"requests": {"cpu": "100m", "memory": "128Mi"}, "limits": {"cpu": "500m", "memory": "1Gi"}}}]
    return {"apiVersion": "batch/v1", "kind": "Job", "metadata": {"name": name}, "spec": {"backoffLimit": 0, "activeDeadlineSeconds": 1400, "template": {"metadata": {"labels": {GEN: generation, OWNER: NAME}}, "spec": spec}}}


def copy_filers():
    import shutil
    (Path("/work") / "master").mkdir()
    for label in ("filer0", "filer1"):
        paths = list((Path("/restore") / label).rglob("filerldb2"))
        require(len(paths) == 1 and paths[0].is_dir(), "Expected one LevelDB store")
        files = list(paths[0].rglob("*"))
        require(not any(p.is_symlink() for p in files), "Filer store has symlinks")
        require(sum(p.stat().st_size for p in files if p.is_file()) < 3 * 2**30, "Filer copy exceeds scratch budget")
        target = Path("/work") / label
        target.mkdir()
        shutil.copytree(paths[0], target / "filerldb2")
        (target / "filer.toml").write_text('[leveldb2]\nenabled=true\ndir="/work/' + label + '/filerldb2"\n')


if __name__ == "__main__":
    try:
        mode = sys.argv[1] if len(sys.argv) > 1 else "coordinate"
        if mode == "verify":
            summary = json.dumps(verify(sys.argv[2]))
            require(len(summary.encode()) < 4000, "Verifier summary exceeds termination-message limit")
            Path("/dev/termination-log").write_text(summary)
            print(summary, flush=True)
        elif mode == "copy":
            copy_filers()
        elif mode == "wait":
            deadline = time.monotonic() + 900
            while Path("/gate/ready").read_text().strip() != "allow":
                require(time.monotonic() < deadline, "Clone health gate deadline")
                time.sleep(5)
        elif mode == "coordinate":
            coordinate()
        else:
            raise RuntimeError("Unknown mode")
    except Exception as error:
        summary = json.dumps({"verified": False, "error": str(error)[:240]})
        if mode in ("verify", "copy", "wait"):
            Path("/dev/termination-log").write_text(summary)
        print(summary, flush=True)
        sys.exit(1)
