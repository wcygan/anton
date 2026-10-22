"""Exercise actual restore readers and destructive-cleanup boundary failures."""
import importlib.util
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[2] / "kubernetes/apps/storage/longhorn-maintenance/app/cluster-recovery-checkpoints.py"
spec = importlib.util.spec_from_file_location("recovery", SOURCE)
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


class APIProtocolTests(unittest.TestCase):
    def setUp(self):
        self.api = object.__new__(recovery.API)
        self.api.base = "https://kubernetes.example:443"
        self.api.token = "unit-test-token-not-for-output"
        self.api.ssl = None
        self.path = "/apis/longhorn.io/v1beta2/namespaces/storage/nodes"

    def failure(self, code=429, retry_after="1"):
        status = {"kind": "Status", "reason": "TooManyRequests" if code == 429 else "Forbidden", "message": "storage is (re)initializing" if code == 429 else "request forbidden", "details": {"retryAfterSeconds": 1}}
        return recovery.urllib.error.HTTPError(self.api.base + self.path, code, "HTTP failure", {"Retry-After": retry_after}, io.BytesIO(json.dumps(status).encode()))

    def test_get_429_respects_retry_after_then_returns_success(self):
        with patch.object(recovery.urllib.request, "urlopen", side_effect=[self.failure(), io.BytesIO(b'{"items":[]}')]) as request, patch.object(recovery.time, "sleep") as sleep:
            self.assertEqual(self.api.request("GET", self.path), {"items": []})
            self.assertEqual(request.call_count, 2)
            sleep.assert_called_once_with(1)

    def test_repeated_get_429_is_bounded_and_diagnostic(self):
        with patch.object(recovery.urllib.request, "urlopen", side_effect=[self.failure(retry_after="100") for _ in range(4)]) as request, patch.object(recovery.time, "sleep") as sleep:
            with self.assertRaises(RuntimeError) as error:
                self.api.request("GET", self.path)
            self.assertEqual(request.call_count, 4)
            self.assertEqual([call.args[0] for call in sleep.call_args_list], [5, 5, 5])
            self.assertIn(self.path, str(error.exception))
            self.assertIn("429", str(error.exception))
            self.assertIn("TooManyRequests", str(error.exception))
            self.assertIn("storage is (re)initializing", str(error.exception))
            self.assertNotIn(self.api.token, str(error.exception))

    def test_retry_delay_uses_status_fallback_and_caps_http_date(self):
        for header, expected in ((None, 1), ("Wed, 31 Dec 2099 23:59:59 GMT", 5)):
            with self.subTest(header=header):
                error = self.failure()
                if header is None:
                    error.headers = {}
                else:
                    error.headers["Retry-After"] = header
                with patch.object(recovery.urllib.request, "urlopen", side_effect=[error, io.BytesIO(b'{"items":[]}')]), patch.object(recovery.time, "sleep") as sleep:
                    self.api.request("GET", self.path)
                    sleep.assert_called_once_with(expected)

    def test_post_429_other_http_and_network_errors_are_never_retried(self):
        for method, error in (("POST", self.failure()), ("PUT", self.failure()), ("DELETE", self.failure()), ("GET", self.failure(403)), ("GET", recovery.urllib.error.URLError("network unavailable"))):
            with self.subTest(method=method, error=type(error).__name__):
                with patch.object(recovery.urllib.request, "urlopen", side_effect=error) as request, patch.object(recovery.time, "sleep") as sleep:
                    with self.assertRaises((RuntimeError, recovery.urllib.error.URLError)):
                        self.api.request(method, self.path)
                    self.assertEqual(request.call_count, 1)
                    sleep.assert_not_called()


class RestoredDataTests(unittest.TestCase):
    def test_reads_real_record_and_rejects_truncated_or_wrong_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "1.dat"
            body = struct.pack(">I", 7) + b"payload" + b"metadata"
            path.write_bytes(b"\x00" * 8 + struct.pack(">IQi", 123, 42, len(body)) + body)
            self.assertEqual(recovery.payload(path, 42, 1, len(body), 123), b"payload")
            with self.assertRaisesRegex(RuntimeError, "identity mismatch"):
                recovery.payload(path, 42, 1, len(body), 999)
            path.write_bytes(path.read_bytes()[:-1])
            with self.assertRaisesRegex(RuntimeError, "Truncated"):
                recovery.payload(path, 42, 1, len(body), 123)

    def test_index_last_record_wins_and_partial_entry_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "1.idx"
            path.write_bytes(struct.pack(">QIiQIi", 42, 1, 11, 42, 0, -1))
            self.assertEqual(recovery.latest_index(path), {42: (0, -1)})
            path.write_bytes(path.read_bytes() + b"x")
            with self.assertRaisesRegex(RuntimeError, "Truncated"):
                recovery.latest_index(path)

    def test_loki_reader_hashes_actual_restored_bytes_and_rejects_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "loki0").mkdir()
            with self.assertRaisesRegex(RuntimeError, "empty"):
                recovery.verify(root)
            (root / "loki0" / "wal").write_bytes(b"stored log record")
            result = recovery.verify(root)
            self.assertEqual(result["bytes"], 17)
            self.assertEqual(result["sha256"], recovery.hashlib.sha256(b"stored log record").hexdigest())

    def test_total_index_budget_checked_before_index_allocation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for label in ("volume0", "volume1", "volume2"):
                (root / label).mkdir()
                with (root / label / "1.idx").open("wb") as stream:
                    stream.truncate(recovery.INDEX_BUDGET // 2)
            with patch.object(recovery, "latest_index") as read_index:
                with self.assertRaisesRegex(RuntimeError, "Total restored index"):
                    recovery.verify(root)
                read_index.assert_not_called()

    def test_legacy_and_structured_chunk_identities(self):
        self.assertEqual(recovery.chunk_identity({"file_id": "12,0000002a0000007b"}), (12, 42, 123))
        self.assertEqual(recovery.chunk_identity({"fid": {"volume_id": 12, "file_key": 42, "cookie": 123}}), (12, 42, 123))

    def test_rehearsal_reads_real_filer_referenced_content_addressed_blob(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            digest = recovery.hashlib.sha256(b"actual Harbor blob").hexdigest()
            harbor_path = "/buckets/harbor/docker/registry/v2/blobs/sha256/" + digest[:2] + "/" + digest + "/data"

            def record(label, vid, key, cookie, data):
                target = root / label
                target.mkdir(exist_ok=True)
                body = struct.pack(">I", len(data)) + data
                (target / (str(vid) + ".idx")).write_bytes(struct.pack(">QIi", key, 1, len(body)))
                (target / (str(vid) + ".dat")).write_bytes(b"\0" * 8 + struct.pack(">IQi", cookie, key, len(body)) + body)

            for label in ("volume0", "volume1"):
                record(label, 1, 42, 123, b"actual Harbor blob")
            for label in ("volume1", "volume2"):
                record(label, 2, 43, 124, b"actual Loki chunk")

            def listing(port, path):
                if path == "/?limit=1":
                    return {}
                if "metadata=true" in path:
                    return {"chunks": [{"file_id": "1,2a0000007b" if "/harbor/" in path else "2,2b0000007c"}]}
                return {"Entries": [{"FullPath": harbor_path if "/harbor/" in path else "/buckets/loki/chunk", "Mode": 0}]}

            with patch.object(recovery, "local_json", side_effect=listing):
                result = recovery.verify(root)
                self.assertEqual(len(result["referenced_samples"]), 4)
                self.assertEqual(result["referenced_samples"]["8888/harbor"]["payload_sha256"], digest)
                self.assertTrue(result["referenced_samples"]["8888/harbor"]["content_addressed_hash_checked"])
                record("volume1", 1, 42, 123, b"corrupted blob")
                with self.assertRaisesRegex(RuntimeError, "divergent payload"):
                    recovery.verify(root)


class CleanupTests(unittest.TestCase):
    def test_uid_replacement_and_foreign_owner_are_never_deleted(self):
        api = object.__new__(recovery.API)
        original = {"metadata": {"name": "restore", "uid": "first", "labels": {recovery.OWNER: recovery.NAME}}}
        replacement = json.loads(json.dumps(original))
        replacement["metadata"]["uid"] = "replacement"
        with patch.object(api, "get", return_value=replacement), patch.object(api, "request") as request:
            with self.assertRaisesRegex(RuntimeError, "UID mismatch"):
                api.delete_owned("storage", "persistentvolumeclaims", original)
            request.assert_not_called()
        original["metadata"]["labels"] = {}
        with patch.object(api, "request") as request:
            with self.assertRaisesRegex(RuntimeError, "ownership mismatch"):
                api.delete_owned("storage", "persistentvolumeclaims", original)
            request.assert_not_called()

    def test_delete_contains_uid_precondition(self):
        api = object.__new__(recovery.API)
        original = {"metadata": {"name": "restore", "uid": "first", "labels": {recovery.OWNER: recovery.NAME}}}
        with patch.object(api, "get", side_effect=[original, None]), patch.object(api, "request") as request:
            api.delete_owned("storage", "persistentvolumeclaims", original)
            self.assertEqual(request.call_args.args[2]["preconditions"], {"uid": "first"})

    def test_reader_cannot_write_sources_or_access_api(self):
        selected = [{"label": label, "clone": label + "-clone"} for label in ("volume0", "volume1", "volume2", "filer0", "filer1")]
        job = recovery.reader_job("test", "generation", selected)
        pod = job["spec"]["template"]["spec"]
        self.assertFalse(pod["automountServiceAccountToken"])
        for volume in pod["volumes"]:
            if "persistentVolumeClaim" in volume:
                self.assertTrue(volume["persistentVolumeClaim"]["readOnly"])
        for container in pod["containers"] + pod["initContainers"]:
            self.assertIn("@sha256:", container["image"])
            self.assertFalse(container["securityContext"]["allowPrivilegeEscalation"])
            for mount in container["volumeMounts"]:
                if mount["mountPath"].startswith("/restore"):
                    self.assertTrue(mount["readOnly"])
        self.assertEqual(pod["initContainers"][2]["restartPolicy"], "Always")
        wait_resources = pod["initContainers"][0]["resources"]
        self.assertEqual(wait_resources["requests"]["cpu"], "10m")
        self.assertEqual(wait_resources["limits"]["cpu"], "100m")


class LifecycleTests(unittest.TestCase):
    class FakeAPI:
        def __init__(self, fail_reader):
            self.fail_reader = fail_reader
            self.objects = {}
            self.created = []
            self.selected = [{"namespace": "observability" if i == 5 else "storage", "label": "source" + str(i), "uid": "source-uid" + str(i), "pv": "pv" + str(i), "pvc": "source" + str(i), "size": "1Gi"} for i in range(6)]
            self.objects[("storage", "leases", recovery.NAME)] = {"metadata": {"name": recovery.NAME}, "spec": {}}
            self.objects[("storage", "configmaps", recovery.NAME + "-journal")] = {"metadata": {"name": recovery.NAME + "-journal"}, "data": {"verified": "good", "previous_verified": "older", "error": "previous run HTTP 429"}}
            for generation in ("good", "older", "failed-candidate"):
                self.objects[("storage", "volumesnapshots", generation)] = {"metadata": {"name": generation, "uid": generation, "labels": {recovery.OWNER: recovery.NAME, recovery.GEN: generation}}}
            self.objects[("storage", "configmaps", recovery.NAME + "-journal")]["data"]["registry"] = json.dumps([{"namespace": "storage", "kind": "volumesnapshots", "name": gen, "uid": gen} for gen in ("good", "older", "failed-candidate")])
            for source in self.selected:
                self.objects[(source["namespace"], "persistentvolumeclaims", source["pvc"])] = {"metadata": {"name": source["pvc"], "uid": source["uid"]}, "spec": {"volumeName": source["pv"]}}

        def path(self, namespace, kind, name=""):
            return namespace + "/" + kind + "/" + name

        def get(self, namespace, kind, name):
            return json.loads(json.dumps(self.objects.get((namespace, kind, name))))

        def list(self, namespace, kind, owned=False):
            return [obj for (ns, k, _), obj in self.objects.items() if ns == namespace and k == kind and (not owned or obj.get("metadata", {}).get("labels", {}).get(recovery.OWNER) == recovery.NAME)]

        def create(self, namespace, kind, body):
            body = json.loads(json.dumps(body))
            self.created.append(body)
            name = body["metadata"]["name"]
            body["metadata"]["uid"] = name
            if kind == "volumesnapshots":
                body["status"] = {"readyToUse": True, "boundVolumeSnapshotContentName": name}
            elif kind == "persistentvolumeclaims":
                body["status"] = {"phase": "Bound"}
                body["spec"]["volumeName"] = name + "-pv"
            elif kind == "jobs":
                body["status"] = {"conditions": [{"type": "Failed" if self.fail_reader else "Complete", "status": "True"}]}
                self.objects[(namespace, "pods", name)] = {"metadata": {"ownerReferences": [{"uid": name}]}, "status": {"containerStatuses": [{"name": "reader", "state": {"terminated": {"exitCode": 0, "message": '{"coverage":"fixture"}'}}}]}}
            self.objects[(namespace, kind, name)] = body
            return body

        def delete_owned(self, namespace, kind, obj):
            del self.objects[(namespace, kind, obj["metadata"]["name"])]

        def request(self, method, path, data=None):
            if method == "PUT":
                namespace, kind, name = path.split("/")
                self.objects[(namespace, kind, name)] = json.loads(json.dumps(data))
                return json.loads(json.dumps(data))
            if path.endswith("/volumes"):
                return {"items": [{"metadata": {"name": source["pv"]}, "status": {"robustness": "healthy"}} for source in self.selected]}
            if path.endswith("/nodes"):
                return {"items": [{"metadata": {"name": name}, "spec": {"allowScheduling": True, "disks": {"disk": {"allowScheduling": True, "storageReserved": 0}}}, "status": {"conditions": [{"type": "Ready", "status": "True"}], "diskStatus": {"disk": {"storageAvailable": 100 * 2**30, "conditions": [{"type": "Ready", "status": "True"}]}}}} for name in ("node1", "node2")]}
            if "/volumes/" in path:
                return {"status": {"robustness": "healthy", "state": "attached"}}
            if "/volumesnapshotcontents/" in path:
                name = path.rsplit("/", 1)[-1]
                source = next(s for s in self.selected if name.endswith("-" + s["label"]))
                return {"spec": {"source": {"volumeHandle": source["pv"]}, "volumeSnapshotRef": {"uid": name}}}
            if "/persistentvolumes/" in path:
                pv = path.rsplit("/", 1)[-1]
                source = next(source for source in self.selected if source["pv"] == pv)
                return {"spec": {"csi": {"volumeHandle": pv}, "claimRef": {"uid": source["uid"]}}}
            raise AssertionError((method, path))

    def run_lifecycle(self, fail_reader):
        api = self.FakeAPI(fail_reader)
        with patch.object(recovery, "API", return_value=api), patch.object(recovery, "sources", return_value=api.selected), patch("builtins.print"):
            if fail_reader:
                with self.assertRaisesRegex(RuntimeError, "verifier failed"):
                    recovery.coordinate()
            else:
                recovery.coordinate()
        journal = api.get("storage", "configmaps", recovery.NAME + "-journal")["data"]
        snapshots = [obj for (ns, kind, name), obj in api.objects.items() if kind == "volumesnapshots"]
        generations = {obj["metadata"]["labels"][recovery.GEN] for obj in snapshots}
        self.assertIn("good", generations)
        self.assertEqual(len(generations), 2)
        self.assertFalse(api.get("storage", "leases", recovery.NAME)["spec"]["holderIdentity"])
        self.assertFalse(any(kind in ("jobs", "networkpolicies") for ns, kind, name in api.objects))
        self.assertEqual(len([1 for ns, kind, name in api.objects if kind == "persistentvolumeclaims"]), 6)
        return journal

    def test_success_retains_two_generations_and_removes_only_temporaries(self):
        journal = self.run_lifecycle(False)
        self.assertEqual(journal["phase"], "complete")
        self.assertNotEqual(journal["verified"], "good")
        self.assertIn("verified_report", journal)
        self.assertEqual(journal["error"], "")

    def test_failure_preserves_both_verified_generations(self):
        journal = self.run_lifecycle(True)
        self.assertEqual(journal["phase"], "failed")
        self.assertEqual(journal["verified"], "good")
        self.assertEqual(journal["previous_verified"], "older")

    def test_journal_write_failure_still_cleans_created_uid_and_releases_lease(self):
        api = self.FakeAPI(False)
        original = api.request
        def fail_journal(method, path, data=None):
            if method == "PUT" and path.endswith("/" + recovery.NAME + "-journal") and any(name.startswith("recovery-") for ns, kind, name in api.objects):
                raise RuntimeError("injected journal failure")
            return original(method, path, data)
        with patch.object(recovery, "API", return_value=api), patch.object(recovery, "sources", return_value=api.selected), patch.object(api, "request", side_effect=fail_journal), patch("builtins.print"):
            with self.assertRaisesRegex(RuntimeError, "injected journal failure"):
                recovery.coordinate()
        self.assertFalse(any(name.startswith("recovery-") for ns, kind, name in api.objects))
        self.assertFalse(api.get("storage", "leases", recovery.NAME)["spec"]["holderIdentity"])

    def test_copied_owner_labels_without_registered_uid_fail_closed(self):
        api = self.FakeAPI(False)
        api.objects[("storage", "persistentvolumeclaims", "foreign")] = {"metadata": {"name": "foreign", "uid": "not-registered", "labels": {recovery.OWNER: recovery.NAME, recovery.GEN: "copied"}}}
        with patch.object(recovery, "API", return_value=api), patch("builtins.print"):
            with self.assertRaisesRegex(RuntimeError, "Unknown owned resource UID"):
                recovery.coordinate()
        self.assertIsNotNone(api.get("storage", "persistentvolumeclaims", "foreign"))

    def test_failed_verification_publication_retains_both_previous_checkpoints(self):
        api = self.FakeAPI(False)
        original = api.request
        def fail_publication(method, path, data=None):
            if method == "PUT" and path.endswith("/" + recovery.NAME + "-journal") and data.get("data", {}).get("phase") == "verified":
                raise RuntimeError("injected publication failure")
            return original(method, path, data)
        with patch.object(recovery, "API", return_value=api), patch.object(recovery, "sources", return_value=api.selected), patch.object(api, "request", side_effect=fail_publication), patch("builtins.print"):
            with self.assertRaisesRegex(RuntimeError, "publication failure"):
                recovery.coordinate()
        journal = api.get("storage", "configmaps", recovery.NAME + "-journal")["data"]
        self.assertEqual(journal["verified"], "good")
        self.assertEqual(journal["previous_verified"], "older")
        self.assertEqual({obj["metadata"]["labels"][recovery.GEN] for ns, kind, name in api.objects if kind == "volumesnapshots" for obj in [api.objects[(ns, kind, name)]]}, {"good", "older"})

    def test_offline_unschedulable_or_reserved_capacity_does_not_count(self):
        api = self.FakeAPI(False)
        nodes = api.request("GET", "/nodes")["items"]
        recovery.capacity_gate(nodes, api.selected)
        nodes[1]["spec"]["allowScheduling"] = False
        with self.assertRaisesRegex(RuntimeError, "Two Ready"):
            recovery.capacity_gate(nodes, api.selected)
        nodes[1]["spec"]["allowScheduling"] = True
        nodes[1]["spec"]["disks"]["disk"]["storageReserved"] = 99 * 2**30
        with self.assertRaisesRegex(RuntimeError, "Two Ready"):
            recovery.capacity_gate(nodes, api.selected)

    def test_generation_code_is_immutable_startup_capture_without_late_file_read(self):
        api = self.FakeAPI(False)
        with patch.object(recovery, "API", return_value=api), patch.object(recovery, "sources", return_value=api.selected), patch.object(recovery, "Path", side_effect=AssertionError("Code file re-read during run")), patch("builtins.print"):
            recovery.coordinate()
        configs = [obj for obj in api.created if obj["kind"] == "ConfigMap" and "run.py" in obj.get("data", {})]
        self.assertEqual(len(configs), 2)
        for obj in configs:
            self.assertTrue(obj["immutable"])
            self.assertEqual(obj["data"]["run.py"], recovery.SCRIPT_SOURCE)


if __name__ == "__main__":
    unittest.main()
