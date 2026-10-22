"""Fail closed on foreign snapshots, unhealthy replicas and partial upgrades."""
import argparse
import copy
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "upgrade-longhorn-engines.py"
spec = importlib.util.spec_from_file_location("engine_upgrade", SOURCE)
upgrade = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upgrade)
OLD = "longhornio/longhorn-engine:v1.12.1"
NEW = "longhornio/longhorn-engine:v1.13.0"


def state():
    now = datetime.now(timezone.utc).isoformat()
    volume = {"metadata": {"name": "volume", "uid": "volume-uid", "resourceVersion": "7"},
              "spec": {"image": OLD, "dataEngine": "v1", "numberOfReplicas": 2},
              "status": {"currentImage": OLD, "robustness": "healthy", "state": "attached", "currentNodeID": "node1"}}
    engine = {"metadata": {"name": "engine"}, "spec": {"volumeName": "volume"},
              "status": {"currentImage": OLD, "currentState": "running", "replicaModeMap": {"r1": "RW", "r2": "RW"}}}
    replicas = [{"metadata": {"name": "r" + str(i)},
                 "spec": {"volumeName": "volume", "nodeID": "node" + str(i), "active": True, "healthyAt": now},
                 "status": {"currentState": "running", "currentImage": OLD}} for i in (1, 2)]
    return {"volumes": [volume], "engines": [engine], "replicas": replicas,
            "nodes": [{"metadata": {"name": "node" + str(i)}, "status": {"conditions": [{"type": "Ready", "status": "True"}]}} for i in (1, 2)],
            "images": [{"spec": {"image": image}, "status": {"state": "deployed", "nodeDeploymentMap": {"node1": True, "node2": True}}} for image in (OLD, NEW)],
            "settings": [{"metadata": {"name": "default-engine-image"}, "value": NEW},
                         {"metadata": {"name": "concurrent-automatic-engine-upgrade-per-node-limit"}, "value": "0"}],
            "pvs": [{"metadata": {"name": "pv"}, "spec": {"csi": {"driver": "driver.longhorn.io", "volumeHandle": "volume"},
                     "claimRef": {"name": "data", "namespace": "storage", "uid": "pvc-uid"}}}],
            "pvcs": [{"metadata": {"name": "data", "namespace": "storage", "uid": "pvc-uid"},
                      "spec": {"volumeName": "pv"}, "status": {"phase": "Bound"}}],
            "snapshots": [{"metadata": {"name": "pre-volume", "namespace": "storage", "uid": "snap-uid", "creationTimestamp": now,
                           "annotations": {upgrade.ANNOTATION + "source-volume-uid": "volume-uid", upgrade.ANNOTATION + "source-pvc-uid": "pvc-uid"}},
                           "spec": {"volumeSnapshotClassName": "longhorn-wal-forensics", "source": {"persistentVolumeClaimName": "data"}},
                           "status": {"readyToUse": True, "creationTime": now, "boundVolumeSnapshotContentName": "content"}}],
            "contents": [{"metadata": {"name": "content"},
                          "spec": {"driver": "driver.longhorn.io", "deletionPolicy": "Retain", "source": {"volumeHandle": "volume"},
                                   "volumeSnapshotRef": {"name": "pre-volume", "namespace": "storage", "uid": "snap-uid"}},
                          "status": {"readyToUse": True}}]}


def args(execute=False):
    return argparse.Namespace(target="1.13.0", snapshot_prefix="pre-", snapshot_max_age_hours=24,
                              expected_volume_count=1, timeout_seconds=1, execute=execute)


def two_volume_state():
    result = state()
    other = state()
    replacements = {"volume": "volume2", "volume-uid": "volume2-uid", "engine": "engine2",
                    "r1": "r3", "r2": "r4", "pv": "pv2", "data": "data2", "pvc-uid": "pvc2-uid",
                    "pre-volume": "pre-volume2", "snap-uid": "snap2-uid", "content": "content2"}

    def replace(value):
        if isinstance(value, str):
            return replacements.get(value, value)
        if isinstance(value, list):
            return [replace(item) for item in value]
        if isinstance(value, dict):
            return {replacements.get(key, key): replace(item) for key, item in value.items()}
        return value

    other = replace(other)
    for key in ("volumes", "engines", "replicas", "pvs", "pvcs", "snapshots", "contents"):
        result[key] += other[key]
    return result


class FakeCluster:
    def __init__(self, converge=True):
        self.value = state()
        self.mutations = []
        self.converge = converge

    def state(self):
        return copy.deepcopy(self.value)

    def guard(self):
        pass

    def command(self, *command):
        self.mutations.append(command)
        target = json.loads(command[command.index("-p") + 1])[-1]["value"]
        self.value["volumes"][0]["spec"]["image"] = target
        if self.converge:
            for kind in ("volumes", "engines", "replicas"):
                for obj in self.value[kind]:
                    obj["status"]["currentImage"] = target
        return self.value["volumes"][0]


class UpgradeTests(unittest.TestCase):
    def test_null_replica_map_waits_until_two_rw_replicas_are_observed(self):
        class NullMapCluster(FakeCluster):
            def __init__(self):
                super().__init__()
                self.pending_reads = None
                self.null_observed = False

            def command(self, *command):
                result = super().command(*command)
                self.value["engines"][0]["status"]["replicaModeMap"] = None
                self.pending_reads = 0
                return result

            def state(self):
                if self.pending_reads is not None:
                    self.pending_reads += 1
                    if self.pending_reads == 1:
                        self.null_observed = True
                    else:
                        self.value["engines"][0]["status"]["replicaModeMap"] = {"r1": "RW", "r2": "RW"}
                return super().state()

        initial = state()
        initial["engines"][0]["status"]["replicaModeMap"] = None
        with self.assertRaisesRegex(RuntimeError, "two RW replicas"):
            upgrade.healthy(initial["volumes"][0], initial["engines"], initial["replicas"])
        cluster = NullMapCluster()
        with patch.object(upgrade.time, "sleep") as wait:
            upgrade.execute(cluster, args(True))
        self.assertTrue(cluster.null_observed)
        wait.assert_called_once()
        self.assertEqual(len(cluster.mutations), 1)
        self.assertEqual(cluster.value["engines"][0]["status"]["replicaModeMap"], {"r1": "RW", "r2": "RW"})

    def test_two_volumes_never_patch_second_before_first_engine_and_replicas_converge(self):
        class SerialCluster(FakeCluster):
            def __init__(self):
                super().__init__()
                self.value = two_volume_state()
                self.pending = None
                self.pending_reads = 0
                self.first_verified_before_second = False

            def state(self):
                if self.pending is not None:
                    self.pending_reads += 1
                    if self.pending_reads >= 2:
                        for key in ("volumes", "engines", "replicas"):
                            for item in self.value[key]:
                                if (item["metadata"].get("name") == self.pending
                                        or item.get("spec", {}).get("volumeName") == self.pending):
                                    item["status"]["currentImage"] = NEW
                        self.pending = None
                return super().state()

            def command(self, *command):
                name = command[4]
                if name == "volume2":
                    upgrade.healthy(self.value["volumes"][0], self.value["engines"], self.value["replicas"], NEW)
                    self.first_verified_before_second = True
                self.mutations.append(command)
                volume = next(v for v in self.value["volumes"] if v["metadata"]["name"] == name)
                volume["spec"]["image"] = NEW
                self.pending, self.pending_reads = name, 0
                return volume

        cluster = SerialCluster()
        config = args(True)
        config.expected_volume_count = 2
        with patch.object(upgrade.time, "sleep"):
            upgrade.execute(cluster, config)
        self.assertEqual([command[4] for command in cluster.mutations], ["volume", "volume2"])
        self.assertTrue(cluster.first_verified_before_second)

    def test_other_volume_degradation_stops_before_second_patch(self):
        class DegradingCluster(FakeCluster):
            def __init__(self):
                super().__init__()
                self.value = two_volume_state()

            def command(self, *command):
                result = super().command(*command)
                self.value["volumes"][1]["status"]["robustness"] = "degraded"
                return result

        cluster = DegradingCluster()
        config = args(True)
        config.expected_volume_count = 2
        with self.assertRaisesRegex(RuntimeError, "volume2: volume is not attached and healthy"):
            upgrade.execute(cluster, config)
        self.assertEqual([command[4] for command in cluster.mutations], ["volume"])

    def test_read_only_default_plans_without_mutation(self):
        cluster = FakeCluster()
        upgrade.execute(cluster, args())
        self.assertEqual(cluster.mutations, [])

    def test_execute_applies_one_uid_and_old_image_guarded_patch_then_is_idempotent(self):
        cluster = FakeCluster()
        upgrade.execute(cluster, args(True))
        self.assertEqual(len(cluster.mutations), 1)
        import json
        command = cluster.mutations[0]
        changes = json.loads(command[command.index("-p") + 1])
        self.assertEqual(changes, [{"op": "test", "path": "/metadata/uid", "value": "volume-uid"},
                                   {"op": "test", "path": "/metadata/resourceVersion", "value": "7"},
                                   {"op": "test", "path": "/spec/image", "value": OLD},
                                   {"op": "replace", "path": "/spec/image", "value": NEW}])
        upgrade.execute(cluster, args(True))
        self.assertEqual(len(cluster.mutations), 1)

    def test_timeout_stops_after_one_patch_without_retry(self):
        cluster = FakeCluster(converge=False)
        with patch.object(upgrade.time, "monotonic", side_effect=[0, 2]):
            with self.assertRaisesRegex(RuntimeError, "convergence timeout"):
                upgrade.execute(cluster, args(True))
        self.assertEqual(len(cluster.mutations), 1)

    def test_foreign_stale_unbound_or_failed_snapshots_stop_before_patch(self):
        mutations = [lambda s: s["snapshots"][0]["metadata"]["annotations"].update({upgrade.ANNOTATION + "source-pvc-uid": "foreign"}),
                     lambda s: s["snapshots"][0]["status"].update(creationTime="2000-01-01T00:00:00Z"),
                     lambda s: s["contents"][0]["spec"]["source"].update(volumeHandle="foreign"),
                     lambda s: s["contents"][0]["spec"]["volumeSnapshotRef"].update(uid="foreign"),
                     lambda s: s["snapshots"][0]["status"].update(readyToUse=False),
                     lambda s: s["snapshots"][0]["status"].update(error={"message": "failed"}),
                     lambda s: s["pvcs"][0]["metadata"].update(uid="replacement")]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                cluster = FakeCluster()
                mutate(cluster.value)
                with self.assertRaises(RuntimeError):
                    upgrade.execute(cluster, args(True))
                self.assertEqual(cluster.mutations, [])

    def test_unhealthy_engine_replica_or_image_stops_before_patch(self):
        mutations = [lambda s: s["volumes"][0]["status"].update(robustness="degraded"),
                     lambda s: s["engines"][0]["status"]["replicaModeMap"].update(r1="WO"),
                     lambda s: s["replicas"][0]["status"].update(currentState="stopped"),
                     lambda s: s["replicas"][0]["spec"].update(failedAt="now"),
                     lambda s: s["images"][1]["status"]["nodeDeploymentMap"].update(node2=False),
                     lambda s: s["images"][1]["status"].update(nodeDeploymentMap=None),
                     lambda s: s["settings"][1].update(value="1")]
        for mutate in mutations:
            cluster = FakeCluster()
            mutate(cluster.value)
            with self.assertRaises(RuntimeError):
                upgrade.execute(cluster, args(True))
            self.assertEqual(cluster.mutations, [])

    def test_adjacent_path_rejects_skips_downgrades_and_unpinned_versions(self):
        upgrade.adjacent("longhornio/longhorn-engine:v1.11.1", "1.12.1")
        for old, target in [("v1.11.1", "1.13.0"), ("v1.13.0", "1.12.1"), ("v1.12.1", "1.13.1")]:
            with self.assertRaises(RuntimeError):
                upgrade.adjacent("longhornio/longhorn-engine:" + old, target)

    def test_cluster_guard_rejects_foreign_cluster(self):
        config = argparse.Namespace(expected_kube_system_uid="expected")
        cluster = upgrade.Cluster(config)
        with patch.object(cluster, "command", return_value={"metadata": {"uid": "foreign"}}):
            with self.assertRaisesRegex(RuntimeError, "kube-system UID"):
                cluster.guard()

    def test_all_namespace_scope_follows_get_subcommand(self):
        cluster = upgrade.Cluster(argparse.Namespace())
        with patch.object(cluster, "command", return_value={"items": []}) as command:
            self.assertEqual(cluster.items("pv", ""), [])
            command.assert_called_once_with("get", "pv", "-A", "-o", "json")

    def test_uses_exact_advertised_docker_io_image(self):
        cluster = FakeCluster()
        cluster.value = json.loads(json.dumps(cluster.value).replace("longhornio/longhorn-engine:",
                                                                   "docker.io/longhornio/longhorn-engine:"))
        _, plan = upgrade.preflight(cluster.state(), args())
        self.assertEqual(plan[0]["to"], "docker.io/" + NEW)
        upgrade.execute(cluster, args(True))
        changes = json.loads(cluster.mutations[0][cluster.mutations[0].index("-p") + 1])
        self.assertEqual(changes[-1]["value"], "docker.io/" + NEW)
        self.assertEqual(cluster.value["volumes"][0]["status"]["currentImage"], "docker.io/" + NEW)


if __name__ == "__main__":
    unittest.main()
