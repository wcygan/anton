"""Behavior of the read-only node gate against a fake three-node cluster.

Each test breaks one thing in an otherwise healthy fixture and asserts exactly
which checks fail, so a check that stops looking at its evidence fails here.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


TESTS = Path(__file__).resolve().parent
REPO = TESTS.parents[1]
sys.path.insert(0, str(REPO / "scripts" / "lib"))
sys.path.insert(0, str(TESTS))

from node_gate import (  # noqa: E402
    PHASE_CHECKS,
    CommandResult,
    NotReadOnly,
    Plan,
    Talos,
    gate,
    parse_table,
    render,
    report,
    require_read_only,
    talconfig_addresses,
    talenv_versions,
)
from node_gate_fixture import (  # noqa: E402
    CONTEXT,
    INVENTORY,
    KUBERNETES,
    LAN,
    TAILSCALE,
    TALOS,
    find_named,
    find_pod,
    healthy,
    instance_manager_name,
    respond,
)


NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)


class FakeRunner:
    def __init__(self, state: dict):
        self.state = state
        self.calls: list[list[str]] = []
        self.lock = threading.Lock()

    def __call__(self, argv, timeout) -> CommandResult:
        with self.lock:
            self.calls.append(list(argv))
        return CommandResult(*respond(self.state, list(argv)))


def endpoints(node: str) -> list[tuple[str, str]]:
    order = [name for name in INVENTORY if name != node] + [node]
    return [(name, TAILSCALE[name]) for name in order]


def run(state: dict, node: str = "k8s-2", phase: str = "pre", **overrides):
    values = dict(
        node=node, phase=phase, inventory=INVENTORY, lan_ips=LAN,
        talos_version=TALOS, kubernetes_version=KUBERNETES,
    )
    gate_options = {key: overrides.pop(key) for key in ("wait", "clock", "sleep", "progress") if key in overrides}
    values.update(overrides)
    runner = FakeRunner(state)
    result = gate(
        Plan(**values), runner=runner, context=CONTEXT, talosconfig="/fake/talosconfig",
        endpoints=endpoints(node), now=lambda: NOW, **gate_options,
    )
    return result, runner


def failed(result) -> list[str]:
    return [check.id for check in result.results if check.status == "FAIL"]


def check(result, check_id: str):
    return next(item for item in result.results if item.id == check_id)


def problems(result, check_id: str) -> str:
    return "\n".join(check(result, check_id).problems)


class HealthyClusterTests(unittest.TestCase):
    def test_every_phase_passes_on_a_healthy_cluster(self) -> None:
        for phase in ("pre", "return", "post"):
            with self.subTest(phase=phase):
                result, runner = run(healthy(phase=phase), phase=phase)
                self.assertEqual(failed(result), [], render(result))
                self.assertTrue(result.passed)
                self.assertEqual([item.id for item in result.results], list(PHASE_CHECKS[phase]))
                self.assertEqual(result.talos_endpoint, "k8s-1")
                self.assertIn(f"NODE GATE PASS k8s-2 phase={phase}", render(result))

    def test_every_command_is_a_read_bound_to_the_target(self) -> None:
        state = healthy(phase="post")
        result, runner = run(state, phase="post")
        self.assertTrue(result.passed, render(result))
        self.assertEqual(state["violations"], [])
        talos_verbs = set()
        for argv in runner.calls:
            if argv[0] == "kubectl":
                self.assertEqual(argv[1:3], ["--context", CONTEXT])
                self.assertEqual(argv[4], "get")
            else:
                self.assertEqual(argv[0], "talosctl")
                self.assertEqual(argv[1:6:2], ["--talosconfig", "-e", "-n"])
                self.assertEqual(argv[4], TAILSCALE["k8s-1"])
                talos_verbs.add(tuple(argv[7:9]) if argv[7] == "etcd" else (argv[7],))
        self.assertEqual(talos_verbs, {("get",), ("ls",), ("read",), ("etcd", "members"), ("etcd", "status")})

    def test_mutating_commands_are_refused_before_they_run(self) -> None:
        runner = FakeRunner(healthy())
        with self.assertRaises(NotReadOnly):
            Talos(runner, "/fake/talosconfig", TAILSCALE["k8s-1"]).run([LAN["k8s-2"]], ("upgrade",))
        for verb in (("reboot",), ("etcd", "remove-member"), ("apply-config",)):
            with self.subTest(verb=verb), self.assertRaises(NotReadOnly):
                require_read_only("talosctl", verb)
        with self.assertRaises(NotReadOnly):
            require_read_only("kubectl", ("cordon",))
        self.assertEqual(runner.calls, [])


class TargetTests(unittest.TestCase):
    def test_talos_is_reached_through_the_next_peer_when_one_is_down(self) -> None:
        state = healthy()
        state["unreachable_endpoints"] = [TAILSCALE["k8s-1"]]
        result, _ = run(state)
        self.assertEqual(failed(result), [], render(result))
        self.assertEqual(result.talos_endpoint, "k8s-3")

    def test_a_peer_that_cannot_route_to_every_node_is_not_a_node_failure(self) -> None:
        state = healthy()
        state["unreachable_routes"] = {TAILSCALE["k8s-1"]: [LAN["k8s-3"]]}
        result, _ = run(state)
        self.assertEqual(failed(result), [], render(result))
        self.assertEqual(result.talos_endpoint, "k8s-3")

    def test_unreachable_talos_fails_every_talos_check_and_keeps_the_rest(self) -> None:
        state = healthy()
        state["unreachable_endpoints"] = list(TAILSCALE.values())
        result, _ = run(state)
        self.assertEqual(failed(result), ["identity", "versions", "etcd", "talos-services", "cni-config"])
        self.assertIn("Talos API unreachable", problems(result, "etcd"))
        self.assertNotIn("100.64.0.", render(result))

    def test_identity_binds_talconfig_kubernetes_and_talos(self) -> None:
        state = healthy()
        state["talos"][LAN["k8s-2"]]["nodename"] = "k8s-3"
        result, _ = run(state)
        self.assertIn("identity", failed(result))
        self.assertIn("reports nodename k8s-3, expected k8s-2", problems(result, "identity"))

        state = healthy()
        find_named(state["kube"]["nodes"], "k8s-3")["status"]["addresses"][0]["address"] = "192.0.2.9"
        result, _ = run(state)
        self.assertEqual(failed(result), ["identity"])
        self.assertIn("talconfig.yaml assigns", problems(result, "identity"))

    def test_a_missing_node_answer_names_the_node(self) -> None:
        state = healthy()
        state["unreachable_nodes"] = [LAN["k8s-3"]]
        result, _ = run(state)
        self.assertEqual(failed(result), ["identity", "etcd"])
        self.assertIn("Talos on k8s-3", problems(result, "identity"))
        self.assertIn("no etcd service status from k8s-3", problems(result, "etcd"))


class NodeTests(unittest.TestCase):
    def test_cordon_state_must_match_the_phase(self) -> None:
        cases = (
            ("pre", "k8s-2", "already cordoned"),
            ("post", "k8s-2", "still cordoned"),
            ("pre", "k8s-3", "maintain one node at a time"),
            ("return", "k8s-1", "maintain one node at a time"),
        )
        for phase, cordoned, message in cases:
            with self.subTest(phase=phase, cordoned=cordoned):
                state = healthy(phase=phase)
                find_named(state["kube"]["nodes"], cordoned)["spec"]["unschedulable"] = True
                result, _ = run(state, phase=phase)
                self.assertEqual(failed(result), ["nodes"])
                self.assertIn(message, problems(result, "nodes"))

    def test_return_requires_the_target_to_stay_cordoned(self) -> None:
        state = healthy(phase="return")
        find_named(state["kube"]["nodes"], "k8s-2")["spec"] = {}
        result, _ = run(state, phase="return")
        self.assertEqual(failed(result), ["nodes"])
        self.assertIn("keep it cordoned until the return gate passes", problems(result, "nodes"))

    def test_a_node_that_is_not_ready_fails(self) -> None:
        state = healthy()
        find_named(state["kube"]["nodes"], "k8s-3")["status"]["conditions"] = [
            {"type": "Ready", "status": "Unknown", "reason": "NodeStatusUnknown"}
        ]
        result, _ = run(state)
        self.assertEqual(failed(result), ["nodes"])
        self.assertIn("k8s-3 is not Ready (NodeStatusUnknown)", problems(result, "nodes"))


class VersionTests(unittest.TestCase):
    @staticmethod
    def running(state: dict, talos: str) -> None:
        state["talos"][LAN["k8s-2"]]["version"] = talos
        find_named(state["kube"]["nodes"], "k8s-2")["status"]["nodeInfo"]["osImage"] = f"Talos ({talos})"

    def test_after_the_reboot_the_node_runs_the_expected_versions(self) -> None:
        for phase in ("return", "post"):
            with self.subTest(phase=phase):
                state = healthy(phase=phase)
                self.running(state, "v1.14.3")
                result, _ = run(state, phase=phase)
                self.assertEqual(failed(result), ["versions"])
                self.assertIn("Talos is v1.14.3, expected v1.14.4", problems(result, "versions"))
                result, _ = run(healthy(phase=phase), phase=phase, kubernetes_version="v1.37.2")
                self.assertEqual(failed(result), ["versions", "control-plane"])

    def test_before_cordon_one_patch_or_minor_step_is_allowed(self) -> None:
        for target in ("v1.14.5", "v1.15.0"):
            with self.subTest(target=target):
                result, _ = run(healthy(), talos_version=target)
                self.assertEqual(failed(result), [])
                self.assertIn(f"pending: Talos {TALOS} -> {target}", check(result, "versions").summary)
        for target, message in (("v1.16.0", "skips a minor"), ("v1.14.3", "rollback, not an upgrade")):
            with self.subTest(target=target):
                result, _ = run(healthy(), talos_version=target)
                self.assertEqual(failed(result), ["versions"])
                self.assertIn(message, problems(result, "versions"))

    def test_only_one_pin_may_be_pending(self) -> None:
        result, _ = run(healthy(), talos_version="v1.14.5", kubernetes_version="v1.37.2")
        self.assertEqual(failed(result), ["versions"])
        self.assertIn("one pin at a time", problems(result, "versions"))

    def test_kubelet_and_talos_must_report_the_same_os(self) -> None:
        state = healthy()
        state["talos"][LAN["k8s-2"]]["version"] = "v1.14.3"
        result, _ = run(state)
        self.assertEqual(failed(result), ["versions"])
        self.assertIn("kubelet reports 'Talos (v1.14.4)' but Talos reports v1.14.3", problems(result, "versions"))


class EtcdTests(unittest.TestCase):
    def test_etcd_needs_three_healthy_voters_that_agree_on_a_leader(self) -> None:
        def unhealthy(state):
            state["talos"][LAN["k8s-3"]]["services"]["etcd"]["healthy"] = False

        def learner(state):
            state["etcd"]["members"][2]["learner"] = True

        def extra_member(state):
            state["etcd"]["members"].append(
                {"id": f"{9:016x}", "hostname": "k8s-old", "address": "192.0.2.50", "learner": False}
            )

        def split_leader(state):
            state["etcd"]["leaders"] = {LAN["k8s-3"]: f"{3:016x}"}

        def errors(state):
            state["talos"][LAN["k8s-1"]]["etcd_errors"] = "etcdserver: request timed out"

        cases = (
            (unhealthy, "etcd on k8s-3 is running=True healthy=False"),
            (learner, "etcd learner members: k8s-3"),
            (extra_member, "expected exactly k8s-1, k8s-2, k8s-3"),
            (split_leader, "do not agree on one listed leader"),
            (errors, "etcd on k8s-1 reports errors: etcdserver: request timed out"),
        )
        for mutate, message in cases:
            with self.subTest(case=mutate.__name__):
                state = healthy()
                mutate(state)
                result, _ = run(state)
                self.assertEqual(failed(result), ["etcd"])
                self.assertIn(message, problems(result, "etcd"))


class TalosServiceTests(unittest.TestCase):
    def test_services_must_run_and_the_machine_must_be_ready(self) -> None:
        state = healthy()
        state["talos"][LAN["k8s-2"]]["services"]["kubelet"]["running"] = False
        state["talos"][LAN["k8s-2"]]["machine"] = {
            "stage": "booting",
            "status": {"ready": False, "unmetConditions": [{"name": "nodeReady", "reason": "node not ready"}]},
        }
        result, _ = run(state)
        self.assertEqual(failed(result), ["talos-services"])
        text = problems(result, "talos-services")
        self.assertIn("service kubelet is not running", text)
        self.assertIn("machine stage is booting", text)
        self.assertIn("nodeReady: node not ready", text)

    def test_a_running_service_without_a_health_check_passes(self) -> None:
        state = healthy()
        state["talos"][LAN["k8s-2"]]["services"]["ext-tailscale"] = {"running": True, "healthy": False, "unknown": True}
        self.assertEqual(failed(run(state)[0]), [])


class ControlPlaneTests(unittest.TestCase):
    def test_static_pods_must_be_ready_and_current(self) -> None:
        state = healthy(phase="return")
        apiserver = find_pod(state, "kube-system", "kube-apiserver-k8s-2")
        apiserver["status"]["conditions"] = [{"type": "Ready", "status": "False"}]
        apiserver["status"]["containerStatuses"][0].update(
            ready=False, restartCount=4, state={"waiting": {"reason": "CrashLoopBackOff"}}
        )
        find_pod(state, "kube-system", "kube-scheduler-k8s-2")["spec"]["containers"][0]["image"] = (
            "registry.k8s.io/kube-scheduler:v1.36.5"
        )
        result, _ = run(state, phase="return")
        self.assertEqual(failed(result), ["control-plane"])
        text = problems(result, "control-plane")
        self.assertIn("kube-apiserver on k8s-2 is not Ready", text)
        self.assertIn("CrashLoopBackOff", text)
        self.assertIn("kube-scheduler runs registry.k8s.io/kube-scheduler:v1.36.5, expected v1.37.1", text)


class CniTests(unittest.TestCase):
    def test_net_d_must_hold_only_the_multus_shim(self) -> None:
        cases = (
            ("stray Cilium config", lambda node: node["cni_dir"].append(["05-cilium.conflist", "-rw-------"]),
             "unexpected /etc/cni/net.d/05-cilium.conflist"),
            ("missing Multus config", lambda node: node["cni_dir"].pop(1), "00-multus.conf is missing"),
            ("wrong plugin type", lambda node: node.update(multus_conf=json.dumps({"type": "cilium-cni"})),
             "has type 'cilium-cni', expected multus-shim"),
            ("whereabouts.d as a file", lambda node: node["cni_dir"].__setitem__(2, ["whereabouts.d", "-rw-r--r--"]),
             "unexpected /etc/cni/net.d/whereabouts.d"),
        )
        for name, mutate, message in cases:
            with self.subTest(case=name):
                state = healthy()
                mutate(state["talos"][LAN["k8s-2"]])
                result, _ = run(state)
                self.assertEqual(failed(result), ["cni-config"])
                self.assertIn(message, problems(result, "cni-config"))

    def test_cni_daemons_on_the_target_must_be_ready(self) -> None:
        state = healthy(phase="return")
        multus = find_pod(state, "network", "kube-multus-ds-2")
        multus["status"]["conditions"] = [{"type": "Ready", "status": "False"}]
        state["kube"]["pods"].remove(find_pod(state, "network", "storage-vxlan-2"))
        result, _ = run(state, phase="return")
        self.assertEqual(failed(result), ["cni-daemons"])
        text = problems(result, "cni-daemons")
        self.assertIn("network/kube-multus-ds-2 on k8s-2 is not Ready", text)
        self.assertIn("no network/storage-vxlan pod on k8s-2", text)


class InstanceManagerTests(unittest.TestCase):
    @staticmethod
    def without_storage_network(state: dict, node: str) -> None:
        manager = find_pod(state, "storage", instance_manager_name(node))
        annotations = manager["metadata"]["annotations"]
        status = [entry for entry in json.loads(annotations["k8s.v1.cni.cncf.io/network-status"])
                  if entry["interface"] != "lhnet1"]
        annotations["k8s.v1.cni.cncf.io/network-status"] = json.dumps(status)

    def test_an_instance_manager_without_lhnet1_fails_on_any_node(self) -> None:
        state = healthy()
        self.without_storage_network(state, "k8s-3")
        result, _ = run(state)
        self.assertEqual(failed(result), ["instance-managers"])
        self.assertIn(f"{instance_manager_name('k8s-3')} on k8s-3 has no lhnet1", problems(result, "instance-managers"))

    def test_replicas_must_serve_on_their_instance_manager_storage_ip(self) -> None:
        state = healthy()
        find_named(state["kube"]["longhorn-replicas"], "pvc-0-r-2")["status"]["storageIP"] = "10.42.2.10"
        result, _ = run(state)
        self.assertEqual(failed(result), ["instance-managers"])
        self.assertIn("serve on 10.42.2.10, not its storage IP 10.100.1.22", problems(result, "instance-managers"))

    def test_lhnet1_must_sit_in_the_storage_network(self) -> None:
        state = healthy()
        state["kube"]["storage-network"]["spec"]["config"] = json.dumps({"ipam": {"range": "10.100.9.0/24"}})
        result, _ = run(state)
        self.assertEqual(failed(result), ["instance-managers"])
        self.assertIn("outside 10.100.9.0/24", problems(result, "instance-managers"))

    def test_every_node_needs_an_instance_manager(self) -> None:
        state = healthy()
        state["kube"]["pods"].remove(find_pod(state, "storage", instance_manager_name("k8s-1")))
        result, _ = run(state)
        self.assertEqual(failed(result), ["instance-managers"])
        self.assertIn("no Longhorn instance manager pod on k8s-1", problems(result, "instance-managers"))


class MultusStatusTests(unittest.TestCase):
    def test_after_the_reboot_every_pod_network_pod_went_through_multus(self) -> None:
        state = healthy(phase="post")
        missing = find_pod(state, "demo", "web-2")
        del missing["metadata"]["annotations"]["k8s.v1.cni.cncf.io/network-status"]
        stale = find_pod(state, "storage", "seaweedfs-volume-1")
        stale["status"].update(podIP="10.42.2.99", podIPs=[{"ip": "10.42.2.99"}])
        stale["status"]["conditions"].append(
            {"type": "PodReadyToStartContainers", "status": "True", "lastTransitionTime": "2026-10-23T11:50:00Z"}
        )
        result, _ = run(state, phase="post")
        self.assertEqual(failed(result), ["multus-status"])
        text = problems(result, "multus-status")
        self.assertIn("demo/web-2 (sandbox since unknown) has no network-status: it started without Multus", text)
        self.assertIn(
            "storage/seaweedfs-volume-1 (sandbox since 2026-10-23T11:50:00Z) network-status lists ['10.42.2.20'], "
            "but the pod IP is 10.42.2.99",
            text,
        )

    def test_a_requested_attachment_must_be_present(self) -> None:
        state = healthy(phase="return")
        InstanceManagerTests.without_storage_network(state, "k8s-2")
        result, _ = run(state, phase="return")
        self.assertEqual(failed(result), ["instance-managers", "multus-status"])
        self.assertIn("requested storage/longhorn-storage but Multus did not attach it", problems(result, "multus-status"))

    def test_before_cordon_pods_from_an_earlier_boot_do_not_gate(self) -> None:
        state = healthy()
        del find_pod(state, "demo", "web-2")["metadata"]["annotations"]["k8s.v1.cni.cncf.io/network-status"]
        result, _ = run(state)
        self.assertNotIn("multus-status", [item.id for item in result.results])
        self.assertTrue(result.passed)


class StorageTests(unittest.TestCase):
    def test_volumes_must_be_healthy_and_longhorn_nodes_schedulable(self) -> None:
        state = healthy()
        state["kube"]["longhorn-volumes"][0]["status"]["robustness"] = "degraded"
        state["kube"]["longhorn-volumes"].append(
            {"metadata": {"name": "pvc-idle"}, "status": {"state": "detached", "robustness": "unknown"}}
        )
        find_named(state["kube"]["longhorn-nodes"], "k8s-1")["status"]["conditions"][1] = {
            "type": "Schedulable", "status": "False", "reason": "KubernetesNodeCordoned",
        }
        result, _ = run(state)
        self.assertEqual(failed(result), ["longhorn"])
        text = problems(result, "longhorn")
        self.assertIn("volume pvc-0 (storage/data-0) is attached/degraded", text)
        self.assertIn("Longhorn node k8s-1 is not Schedulable: KubernetesNodeCordoned", text)
        self.assertNotIn("pvc-idle", text)

    def test_seaweedfs_gauge_must_read_zero_from_every_volume_server(self) -> None:
        state = healthy()
        state["kube"]["seaweedfs-gauge"][0]["value"] = [0, "2"]
        state["kube"]["seaweedfs-gauge"][0]["metric"]["collection"] = "loki"
        state["kube"]["seaweedfs-gauge"].pop()
        result, _ = run(state)
        self.assertEqual(failed(result), ["seaweedfs"])
        text = problems(result, "seaweedfs")
        self.assertIn("seaweedfs-volume-0 reports 2 IsReadOnly volumes in collection loki", text)
        self.assertIn("no read-only gauge from seaweedfs-volume-2", text)

    def test_unreadable_prometheus_fails_instead_of_passing_empty(self) -> None:
        state = healthy()
        state["kube_errors"]["seaweedfs-gauge"] = "Error from server (ServiceUnavailable): no endpoints available"
        result, _ = run(state)
        self.assertEqual(failed(result), ["seaweedfs"])
        self.assertIn("could not read the SeaweedFS read-only gauge", problems(result, "seaweedfs"))


class ClusterTests(unittest.TestCase):
    def test_unhealthy_pods_fail_while_starting_and_failed_pods_do_not(self) -> None:
        state = healthy()
        web = find_pod(state, "demo", "web-1")
        web["status"]["conditions"] = [{"type": "Ready", "status": "False"}]
        web["status"]["containerStatuses"][0].update(ready=False, state={"waiting": {"reason": "CrashLoopBackOff"}})
        starting = json.loads(json.dumps(find_pod(state, "demo", "web-3")))
        starting["metadata"].update(name="web-4", creationTimestamp=(NOW - timedelta(seconds=30)).isoformat())
        starting["status"] = {"phase": "Pending"}
        tombstone = json.loads(json.dumps(find_pod(state, "demo", "web-3")))
        tombstone["metadata"]["name"] = "web-5"
        tombstone["status"] = {"phase": "Failed", "reason": "Evicted"}
        state["kube"]["pods"] += [starting, tombstone]
        result, _ = run(state)
        self.assertEqual(failed(result), ["pods"])
        self.assertIn("demo/web-1 on k8s-1 is Running, web CrashLoopBackOff", problems(result, "pods"))
        self.assertNotIn("web-4", problems(result, "pods"))
        self.assertNotIn("web-5", problems(result, "pods"))
        self.assertEqual(check(result, "pods").details["failed_tombstones"], ["demo/web-5 on k8s-3"])

    def test_flux_objects_must_be_ready_current_and_resumed(self) -> None:
        state = healthy()
        flux = state["kube"]["flux"]
        flux[0]["status"]["conditions"][0].update(status="False", reason="BuildFailed", message="kustomize build failed")
        flux[1]["status"]["observedGeneration"] = 1
        flux[2]["spec"]["suspend"] = True
        result, _ = run(state)
        self.assertEqual(failed(result), ["flux"])
        text = problems(result, "flux")
        self.assertIn("Kustomization flux-system/cluster is not Ready: BuildFailed", text)
        self.assertIn("HelmRelease storage/longhorn has not reconciled generation 2", text)
        self.assertIn("GitRepository flux-system/flux-system is suspended", text)


def alert(name: str, state: str = "active", **labels) -> dict:
    return {
        "labels": {"alertname": name, "severity": "warning", **labels},
        "status": {"state": state},
        "annotations": {"summary": f"{name} summary"},
    }


class AlertTests(unittest.TestCase):
    def test_unexpected_alerts_fail_and_accepted_ones_pass(self) -> None:
        state = healthy()
        state["kube"]["alerts"].append(alert("CronJobSuccessOverdue", namespace="storage"))
        result, _ = run(state)
        self.assertEqual(failed(result), ["alerts"])
        self.assertIn("CronJobSuccessOverdue (warning) on storage: CronJobSuccessOverdue summary", problems(result, "alerts"))
        result, _ = run(state, accepted_alerts=frozenset({"CronJobSuccessOverdue"}))
        self.assertEqual(failed(result), [])
        self.assertEqual(len(check(result, "alerts").details["accepted"]), 1)

    def test_reboot_alerts_are_expected_only_for_rebooted_nodes(self) -> None:
        reboot = alert("NodeUnexpectedReboot", severity="critical", instance=f"{LAN['k8s-2']}:9100")
        restart = alert("MultusDaemonRestarting", namespace="network", pod="kube-multus-ds-2")
        state = healthy(phase="post")
        state["kube"]["alerts"] += [reboot, restart]
        result, _ = run(state, phase="post")
        self.assertEqual(failed(result), [], render(result))
        self.assertEqual(len(check(result, "alerts").details["expected_after_reboot"]), 2)

        state = healthy(node="k8s-3")
        state["kube"]["alerts"].append(reboot)
        result, _ = run(state, node="k8s-3")
        self.assertEqual(failed(result), ["alerts"])
        self.assertIn("NodeUnexpectedReboot (critical) on k8s-2", problems(result, "alerts"))
        result, _ = run(state, node="k8s-3", rebooted=frozenset({"k8s-2"}))
        self.assertEqual(failed(result), [])

    def test_pod_bypassing_multus_is_never_expected(self) -> None:
        state = healthy(phase="post")
        state["kube"]["alerts"].append(alert("PodBypassedMultus", namespace="demo", pod="web-2"))
        result, _ = run(state, phase="post")
        self.assertEqual(failed(result), ["alerts"])
        self.assertIn("PodBypassedMultus (warning) on k8s-2", problems(result, "alerts"))

    def test_without_watchdog_an_empty_alert_list_proves_nothing(self) -> None:
        state = healthy()
        state["kube"]["alerts"] = []
        result, _ = run(state)
        self.assertEqual(failed(result), ["alerts"])
        self.assertIn("Watchdog is not active", problems(result, "alerts"))
        state = healthy()
        state["kube_errors"]["alerts"] = "Error from server (ServiceUnavailable): no endpoints available"
        result, _ = run(state)
        self.assertEqual(failed(result), ["alerts"])
        self.assertIn("could not read Alertmanager alerts", problems(result, "alerts"))

    def test_silenced_alerts_are_reported_without_failing(self) -> None:
        state = healthy()
        state["kube"]["alerts"].append(alert("NodePhysicalFanStoppedOrUnstable", state="suppressed"))
        result, _ = run(state)
        self.assertEqual(failed(result), [])
        self.assertEqual(len(check(result, "alerts").details["silenced_or_inhibited"]), 1)


class DisruptionBudgetTests(unittest.TestCase):
    def test_a_budget_that_would_block_the_drain_fails_before_cordon(self) -> None:
        state = healthy()
        web = find_named(state["kube"]["pdbs"], "web", "demo")
        web["status"]["disruptionsAllowed"] = 0
        result, _ = run(state)
        self.assertEqual(failed(result), ["disruption-budgets"])
        self.assertIn("demo/web allows 0 disruptions and covers web-2 on k8s-2", problems(result, "disruption-budgets"))
        web["spec"]["selector"] = {"matchLabels": {"app": "web"}, "matchExpressions": [
            {"key": "tier", "operator": "Exists"}
        ]}
        self.assertEqual(failed(run(state)[0]), [])

    def test_controller_released_budgets_pass_when_the_controller_can_act(self) -> None:
        result, _ = run(healthy())
        released = "\n".join(check(result, "disruption-budgets").details["released_by_controller"])
        self.assertIn("storage/" + instance_manager_name("k8s-2"), released)
        self.assertIn("registries/harbor-postgres-primary: CloudNativePG switches harbor-postgres-2", released)

        state = healthy()
        state["kube"]["cnpg-clusters"][0]["status"]["readyInstances"] = 2
        result, _ = run(state)
        self.assertEqual(failed(result), ["disruption-budgets"])
        self.assertIn("2/3 instances ready", problems(result, "disruption-budgets"))
        self.assertEqual(failed(run(state, node="k8s-1")[0]), [])

    def test_after_uncordon_budgets_must_be_back_at_their_minimum(self) -> None:
        state = healthy(phase="post")
        find_named(state["kube"]["pdbs"], "seaweedfs-volume")["status"].update(currentHealthy=1, disruptionsAllowed=0)
        find_named(state["kube"]["pdbs"], "web")["metadata"]["generation"] = 2
        result, _ = run(state, phase="post")
        self.assertEqual(failed(result), ["disruption-budgets"])
        text = problems(result, "disruption-budgets")
        self.assertIn("storage/seaweedfs-volume has 1 healthy pods, below its minimum of 2", text)
        self.assertIn("demo/web status has not observed its current generation", text)


class WaitTests(unittest.TestCase):
    def test_wait_retries_until_every_check_passes(self) -> None:
        state = healthy(phase="post")
        state["kube"]["longhorn-volumes"][0]["status"]["robustness"] = "degraded"
        moments = iter(range(0, 1000, 5))
        messages: list[str] = []

        def heal(seconds: float) -> None:
            state["kube"]["longhorn-volumes"][0]["status"]["robustness"] = "healthy"

        result, _ = run(state, phase="post", wait=300, clock=lambda: next(moments), sleep=heal, progress=messages.append)
        self.assertTrue(result.passed, render(result))
        self.assertEqual(result.attempts, 2)
        self.assertIn("attempt 1: FAIL longhorn", messages[0])

    def test_wait_stops_at_the_deadline(self) -> None:
        state = healthy(phase="post")
        state["kube"]["longhorn-volumes"][0]["status"]["robustness"] = "degraded"
        now = [0.0]
        sleeps: list[float] = []

        def sleep(seconds: float) -> None:
            sleeps.append(seconds)
            now[0] += seconds

        result, _ = run(state, phase="post", wait=50, clock=lambda: now[0], sleep=sleep)
        self.assertFalse(result.passed)
        self.assertEqual(sleeps, [20, 20, 10])
        self.assertEqual(result.attempts, 4)
        self.assertIn("NODE GATE FAIL k8s-2 phase=post: longhorn", render(result))


class ReportTests(unittest.TestCase):
    def test_report_and_output_redact_the_tailnet_and_tailscale_addresses(self) -> None:
        state = healthy()
        state["unreachable_endpoints"] = [TAILSCALE["k8s-1"]]
        state["unreachable_nodes"] = [LAN["k8s-3"]]
        state["kube_errors"]["flux"] = f"Unable to connect: dial tcp: lookup {CONTEXT}: no such host"
        result, _ = run(state)
        document = report(result, context=CONTEXT, target_source="override")
        text = json.dumps(document) + render(result)
        self.assertNotIn("example-tailnet", text)
        self.assertNotIn("100.64.0.", text)
        self.assertEqual(document["kube_context"], "tailscale-operator.<tailnet-name>.ts.net")
        self.assertEqual(document["verdict"], "FAIL")
        self.assertEqual(document["talos_endpoint"], "k8s-3")
        self.assertEqual({item["id"]: item["status"] for item in document["checks"]}["flux"], "FAIL")


ETCD_STATUS = """\
NODE            MEMBER             DB SIZE   IN USE           LEADER             RAFT INDEX   RAFT TERM   RAFT APPLIED INDEX   LEARNER   PROTOCOL   STORAGE   ERRORS
192.168.1.98    8626e6c4157f9b39   261 MB    63 MB (24.31%)   8626e6c4157f9b39   362173199    77          362173199            false     3.7.2      3.7.0
192.168.1.100   114ce46a139b1a91   264 MB    63 MB (24.01%)   8626e6c4157f9b39   362173199    77          362173199            false     3.7.2      3.7.0
"""
LS_LONG = """\
NODE           MODE         UID   GID   SIZE(B)   LASTMOD           LABEL                             NAME
192.168.1.98   drwx------   0     0     80        Oct 23 10:59:01   system_u:object_r:cni_conf_t:s0   .
192.168.1.98   -rw-------   0     0     171       Oct 23 10:59:01   system_u:object_r:cni_conf_t:s0   00-multus.conf
"""


class ParserTests(unittest.TestCase):
    def test_talosctl_tables_parse_by_header_offsets(self) -> None:
        rows = parse_table(ETCD_STATUS)
        self.assertEqual([row["NODE"] for row in rows], ["192.168.1.98", "192.168.1.100"])
        self.assertEqual(rows[0]["IN USE"], "63 MB (24.31%)")
        self.assertEqual(rows[1]["LEADER"], "8626e6c4157f9b39")
        self.assertEqual(rows[1]["ERRORS"], "")
        listing = parse_table(LS_LONG)
        self.assertEqual([(row["MODE"], row["NAME"]) for row in listing], [("drwx------", "."), ("-rw-------", "00-multus.conf")])

    def test_committed_talconfig_and_talenv_resolve(self) -> None:
        addresses = talconfig_addresses((REPO / "talos" / "talconfig.yaml").read_text(), INVENTORY)
        self.assertEqual(list(addresses), list(INVENTORY))
        self.assertEqual(len(set(addresses.values())), 3)
        talos, kubernetes = talenv_versions((REPO / "talos" / "talenv.yaml").read_text())
        self.assertRegex(talos, r"^v\d+\.\d+\.\d+")
        self.assertRegex(kubernetes, r"^v\d+\.\d+\.\d+")
        with self.assertRaises(ValueError):
            talconfig_addresses((REPO / "talos" / "talconfig.yaml").read_text(), ("k8s-1", "k8s-2"))


FAKE_BINARY = """#!{python}
import sys
sys.path.insert(0, {tests!r})
from node_gate_fixture import cli_respond
raise SystemExit(cli_respond(sys.argv))
"""


class CommandLineTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        binaries = self.root / "bin"
        binaries.mkdir()
        for name in ("kubectl", "talosctl"):
            path = binaries / name
            path.write_text(FAKE_BINARY.format(python=sys.executable, tests=str(TESTS)), encoding="utf-8")
            path.chmod(0o755)
        self.state = self.root / "state.json"
        self.log = self.root / "calls.jsonl"
        talosconfig = self.root / "talosconfig"
        talosconfig.write_text("context: kubernetes\n", encoding="utf-8")
        self.env = dict(
            os.environ,
            PATH=f"{binaries}{os.pathsep}{os.environ['PATH']}",
            FAKE_CLUSTER_STATE=str(self.state),
            FAKE_CLUSTER_LOG=str(self.log),
            TALOSCONFIG=str(talosconfig),
            ANTON_KUBE_CONTEXT=CONTEXT,
            TALOS_TAILSCALE_NODES=",".join(f"{name}={TAILSCALE[name]}" for name in INVENTORY),
        )

    def gate(self, state: dict, *arguments: str) -> subprocess.CompletedProcess[str]:
        self.state.write_text(json.dumps(state), encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(REPO / "scripts" / "node-gate.py"), *arguments],
            capture_output=True, text=True, env=self.env, timeout=60,
        )

    def versions(self) -> tuple[str, ...]:
        return ("--talos-version", TALOS, "--kubernetes-version", KUBERNETES)

    def test_pass_writes_a_report_and_exits_zero(self) -> None:
        report_path = self.root / "reports" / "k8s-2-pre.json"
        result = self.gate(healthy(), "--node", "k8s-2", "--phase", "pre", *self.versions(), "--report", str(report_path))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("NODE GATE PASS k8s-2 phase=pre (15/15 checks, 1 attempt)", result.stdout)
        document = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual((document["verdict"], document["node"], document["phase"]), ("PASS", "k8s-2", "pre"))
        self.assertEqual(document["talos_target_source"], "override")
        calls = [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]
        self.assertTrue(all(call[1:3] == ["--context", CONTEXT] for call in calls if call[0].endswith("kubectl")))
        self.assertFalse(Path(str(self.log) + ".violations").exists())

    def test_a_failed_check_exits_one(self) -> None:
        state = healthy(phase="post")
        state["kube"]["longhorn-volumes"][0]["status"]["robustness"] = "degraded"
        result = self.gate(state, "--node", "k8s-2", "--phase", "post", *self.versions())
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("NODE GATE FAIL k8s-2 phase=post: longhorn", result.stdout)

    def test_the_gate_refuses_to_start_without_a_resolvable_target(self) -> None:
        cases = (
            (("--node", "k8s-9", "--phase", "pre"), "invalid choice"),
            (("--node", "k8s-2", "--phase", "pre", "--talosconfig", str(self.root / "missing")), "cannot start"),
            (("--node", "k8s-2", "--phase", "pre", "--rebooted", "k8s-9"), "outside the inventory"),
            (("--node", "k8s-2", "--phase", "pre", "--wait", "7200"), "between 0 and 3600"),
            (("--node", "k8s-2", "--phase", "pre", "--report", str(self.state / "report.json")), "cannot start"),
        )
        for arguments, message in cases:
            with self.subTest(arguments=arguments):
                result = self.gate(healthy(), *arguments)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn(message, result.stderr)


if __name__ == "__main__":
    unittest.main()
