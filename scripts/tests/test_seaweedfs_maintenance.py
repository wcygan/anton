"""Offline tests for the read-only SeaweedFS maintenance audit."""

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "seaweedfs-maintenance"
SPEC = importlib.util.spec_from_file_location(
    "seaweed_maintenance", ROOT / "scripts/verify-seaweedfs-maintenance.py"
)
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)
CONTEXT = "tailscale-operator.synthetic.ts.net"


def placement(code):
    fields = ("dc", "rack", "node")
    return {field: int(digit) for field, digit in zip(fields, code) if digit != "0"}


def evidence(*, copies=("seaweedfs-volume-0",), replication="000", slot_used=1):
    urls = [f"{name}.seaweedfs-volume-peer.storage:8444" for name in copies]
    nodes = [f"node-{index}" for index in range(len(urls))]
    server_volumes, data_nodes, pods, pvc_items, node_items = {}, [], [], [], []
    for index, (pod_name, url, node_name) in enumerate(zip(copies, urls, nodes)):
        server_volumes[url] = [{
            "Id": 9, "Size": 1024, "Collection": "harbor",
            "ReplicaPlacement": placement(replication),
        }]
        data_nodes.append({"Url": url, "Volumes": slot_used, "Max": 20})
        pods.append({
            "metadata": {"name": pod_name, "namespace": "storage",
                         "ownerReferences": [{"uid": "sts-uid"}]},
            "spec": {"nodeName": node_name,
                     "volumes": [{"name": "data", "persistentVolumeClaim": {"claimName": f"mount0-{pod_name}"}}]},
            "status": {"podIP": f"10.0.0.{index + 1}",
                       "conditions": [{"type": "Ready", "status": "True"}]},
        })
        pvc_items.append({"metadata": {"name": f"mount0-{pod_name}", "namespace": "storage"},
                          "status": {"phase": "Bound", "capacity": {"storage": "120Gi"}}})
        node_items.append({"metadata": {"name": node_name},
                           "status": {"conditions": [{"type": "Ready", "status": "True"}]}})
    return {
        "context": CONTEXT,
        "expected_context": CONTEXT,
        "kube_system": {"metadata": {"uid": "kube-uid"}},
        "expected_kube_system_uid": "kube-uid",
        "seaweed": {"metadata": {"uid": "seaweed-uid", "namespace": "storage"}, "status": {"conditions": []}},
        "expected_seaweed_uid": "seaweed-uid",
        "statefulset": {"metadata": {"uid": "sts-uid", "namespace": "storage",
                                        "ownerReferences": [{"uid": "seaweed-uid"}]}},
        "pods_response": {"items": pods},
        "nodes_response": {"items": node_items},
        "pvcs_response": {"items": pvc_items},
        "dir_status": {"Topology": {
            "Max": len(urls) * 20, "Free": len(urls) * 20 - len(urls) * slot_used,
            "DataCenters": [{"Id": "dc", "Racks": [{"Id": "rack", "DataNodes": data_nodes}]}],
            "Layouts": [{"collection": "harbor", "replication": replication, "writables": [9]}],
        }},
        "vol_status": {"Volumes": {"DataCenters": {"dc": {"rack": server_volumes}}}},
    }


def audit(**changes):
    values = evidence()
    values.update(changes)
    return AUDIT.analyze(**values)


class SeaweedMaintenanceAudit(unittest.TestCase):
    def test_native_replica_placement_fields_decode_xyz_order(self):
        self.assertEqual(AUDIT.parse_replica_placement({}), "000")
        self.assertEqual(AUDIT.parse_replica_placement({"node": 1}), "001")
        self.assertEqual(AUDIT.parse_replica_placement({"rack": 2, "node": 3}), "023")
        self.assertEqual(AUDIT.parse_replica_placement({"dc": 1, "rack": 2, "node": 3}), "123")

    def test_native_replica_placement_rejects_malformed_or_unknown_fields(self):
        for placement in (
            None,
            {"node": True},
            {"node": "1"},
            {"node": -1},
            {"node": 10},
            {"unknown": 1},
            {"DiffDataCenterCount": 1},
        ):
            with self.subTest(placement=placement):
                with self.assertRaises(AUDIT.AuditError):
                    AUDIT.parse_replica_placement(placement)

    def test_actual_448_master_vol_status_two_copy_001_passes_full_audit(self):
        values = evidence(copies=("seaweedfs-volume-0", "seaweedfs-volume-1"), replication="001")
        values["vol_status"] = json.loads(
            (FIXTURES / "master-vol-status-4.48.json").read_text()
        )
        values["dir_status"]["Topology"]["Layouts"] = [
            {"collection": "harbor", "replication": "001", "writables": [52]}
        ]

        result = AUDIT.analyze(**values)

        volume = result["volumes"][0]
        self.assertEqual(volume["id"], 52)
        self.assertEqual(volume["currentReplication"], "001")
        self.assertEqual(volume["copyCount"], 2)
        self.assertEqual(volume["distinctReadyNodeCount"], 2)
        self.assertTrue(volume["hasCopiesSurvivingAnyOneNode"])
        self.assertTrue(result["auditPass"])

    def test_existing_zero_replication_copy_fails(self):
        result = audit()
        self.assertEqual(result["volumes"][0]["currentReplication"], "000")
        self.assertEqual(result["volumes"][0]["copyCount"], 1)
        self.assertFalse(result["hasCopiesSurvivingAnyOneNode"])
        self.assertFalse(result["auditPass"])
        self.assertIn("writesAvailability", result)
        self.assertIn("not_assessed", result["bytesAndCacheBehavior"])
        self.assertIn("observationStartedAtUTC", result)
        self.assertIn("observationCompletedAtUTC", result)

    def test_two_native_001_copies_on_distinct_ready_nodes_pass(self):
        result = audit(**evidence(copies=("seaweedfs-volume-0", "seaweedfs-volume-1"), replication="001"))
        volume = result["volumes"][0]
        self.assertEqual(volume["copyCount"], 2)
        self.assertEqual(volume["distinctReadyNodeCount"], 2)
        self.assertTrue(volume["hasCopiesSurvivingAnyOneNode"])
        self.assertTrue(result["auditPass"])

    def test_readonly_001_volume_without_writable_layout_still_passes_placement_check(self):
        values = evidence(copies=("seaweedfs-volume-0", "seaweedfs-volume-1"), replication="001")
        values["dir_status"]["Topology"]["Layouts"][0]["writables"] = []
        values["vol_status"]["Volumes"]["DataCenters"]["dc"]["rack"][
            "seaweedfs-volume-0.seaweedfs-volume-peer.storage:8444"][0]["ReadOnly"] = True
        values["vol_status"]["Volumes"]["DataCenters"]["dc"]["rack"][
            "seaweedfs-volume-1.seaweedfs-volume-peer.storage:8444"][0]["ReadOnly"] = True
        result = AUDIT.analyze(**values)
        self.assertFalse(result["volumes"][0]["writableLayoutPresent"])
        self.assertEqual(result["volumes"][0]["currentReplication"], "001")
        self.assertTrue(result["auditPass"])

    def test_mixed_per_copy_native_placements_fail_consensus(self):
        values = evidence(copies=("seaweedfs-volume-0", "seaweedfs-volume-1"), replication="001")
        second = values["vol_status"]["Volumes"]["DataCenters"]["dc"]["rack"][
            "seaweedfs-volume-1.seaweedfs-volume-peer.storage:8444"][0]
        second["ReplicaPlacement"] = placement("000")
        result = AUDIT.analyze(**values)
        self.assertFalse(result["volumes"][0]["copyPlacementsAgree"])
        self.assertIsNone(result["volumes"][0]["currentReplication"])
        self.assertFalse(result["auditPass"])

    def test_copy_missing_from_active_master_topology_is_not_counted(self):
        values = evidence(copies=("seaweedfs-volume-0", "seaweedfs-volume-1"), replication="001")
        data_nodes = values["dir_status"]["Topology"]["DataCenters"][0]["Racks"][0]["DataNodes"]
        data_nodes.pop()
        result = AUDIT.analyze(**values)
        volume = result["volumes"][0]
        self.assertEqual(volume["observedCopyCount"], 2)
        self.assertEqual(volume["copyCount"], 1)
        self.assertEqual(volume["distinctReadyNodeCount"], 1)
        self.assertIn("seaweedfs-volume-1.seaweedfs-volume-peer.storage:8444", result["unmappedVolumeServers"])
        self.assertFalse(volume["hasCopiesSurvivingAnyOneNode"])
        self.assertFalse(result["auditPass"])

    def test_copies_with_different_reported_sizes_fail_placement_acceptance(self):
        values = evidence(copies=("seaweedfs-volume-0", "seaweedfs-volume-1"), replication="001")
        second = values["vol_status"]["Volumes"]["DataCenters"]["dc"]["rack"][
            "seaweedfs-volume-1.seaweedfs-volume-peer.storage:8444"][0]
        second["Size"] = 2048
        result = AUDIT.analyze(**values)
        volume = result["volumes"][0]
        self.assertTrue(volume["copyPlacementsAgree"])
        self.assertEqual(volume["distinctReadyNodeCount"], 2)
        self.assertFalse(volume["copySizesAgree"])
        self.assertFalse(volume["hasCopiesSurvivingAnyOneNode"])
        self.assertFalse(result["auditPass"])
        self.assertIn("replica copies report different volume sizes", result["issues"])
        self.assertIn("not_assessed", result["bytesAndCacheBehavior"])

    def diverged(self):
        values = evidence(copies=("seaweedfs-volume-0", "seaweedfs-volume-1"), replication="001")
        values["vol_status"]["Volumes"]["DataCenters"]["dc"]["rack"][
            "seaweedfs-volume-1.seaweedfs-volume-peer.storage:8444"][0]["Size"] = 2048
        values["observation_started_at"] = "2026-10-23T23:40:00.000000Z"
        return values

    def verified(self, **changes):
        document = {
            "volume_id": 9, "pass": True, "observed_at": "2026-10-23T23:33:13Z",
            "copies": [f"seaweedfs-volume-{i}.seaweedfs-volume-peer.storage:8444" for i in (1, 0)],
        }
        document.update(changes)
        return document

    def test_size_divergence_with_fresh_verify_evidence_is_accepted(self):
        result = AUDIT.analyze(**self.diverged(), accepted_divergence={9: self.verified()})
        volume = result["volumes"][0]
        self.assertFalse(volume["copySizesAgree"], "the sizes still differ; only the verdict changes")
        self.assertTrue(volume["copySizeDivergenceAccepted"])
        self.assertTrue(volume["hasCopiesSurvivingAnyOneNode"])
        self.assertTrue(result["auditPass"], result["issues"])
        self.assertEqual([9], result["acceptedSizeDivergenceIDs"])
        self.assertEqual([], result["issues"])

    def test_size_divergence_without_valid_verify_evidence_still_fails(self):
        cases = {
            "missing": (None, "no verify.json"),
            "failed": (self.verified(**{"pass": False}), "did not pass"),
            "stale": (self.verified(observed_at="2026-10-23T17:00:00Z"), "older than 6 hours"),
            "future": (self.verified(observed_at="2026-10-24T00:00:00Z"), "older than 6 hours"),
            "other copies": (self.verified(copies=["seaweedfs-volume-2.seaweedfs-volume-peer.storage:8444"]), "other copies"),
            "other volume": (self.verified(volume_id=10), "did not pass"),
        }
        for name, (document, reason) in cases.items():
            with self.subTest(name):
                result = AUDIT.analyze(**self.diverged(), accepted_divergence={9: document})
                self.assertFalse(result["volumes"][0]["hasCopiesSurvivingAnyOneNode"])
                self.assertFalse(result["auditPass"])
                self.assertIn("replica copies report different volume sizes", result["issues"])
                self.assertTrue(any(issue.startswith("size divergence not accepted for volume 9") and reason in issue
                                    for issue in result["issues"]), result["issues"])

    def test_size_only_divergence_is_not_reported_as_a_placement_failure(self):
        result = AUDIT.analyze(**self.diverged())
        self.assertNotIn("selected volumes lack observed nonzero two-node replica placement", result["issues"])
        self.assertIn("replica copies report different volume sizes", result["issues"])

    def test_live_cli_reads_verify_evidence_for_named_volumes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "volume-9").mkdir()
            (root / "volume-9" / "verify.json").write_text(json.dumps(self.verified()))
            (root / "volume-10").mkdir()
            (root / "volume-10" / "verify.json").write_text("not json")
            self.assertEqual(self.verified(), AUDIT.load_verify(root, 9))
            self.assertIsNone(AUDIT.load_verify(root, 10))
            self.assertIsNone(AUDIT.load_verify(root, 11))
        self.assertEqual([12, 25], AUDIT.volume_ids("12,25"))
        for bad in ("", "x", "0"):
            with self.assertRaises(argparse.ArgumentTypeError):
                AUDIT.volume_ids(bad)

    def test_duplicate_file_with_000_placement_does_not_pass(self):
        result = audit(**evidence(copies=("seaweedfs-volume-0", "seaweedfs-volume-1"), replication="000"))
        self.assertEqual(result["volumes"][0]["copyCount"], 2)
        self.assertFalse(result["auditPass"])

    def test_two_server_addresses_on_same_node_are_one_node_copy(self):
        values = evidence(copies=("seaweedfs-volume-0", "seaweedfs-volume-1"), replication="001")
        values["pods_response"]["items"][1]["spec"]["nodeName"] = "node-0"
        result = AUDIT.analyze(**values)
        self.assertEqual(result["volumes"][0]["distinctNodeCount"], 1)
        self.assertFalse(result["auditPass"])

    def test_terminating_pod_or_node_is_not_a_ready_copy(self):
        for target in ("pod", "node"):
            with self.subTest(target=target):
                values = evidence(copies=("seaweedfs-volume-0", "seaweedfs-volume-1"), replication="001")
                obj = values["pods_response"]["items"][1] if target == "pod" else values["nodes_response"]["items"][1]
                obj["metadata"]["deletionTimestamp"] = "2026-10-19T00:00:00Z"
                result = AUDIT.analyze(**values)
                self.assertFalse(result["volumes"][0]["hasCopiesSurvivingAnyOneNode"])
                self.assertFalse(result["auditPass"])

    def test_missing_physical_copy_owner_or_pvc_mapping_fails(self):
        self.assertFalse(audit(**evidence(replication="001"))["auditPass"])
        values = evidence(copies=("seaweedfs-volume-0", "seaweedfs-volume-1"), replication="001")
        values["pods_response"]["items"][1]["metadata"]["ownerReferences"][0]["uid"] = "wrong-sts"
        result = AUDIT.analyze(**values)
        self.assertIn("seaweedfs-volume-1.seaweedfs-volume-peer.storage:8444", result["unmappedOwners"])
        self.assertFalse(result["auditPass"])
        values = evidence(copies=("seaweedfs-volume-0", "seaweedfs-volume-1"), replication="001")
        values["pods_response"]["items"][1]["spec"]["volumes"] = []
        self.assertFalse(AUDIT.analyze(**values)["auditPass"])
        values = evidence(copies=("seaweedfs-volume-0", "seaweedfs-volume-1"), replication="001")
        values["pvcs_response"]["items"][1]["metadata"]["namespace"] = "other"
        self.assertFalse(AUDIT.analyze(**values)["auditPass"])

    def test_foreign_alias_and_wrong_namespace_pod_are_unmapped(self):
        for mapping in ("foreign.example.internal", "seaweedfs-volume-0.seaweedfs-volume-peer.other:8444"):
            with self.subTest(mapping=mapping):
                values = evidence(copies=("seaweedfs-volume-0", "seaweedfs-volume-1"), replication="001")
                status = values["vol_status"]["Volumes"]["DataCenters"]["dc"]["rack"]
                first = status.pop("seaweedfs-volume-0.seaweedfs-volume-peer.storage:8444")
                status[f"{mapping}:8444" if ":" not in mapping else mapping] = first
                result = AUDIT.analyze(**values)
                self.assertTrue(result["unmappedVolumeServers"])
                self.assertFalse(result["auditPass"])
        values = evidence(copies=("seaweedfs-volume-0", "seaweedfs-volume-1"), replication="001")
        values["pods_response"]["items"][1]["metadata"]["namespace"] = "other"
        self.assertFalse(AUDIT.analyze(**values)["auditPass"])

    def test_context_and_cluster_uid_mismatches_fail(self):
        values = evidence(copies=("seaweedfs-volume-0", "seaweedfs-volume-1"), replication="001")
        values["expected_context"] = "tailscale-operator.other.ts.net"
        values["expected_kube_system_uid"] = "other-kube"
        values["expected_seaweed_uid"] = "other-seaweed"
        result = AUDIT.analyze(**values)
        self.assertFalse(result["identity"]["exactContextMatch"])
        self.assertFalse(result["identity"]["kubeSystemUIDMatch"])
        self.assertFalse(result["identity"]["seaweedUIDMatch"])
        self.assertNotIn("synthetic.ts.net", str(AUDIT.redact_tailnet(result)))
        self.assertFalse(result["auditPass"])

    def test_slot_exhaustion_is_reported_separately_from_reported_bytes(self):
        result = audit(**evidence(copies=("seaweedfs-volume-0", "seaweedfs-volume-1"), replication="001", slot_used=20))
        self.assertEqual([row["free"] for row in result["topology"]["servers"]], [0, 0])
        self.assertEqual(result["collections"]["harbor"]["reportedVolumeBytes"], 1024)
        self.assertTrue(result["auditPass"])

    def test_malformed_master_api_response_fails_closed(self):
        values = evidence()
        values["vol_status"] = {"Volumes": []}
        with self.assertRaises(AUDIT.AuditError):
            AUDIT.analyze(**values)

    def test_live_cli_pins_every_resource_request_and_bounds_timeouts(self):
        values = evidence()
        responses = {
            "current-context": CONTEXT,
            "namespace": values["kube_system"],
            "seaweed": values["seaweed"],
            "statefulset": values["statefulset"],
            "pods": values["pods_response"],
            "nodes": values["nodes_response"],
            "pvc": values["pvcs_response"],
            "dir/status": values["dir_status"],
            "vol/status": values["vol_status"],
        }
        calls = []

        def fake_run(command, **kwargs):
            calls.append((command, kwargs))
            joined = " ".join(command)
            if " config current-context" in joined:
                response = responses["current-context"]
            elif "/dir/status" in joined:
                response = responses["dir/status"]
            elif "/vol/status" in joined:
                response = responses["vol/status"]
            else:
                response = next(
                (value for key, value in responses.items() if key != "current-context" and key in joined), {}
                )
            stdout = response if isinstance(response, str) else json.dumps(response)
            return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

        args = argparse.Namespace(expected_context=CONTEXT, expected_kube_system_uid="kube-uid",
                                  expected_seaweed_uid="seaweed-uid", collection=None,
                                  accept_size_divergence=[], repair_evidence=Path("/nonexistent"))
        with patch.object(AUDIT.subprocess, "run", side_effect=fake_run):
            AUDIT.run_live(args)
        self.assertEqual(len(calls), 9)
        self.assertTrue(all(call[1]["timeout"] <= AUDIT.TOTAL_TIMEOUT for call in calls))
        for command, _kwargs in calls[1:]:
            self.assertIn(f"--context={CONTEXT}", command)
            self.assertIn("--request-timeout=10s", command)
        self.assertIn("--request-timeout=10s", calls[0][0])

    def test_live_cli_rejects_unexpected_current_context_before_api_reads(self):
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="admin@wrong", stderr="")

        args = argparse.Namespace(expected_context=CONTEXT, expected_kube_system_uid="kube-uid",
                                  expected_seaweed_uid="seaweed-uid", collection=None,
                                  accept_size_divergence=[], repair_evidence=Path("/nonexistent"))
        with patch.object(AUDIT.subprocess, "run", side_effect=fake_run):
            with self.assertRaises(AUDIT.AuditError):
                AUDIT.run_live(args)
        self.assertEqual(len(calls), 1)
        self.assertNotIn("--context=", calls[0])
        self.assertIn("--request-timeout=10s", calls[0])


if __name__ == "__main__":
    unittest.main()
