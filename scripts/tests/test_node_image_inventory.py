import datetime as dt
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.node_image_inventory import canonical_ref, classify, gc_eligibility, parse_table, workload_references


class NodeImages(unittest.TestCase):
    def test_shared_digest_and_stopped_container_are_protected(self):
        images = [{"IMAGE": ref, "DIGEST": digest, "LABELS": ""} for ref, digest in
                  [("docker.io/library/busybox:1", "sha256:a"), ("old-alias", "sha256:a"),
                   ("sha256:config", "sha256:b"), ("unmatched", "sha256:c")]]
        report = classify(images, [{"IMAGE": "sha256:config", "STATUS": "CONTAINER_EXITED"}], {"busybox:1"})
        self.assertEqual(report["candidate_references"], ["unmatched"])
        self.assertIsNone(report["reclaimable_bytes"])

    def test_recursive_desired_and_rollback_init_images(self):
        refs = workload_references([{"spec": {"replicas": 0, "template": {"spec": {
            "initContainers": [{"image": "init:1"}], "containers": [{"image": "app:1"}]}}}},
            {"kind": "ReplicaSet", "spec": {"template": {"spec": {"containers": [{"image": "rollback:1"}]}}}}])
        self.assertEqual(refs, {"init:1", "app:1", "rollback:1"})

    def test_start_time_resets_eligibility(self):
        now = dt.datetime(2026, 10, 13, 16, tzinfo=dt.timezone.utc)
        fresh = gc_eligibility("Started task kubelet (PID 1) for container kubelet (13h15m0s ago)", now)
        self.assertFalse(fresh["aging_window_complete"])
        self.assertEqual(fresh["eligible_after"], "2026-10-20T03:15:00+00:00")
        self.assertIsNone(gc_eligibility("unavailable", now)["eligible_after"])

    def test_fixed_columns_keep_size_units_and_empty_labels(self):
        text = "NODE  IMAGE       DIGEST    SIZE    LABELS  CREATED\nnode  busybox:1   sha256:a  82 MB           2026-01-01\n"
        row = parse_table(text, ("NODE", "IMAGE", "DIGEST", "SIZE", "LABELS", "CREATED"))[0]
        self.assertEqual(row["SIZE"], "82 MB")
        self.assertEqual(row["LABELS"], "")

    def test_implicit_latest_and_runtime_prefix(self):
        self.assertEqual(canonical_ref("busybox"), "docker.io/library/busybox:latest")
        self.assertEqual(canonical_ref("containerd://sha256:abc"), "sha256:abc")
