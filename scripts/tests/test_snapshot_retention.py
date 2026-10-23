"""Exercise expiry, identity and CSI cleanup without touching production data."""
import copy
import datetime
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[2] / "kubernetes/apps/storage/longhorn-maintenance/app/snapshot-retention.py"
spec = importlib.util.spec_from_file_location("retention", SOURCE)
retention = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retention)
NOW = datetime.datetime(2026, 10, 22, tzinfo=datetime.timezone.utc)


def snapshot():
    return {"metadata": {"namespace": "storage", "name": "maintenance", "uid": "snapshot-uid", "resourceVersion": "10", "finalizers": [retention.BOUND],
                         "annotations": {retention.RELEASE: "snapshot-uid", retention.AFTER: "2026-10-21T00:00:00Z"}},
            "spec": {"volumeSnapshotClassName": retention.CLASS},
            "status": {"boundVolumeSnapshotContentName": "content"}}


def content():
    return {"metadata": {"uid": "content-uid", "resourceVersion": "11"},
            "spec": {"volumeSnapshotRef": {"namespace": "storage", "name": "maintenance", "uid": "snapshot-uid"},
                     "volumeSnapshotClassName": retention.CLASS, "driver": "driver.longhorn.io", "deletionPolicy": "Retain",
                     "source": {"volumeHandle": "volume"}}, "status": {"snapshotHandle": "snap://volume/backend"}}


class API:
    def __init__(self):
        self.snapshot = snapshot()
        self.content = content()
        self.pvcs = []
        self.writes = []
        self.volume_health = "healthy"
        self.protected = [{"metadata": {"labels": {retention.recovery.GEN: g, retention.recovery.OWNER: "cluster-recovery"}},
                           "status": {"readyToUse": True}} for g in ("one", "two") for _ in range(6)]

    def get(self, ns, kind, name):
        if kind == "volumesnapshots":
            return copy.deepcopy(self.snapshot)
        return {"data": {"phase": "complete", "verified": "one", "previous_verified": "two", "verified_report": "{}"}}

    def list(self, ns, kind):
        if kind == "persistentvolumeclaims":
            return self.pvcs if ns == "storage" else []
        return self.protected if ns == "storage" else []

    def path(self, ns, kind, name):
        return "/snapshot/" + name

    def request(self, method, path, data=None):
        if method != "GET":
            self.writes.append((method, path, copy.deepcopy(data)))
        if path.endswith("/volumes"):
            return {"items": [{"status": {"robustness": self.volume_health, "state": "attached"}}]}
        if path == "/api/v1/persistentvolumeclaims":
            return {"items": self.pvcs}
        if path.endswith("/snapshots/backend"):
            return None
        if path.endswith("/content"):
            if method == "PUT":
                self.content = copy.deepcopy(data)
                self.snapshot["metadata"]["resourceVersion"] = "12"
            return copy.deepcopy(self.content)
        if method == "DELETE":
            self.snapshot = None
            self.content = None
        return copy.deepcopy(self.snapshot)


class RetentionTests(unittest.TestCase):
    def test_unreleased_and_future_snapshots_are_preserved(self):
        s = snapshot()
        s["metadata"]["annotations"] = {}
        self.assertFalse(retention.released(s, NOW))
        s = snapshot()
        s["metadata"]["annotations"][retention.AFTER] = "2026-11-01T00:00:00Z"
        self.assertFalse(retention.released(s, NOW))

    def test_invalid_or_copied_release_fails_closed(self):
        for key, value in ((retention.RELEASE, "copied-uid"), (retention.AFTER, "bad"), (retention.AFTER, "2026-10-21")):
            s = snapshot()
            s["metadata"]["annotations"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises((RuntimeError, ValueError)):
                retention.released(s, NOW)

    def test_recovery_class_and_labels_cannot_be_released(self):
        for mutate in (lambda s: s["spec"].update(volumeSnapshotClassName="longhorn-recurring-recovery"),
                       lambda s: s["metadata"].update(labels={retention.recovery.GEN: "one"})):
            s = snapshot()
            mutate(s)
            with self.assertRaises(RuntimeError):
                retention.released(s, NOW)

    def test_wrong_binding_driver_volume_and_backup_handle_are_rejected(self):
        for mutate in (lambda c: c["spec"]["volumeSnapshotRef"].update(uid="other"),
                       lambda c: c["spec"].update(driver="other"),
                       lambda c: c["spec"]["source"].update(volumeHandle="other"),
                       lambda c: c["status"].update(snapshotHandle="bs://volume/backend")):
            c = content()
            mutate(c)
            with self.assertRaises(RuntimeError):
                retention.binding(snapshot(), c, [])

    def test_both_restore_reference_forms_block_deletion(self):
        for key in ("dataSource", "dataSourceRef"):
            pvc = {"metadata": {"namespace": "storage"}, "spec": {key: {"kind": "VolumeSnapshot", "name": "maintenance"}}}
            with self.assertRaisesRegex(RuntimeError, "restore consumer"):
                retention.binding(snapshot(), content(), [pvc])

    def test_cross_namespace_restore_reference_blocks_all_writes(self):
        api = API()
        api.pvcs = [{"metadata": {"namespace": "another-app"}, "spec": {"dataSourceRef": {
            "kind": "VolumeSnapshot", "name": "maintenance", "namespace": "storage"}}}]
        with self.assertRaisesRegex(RuntimeError, "restore consumer"):
            retention.remove(api, snapshot(), NOW)
        self.assertFalse(api.writes)

    def test_delete_updates_content_policy_then_uses_uid_and_revision(self):
        api = API()
        retention.remove(api, snapshot(), NOW)
        self.assertEqual([x[0] for x in api.writes], ["PUT", "DELETE"])
        self.assertEqual(api.writes[0][2]["spec"]["deletionPolicy"], "Delete")
        self.assertEqual(api.writes[1][2]["preconditions"], {"uid": "snapshot-uid", "resourceVersion": "12"})
        retention.remove(api, snapshot(), NOW)
        self.assertEqual(len(api.writes), 2)

    def test_resume_after_policy_change_does_not_repeat_update(self):
        api = API()
        api.content["spec"]["deletionPolicy"] = "Delete"
        retention.remove(api, snapshot(), NOW)
        self.assertEqual([x[0] for x in api.writes], ["DELETE"])

    def test_release_revoked_during_policy_update_blocks_delete(self):
        api = API()
        request = api.request
        def revoke(method, path, data=None):
            result = request(method, path, data)
            if method == "PUT":
                api.snapshot["metadata"]["annotations"].clear()
            return result
        api.request = revoke
        with self.assertRaisesRegex(RuntimeError, "revoked after"):
            retention.remove(api, snapshot(), NOW)
        self.assertEqual([x[0] for x in api.writes], ["PUT"])

    def test_waits_for_async_csi_finalizer_and_uses_resulting_revision(self):
        api = API()
        api.snapshot["metadata"]["finalizers"] = []
        def controller_step(_):
            self.assertEqual([x[0] for x in api.writes], ["PUT"])
            api.snapshot["metadata"]["finalizers"] = [retention.BOUND]
            api.snapshot["metadata"]["resourceVersion"] = "13"
        with patch.object(retention.time, "sleep", side_effect=controller_step) as sleep:
            retention.remove(api, snapshot(), NOW)
        sleep.assert_called_once_with(2)
        self.assertEqual(api.writes[1][2]["preconditions"]["resourceVersion"], "13")

    def test_missing_csi_protection_times_out_without_delete(self):
        api = API()
        api.snapshot["metadata"]["finalizers"] = []
        with patch.object(retention.time, "monotonic", side_effect=[0, 241]):
            with self.assertRaisesRegex(RuntimeError, "installed Delete-policy protection"):
                retention.remove(api, snapshot(), NOW)
        self.assertEqual([x[0] for x in api.writes], ["PUT"])

    def test_replaced_snapshot_and_revoked_release_cannot_write(self):
        for change in (lambda a: a.snapshot["metadata"].update(uid="replacement"),
                       lambda a: a.snapshot["metadata"]["annotations"].clear()):
            api = API()
            change(api)
            with self.assertRaises(RuntimeError):
                retention.remove(api, snapshot(), NOW)
            self.assertFalse(api.writes)

    def test_health_blocks_missing_verified_point_and_degraded_volumes(self):
        api = API()
        retention.health(api)
        api.protected.pop()
        with self.assertRaisesRegex(RuntimeError, "Verified snapshots"):
            retention.health(api)
        api = API()
        api.volume_health = "degraded"
        with self.assertRaisesRegex(RuntimeError, "healthy/attached"):
            retention.health(api)


if __name__ == "__main__":
    unittest.main()
