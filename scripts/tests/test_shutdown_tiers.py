"""Source contract: on node shutdown the kubelet stops storage last.

On 2026-10-22 a SeaweedFS volume server was killed mid-write and two Loki
volumes stayed read-only for 34 hours. The Talos kubelet patch stops pods one
PriorityClass tier at a time, so writers stop before SeaweedFS and SeaweedFS
before Longhorn. These tests keep the kubelet groups, the classes and the
grace periods the budgets were sized for in step.
"""

import json
from pathlib import Path
import subprocess
import unittest


REPO = Path(__file__).resolve().parents[2]
KUBELET_PATCH = REPO / "talos/patches/global/machine-kubelet.yaml"
PRIORITY_CLASSES = REPO / "kubernetes/apps/kube-system/priority-classes/app/priorityclasses.yaml"
LOKI = REPO / "kubernetes/apps/observability/loki/app/helmrelease.yaml"
SEAWEED = REPO / "kubernetes/apps/storage/seaweedfs-config/app/seaweed.yaml"

LONGHORN_CRITICAL = 1_000_000_000
SYSTEM_CLUSTER_CRITICAL = 2_000_000_000
SYSTEM_NODE_CRITICAL = 2_000_001_000
# Talos waits this long for the kubelet to release its shutdown inhibitor lock
# before stopping it (logind.InhibitMaxDelay in Talos 1.14).
TALOS_INHIBIT_MAX_DELAY_SECONDS = 1200
# Default toleration for the not-ready taint. A shutting-down kubelet reports
# NotReady; after this long the taint deletes the remaining pods, and
# Longhorn's node-down policy may then force-delete them and detach volumes.
NOT_READY_TOLERATION_SECONDS = 300


def documents(path):
    output = subprocess.check_output(["yq", "-o=json", "-I=0", ".", str(path)], text=True, timeout=30)
    return [json.loads(line) for line in output.splitlines() if line.strip()]


class ShutdownTierTests(unittest.TestCase):
    def setUp(self):
        self.kubelet = documents(KUBELET_PATCH)[0]["machine"]["kubelet"]["extraConfig"]
        self.groups = sorted(
            (group["priority"], group["shutdownGracePeriodSeconds"])
            for group in self.kubelet["shutdownGracePeriodByPodPriority"]
        )
        self.classes = {
            document["metadata"]["name"]: document["value"]
            for document in documents(PRIORITY_CLASSES)
            if document.get("kind") == "PriorityClass"
        }

    def budget(self, priority):
        """Seconds the kubelet gives the group a pod of this priority falls in."""
        return [seconds for boundary, seconds in self.groups if boundary <= priority][-1]

    def test_every_tier_has_its_own_shutdown_group(self):
        expected = {0, LONGHORN_CRITICAL, SYSTEM_CLUSTER_CRITICAL, SYSTEM_NODE_CRITICAL, *self.classes.values()}
        self.assertEqual([priority for priority, _ in self.groups], sorted(expected))

    def test_legacy_grace_periods_are_explicitly_zero(self):
        # Talos sets 30s and 10s when these keys are absent, and the kubelet
        # refuses to start with them alongside per-priority groups.
        self.assertEqual(self.kubelet["shutdownGracePeriod"], "0s")
        self.assertEqual(self.kubelet["shutdownGracePeriodCriticalPods"], "0s")

    def test_total_budget_fits_the_talos_shutdown_wait(self):
        self.assertLessEqual(sum(seconds for _, seconds in self.groups), TALOS_INHIBIT_MAX_DELAY_SECONDS)

    def test_longhorn_consumers_stop_before_not_ready_eviction(self):
        below_longhorn = sum(seconds for priority, seconds in self.groups if priority < LONGHORN_CRITICAL)
        self.assertLess(below_longhorn, NOT_READY_TOLERATION_SECONDS)

    def test_tier_members_fit_their_budget(self):
        # The kubelet cuts a pod's grace period to its group's budget.
        members = {
            "loki": documents(LOKI)[0]["spec"]["values"]["singleBinary"],
            "seaweedfs volume": documents(SEAWEED)[0]["spec"]["volume"],
        }
        for name, spec in members.items():
            if "priorityClassName" not in spec:
                continue
            with self.subTest(name):
                grace = spec.get("terminationGracePeriodSeconds", 30)
                self.assertLessEqual(grace, self.budget(self.classes[spec["priorityClassName"]]))


if __name__ == "__main__":
    unittest.main()
