"""Behavioral contract for the two-phase, proxy-aware node drain command."""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "drain-node.py"
CONTEXT = "tailscale-operator.example.invalid.ts.net"
CLUSTER_UID = "cluster-uid"
NODE_UID = "node-uid"
OPERATOR_UID = "operator-uid"
OLD_POD_UID = "old-pod-uid"
NEW_POD_UID = "new-pod-uid"


FAKE_KUBECTL = r'''#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

state_path = Path(os.environ["FAKE_KUBECTL_STATE"])
log_path = Path(os.environ["FAKE_KUBECTL_LOG"])
state = json.loads(state_path.read_text())
args = sys.argv[1:]
try:
    context_index = args.index("--context")
    actual_context = args[context_index + 1]
    del args[context_index:context_index + 2]
except (ValueError, IndexError):
    actual_context = ""
args = [arg for arg in args if not arg.startswith("--request-timeout=")]
stdin = sys.stdin.read()
with log_path.open("a") as log:
    log.write(json.dumps({"args": args, "context": actual_context, "stdin": stdin}) + "\n")

def emit(value):
    print(json.dumps(value))

def owner(kind, name, uid):
    return {"apiVersion": "apps/v1", "kind": kind, "name": name, "uid": uid, "controller": True}

def pod(name, uid, node, rs_name, rs_uid):
    metadata = {
        "name": name, "uid": uid, "labels": {"app": "operator"},
        "ownerReferences": [owner("ReplicaSet", rs_name, rs_uid)],
    }
    if state.get("deleting_pod") and uid == "old-pod-uid":
        metadata["deletionTimestamp"] = "2026-10-19T00:00:00Z"
    return {
        "apiVersion": "v1", "kind": "Pod",
        "metadata": metadata,
        "spec": {"nodeName": node},
        "status": {"conditions": [{"type": "Ready", "status": "True"}]},
    }

def deployment(uid):
    state["deployment_reads"] = state.get("deployment_reads", 0) + 1
    if state.get("evicted"):
        state["recovery_deployment_reads"] = state.get("recovery_deployment_reads", 0) + 1
    state_path.write_text(json.dumps(state))
    ready_replicas = 0 if (
        state.get("evicted")
        and state["recovery_deployment_reads"] <= state.get("not_ready_recovery_reads", 0)
    ) else 1
    return {
        "apiVersion": "apps/v1", "kind": "Deployment",
        "metadata": {"name": "operator", "uid": uid, "generation": 2},
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": {"app": "operator"}},
            "template": {"spec": {"containers": [{"name": "operator", "env": [
                {"name": "APISERVER_PROXY", "value": state.get("api_proxy", "true")}
            ]}]}},
        },
        "status": {"observedGeneration": 2, "readyReplicas": ready_replicas},
    }

if args == ["config", "current-context"]:
    print(state.get("context", "tailscale-operator.example.invalid.ts.net"))
elif args[:3] == ["get", "namespace", "kube-system"]:
    emit({"metadata": {"name": "kube-system", "uid": state.get("cluster_uid", "cluster-uid")}})
elif args[:2] == ["get", "node"]:
    state["node_reads"] = state.get("node_reads", 0) + 1
    state_path.write_text(json.dumps(state))
    node_uid = state.get("node_uid", "node-uid")
    if state.get("node_uid_after_first_read") and state["node_reads"] > 1:
        node_uid = state["node_uid_after_first_read"]
    emit({
        "metadata": {"name": "k8s-2", "uid": node_uid},
        "spec": {"unschedulable": state.get("cordoned", True)},
        "status": {"conditions": [{"type": "Ready", "status": "True"}]},
    })
elif args[:2] == ["get", "deployment"]:
    emit(deployment(state.get("operator_uid", "operator-uid")))
elif args[:2] == ["get", "pods"]:
    if state.get("pod_get_failures", 0) > 0 and state.get("evicted"):
        state["pod_get_failures"] -= 1
        state_path.write_text(json.dumps(state))
        print(f"Unable to connect to {state.get('leak_host', 'the server')}: connection reset by peer", file=sys.stderr)
        sys.exit(1)
    if state.get("evicted") and state.get("replace", True):
        items = [pod("operator-new", "new-pod-uid", state.get("replacement_node", "k8s-3"), "operator-new-rs", "new-rs-uid")]
    elif state.get("proxy_off_node"):
        items = [pod("operator-old", "old-pod-uid", "k8s-3", "operator-old-rs", "old-rs-uid")]
    else:
        items = [pod("operator-old", "old-pod-uid", "k8s-2", "operator-old-rs", "old-rs-uid")]
    emit({"apiVersion": "v1", "kind": "PodList", "items": items})
elif args[:2] == ["get", "replicaset"]:
    name = args[2]
    rs_uid = "new-rs-uid" if name == "operator-new-rs" else "old-rs-uid"
    emit({
        "apiVersion": "apps/v1", "kind": "ReplicaSet",
        "metadata": {
            "name": name, "uid": rs_uid,
            "ownerReferences": [owner("Deployment", "operator", state.get("rs_owner_uid_after_eviction", state.get("rs_owner_uid", state.get("operator_uid", "operator-uid"))) if state.get("evicted") else state.get("rs_owner_uid", state.get("operator_uid", "operator-uid")))],
        },
    })
elif args[:2] == ["create", "--raw"]:
    state["eviction_count"] = state.get("eviction_count", 0) + 1
    state["eviction_body"] = json.loads(stdin)
    if state.get("pdb_refusal"):
        state_path.write_text(json.dumps(state))
        print("Error from server (TooManyRequests): cannot evict pod as it would violate its disruption budget", file=sys.stderr)
        sys.exit(1)
    if state.get("replace", True):
        state["evicted"] = True
    state_path.write_text(json.dumps(state))
    if state.get("lost_response"):
        print("Unable to connect to the server: connection reset by peer", file=sys.stderr)
        sys.exit(1)
    emit({"kind": "Eviction", "apiVersion": "policy/v1"})
elif args and args[0] == "drain":
    state["drain_count"] = state.get("drain_count", 0) + 1
    state["drain_args"] = args
    state_path.write_text(json.dumps(state))
    if state.get("drain_hang"):
        import time
        time.sleep(10)
    if state.get("drain_failure"):
        print("node drain failed", file=sys.stderr)
        sys.exit(1)
    print("node drained")
else:
    print("unsupported fake kubectl command: " + " ".join(args), file=sys.stderr)
    sys.exit(2)

if "eviction_count" in state or "drain_count" in state:
    state_path.write_text(json.dumps(state))
'''


class DrainNodeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        kubectl = self.bin / "kubectl"
        kubectl.write_text(FAKE_KUBECTL, encoding="utf-8")
        kubectl.chmod(0o755)
        self.state_path = self.root / "state.json"
        self.log_path = self.root / "commands.jsonl"
        self.state_path.write_text("{}", encoding="utf-8")

    def invoke(self, *extra: str, state: dict | None = None, timeout: float = 5) -> subprocess.CompletedProcess[str]:
        if state is not None:
            self.state_path.write_text(json.dumps(state), encoding="utf-8")
        env = os.environ.copy()
        env["PATH"] = f"{self.bin}:{env['PATH']}"
        env["FAKE_KUBECTL_STATE"] = str(self.state_path)
        env["FAKE_KUBECTL_LOG"] = str(self.log_path)
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--node", "k8s-2",
                "--expected-context", CONTEXT,
                "--expected-cluster-uid", CLUSTER_UID,
                "--expected-node-uid", NODE_UID,
                "--expected-operator-uid", OPERATOR_UID,
                "--timeout", str(timeout),
                *extra,
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=(timeout + 3) if math.isfinite(timeout) else 5,
        )

    def state(self) -> dict:
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def commands(self) -> list[dict]:
        return [json.loads(line) for line in self.log_path.read_text(encoding="utf-8").splitlines()]

    def test_lost_eviction_response_observes_replacement_then_drains_once(self) -> None:
        result = self.invoke(state={"lost_response": True})

        self.assertEqual(result.returncode, 0, result.stderr)
        state = self.state()
        self.assertEqual(state["eviction_count"], 1)
        self.assertEqual(state["eviction_body"]["deleteOptions"]["preconditions"]["uid"], OLD_POD_UID)
        self.assertEqual(state["drain_count"], 1)
        self.assertIn("node drained", result.stdout)
        self.assertIn("--ignore-daemonsets", state["drain_args"])
        self.assertFalse(any(arg == "--delete-emptydir-data" for arg in state["drain_args"]))
        timeout_arg = next(arg for arg in state["drain_args"] if arg.startswith("--timeout="))
        self.assertGreater(float(timeout_arg.split("=", 1)[1][:-1]), 0)
        self.assertLessEqual(float(timeout_arg.split("=", 1)[1][:-1]), 5)
        self.assertLess(
            next(i for i, call in enumerate(self.commands()) if call["args"][:2] == ["create", "--raw"]),
            next(i for i, call in enumerate(self.commands()) if call["args"][0] == "drain"),
        )
        calls = self.commands()
        self.assertEqual(calls[0]["args"], ["config", "current-context"])
        self.assertEqual(calls[0]["context"], "")
        self.assertTrue(
            all(
                call["context"] == ("" if call["args"] == ["config", "current-context"] else CONTEXT)
                for call in calls
            )
        )

    def test_pdb_refusal_stops_without_retry_or_bulk_drain(self) -> None:
        result = self.invoke(state={"pdb_refusal": True})

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refused by a PodDisruptionBudget", result.stderr)
        self.assertEqual(self.state()["eviction_count"], 1)
        self.assertNotIn("drain_count", self.state())

    def test_unobserved_eviction_times_out_without_reposting_or_bulk_drain(self) -> None:
        result = self.invoke(
            state={
                "lost_response": True,
                "replace": False,
                "pod_get_failures": 100,
                "leak_host": CONTEXT,
            },
            timeout=1,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("timed out waiting for recovered API proxy", result.stderr)
        self.assertEqual(self.state()["eviction_count"], 1)
        self.assertNotIn("drain_count", self.state())
        self.assertNotIn(CONTEXT, result.stderr)

    def test_replacement_on_target_stops_without_bulk_drain(self) -> None:
        result = self.invoke(state={"lost_response": True, "replacement_node": "k8s-2"})

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("replacement Tailscale operator pod is still on the target node", result.stderr)
        self.assertEqual(self.state()["eviction_count"], 1)
        self.assertNotIn("drain_count", self.state())

    def test_transient_readiness_and_get_failure_recover_without_reposting(self) -> None:
        result = self.invoke(
            state={
                "lost_response": True,
                "not_ready_recovery_reads": 1,
                "pod_get_failures": 1,
            }
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        state = self.state()
        self.assertEqual(state["eviction_count"], 1)
        self.assertEqual(state["drain_count"], 1)

    def test_wrong_replacement_owner_stops_without_bulk_drain(self) -> None:
        result = self.invoke(
            state={"lost_response": True, "rs_owner_uid_after_eviction": "stale-deployment"}
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("owner chain does not match", result.stderr)
        self.assertEqual(self.state()["eviction_count"], 1)
        self.assertNotIn("drain_count", self.state())

    def test_missing_api_proxy_mode_stops_before_eviction(self) -> None:
        result = self.invoke(state={"api_proxy": "false"})

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("APISERVER_PROXY=true", result.stderr)
        self.assertNotIn("eviction_count", self.state())
        self.assertNotIn("drain_count", self.state())

    def test_hung_bulk_drain_is_bounded_by_overall_deadline(self) -> None:
        # The fake drain hangs for 10 s. Allow enough of the overall deadline
        # for the earlier fake kubectl calls to finish on a loaded machine;
        # 0.5 s let the deadline expire before the drain started (1 in 6 runs).
        result = self.invoke(state={"proxy_off_node": True, "drain_hang": True}, timeout=2)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("remaining overall timeout", result.stderr)
        self.assertEqual(self.state()["drain_count"], 1)

    def test_failed_bulk_drain_is_not_retried(self) -> None:
        result = self.invoke(state={"proxy_off_node": True, "drain_failure": True})

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("node drain failed", result.stderr)
        self.assertEqual(self.state()["drain_count"], 1)

    def test_revalidates_target_uid_after_proxy_recovery(self) -> None:
        result = self.invoke(state={"node_uid_after_first_read": "reused-node-name"})

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("node k8s-2 UID changed", result.stderr)
        self.assertEqual(self.state()["eviction_count"], 1)
        self.assertNotIn("drain_count", self.state())

    def test_wrong_target_uid_stops_before_eviction(self) -> None:
        result = self.invoke(state={"node_uid": "reused-node-name"})

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("node k8s-2 UID changed", result.stderr)
        self.assertNotIn("eviction_count", self.state())
        self.assertNotIn("drain_count", self.state())

    def test_wrong_context_and_uncordoned_target_stop_before_eviction(self) -> None:
        for field, value, expected in (
            ("context", "admin@anton", "active context must exactly match"),
            ("cordoned", False, "must remain cordoned"),
        ):
            with self.subTest(field=field):
                self.log_path.unlink(missing_ok=True)
                result = self.invoke(state={field: value})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stderr)
                self.assertNotIn("eviction_count", self.state())
                self.assertNotIn("drain_count", self.state())

    def test_wrong_deployment_owner_chain_stops_before_eviction(self) -> None:
        result = self.invoke(state={"rs_owner_uid": "replaced-deployment"})

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("owner chain does not match", result.stderr)
        self.assertNotIn("eviction_count", self.state())
        self.assertNotIn("drain_count", self.state())

    def test_wrong_cluster_or_operator_uid_stops_before_eviction(self) -> None:
        for field, value, expected in (
            ("cluster_uid", "other-cluster", "kube-system namespace UID"),
            ("operator_uid", "other-operator", "Tailscale operator Deployment UID"),
        ):
            with self.subTest(field=field):
                self.log_path.unlink(missing_ok=True)
                result = self.invoke(state={field: value})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stderr)
                self.assertNotIn("eviction_count", self.state())
                self.assertNotIn("drain_count", self.state())

    def test_proxy_already_off_target_skips_eviction(self) -> None:
        result = self.invoke(state={"proxy_off_node": True})

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("eviction_count", self.state())
        self.assertEqual(self.state()["drain_count"], 1)

    def test_delete_emptydir_is_explicit(self) -> None:
        result = self.invoke("--delete-emptydir-data", state={"proxy_off_node": True})

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--delete-emptydir-data", self.state()["drain_args"])

    def test_nonfinite_timeout_is_rejected(self) -> None:
        result = self.invoke(state={}, timeout=float("nan"))

        self.assertEqual(result.returncode, 2)
        self.assertIn("--timeout must be greater than zero and at most 3600 seconds", result.stderr)


if __name__ == "__main__":
    unittest.main()
