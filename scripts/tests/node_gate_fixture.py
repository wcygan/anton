"""A fake three-node Anton cluster that answers node-gate's kubectl and talosctl reads.

``healthy()`` builds a JSON-serializable state; tests mutate it to break one
thing. ``respond()`` turns one argv into (exit code, stdout, stderr) in the
formats the real CLIs print, and records any command outside the gate's
read-only vocabulary as a violation.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "lib"))

from node_gate import ALERTMANAGER_ALERTS, FLUX_KINDS, PROMETHEUS_QUERY, talconfig_addresses  # noqa: E402


CONTEXT = "tailscale-operator.example-tailnet.ts.net"
INVENTORY = ("k8s-1", "k8s-2", "k8s-3")
LAN = talconfig_addresses((REPO / "talos" / "talconfig.yaml").read_text(encoding="utf-8"), INVENTORY)
TAILSCALE = {name: f"100.64.0.{index}" for index, name in enumerate(INVENTORY, start=1)}
TALOS = "v1.14.4"
KUBERNETES = "v1.37.1"
CREATED = "2026-10-23T00:00:00Z"
STORAGE_IPS = {name: f"10.100.1.{20 + index}" for index, name in enumerate(INVENTORY, start=1)}
TALOS_VERBS = {("get",), ("ls",), ("read",), ("etcd", "members"), ("etcd", "status")}


def _index(node: str) -> int:
    return INVENTORY.index(node) + 1


def pod(
    namespace: str,
    name: str,
    node: str,
    *,
    owner: tuple[str, str] | None = None,
    labels: dict[str, str] | None = None,
    host_network: bool = False,
    ip: str | None = None,
    networks: str | None = None,
    attachments: list[dict[str, Any]] | None = None,
    image: str = "registry.example/app:1",
) -> dict[str, Any]:
    annotations: dict[str, str] = {}
    pod_ip = LAN[node] if host_network else ip
    if not host_network:
        status = [{"name": "cilium", "interface": "eth0", "ips": [pod_ip], "default": True, "dns": {}}]
        annotations["k8s.v1.cni.cncf.io/network-status"] = json.dumps(status + (attachments or []))
    if networks:
        annotations["k8s.v1.cni.cncf.io/networks"] = networks
    metadata: dict[str, Any] = {
        "namespace": namespace, "name": name, "uid": f"uid-{namespace}-{name}",
        "creationTimestamp": CREATED, "labels": labels or {}, "annotations": annotations,
    }
    if owner:
        metadata["ownerReferences"] = [{"kind": owner[0], "name": owner[1], "controller": True}]
    return {
        "metadata": metadata,
        "spec": {"nodeName": node, "hostNetwork": host_network, "containers": [{"name": name.split("-")[0], "image": image}]},
        "status": {
            "phase": "Running", "podIP": pod_ip, "podIPs": [{"ip": pod_ip}],
            "conditions": [{"type": "Ready", "status": "True"}],
            "containerStatuses": [{"name": name.split("-")[0], "ready": True, "restartCount": 0, "state": {"running": {}}}],
        },
    }


def instance_manager_name(node: str) -> str:
    return f"instance-manager-{_index(node):032x}"


def _pods() -> list[dict[str, Any]]:
    pods = []
    for node in INVENTORY:
        i = _index(node)
        pods += [
            pod("kube-system", f"cilium-{i}", node, owner=("DaemonSet", "cilium"), host_network=True),
            pod("network", f"kube-multus-ds-{i}", node, owner=("DaemonSet", "kube-multus-ds"), host_network=True),
            pod("network", f"whereabouts-{i}", node, owner=("DaemonSet", "whereabouts"), host_network=True),
            pod("network", f"storage-vxlan-{i}", node, owner=("DaemonSet", "storage-vxlan"), host_network=True),
        ]
        for component in ("kube-apiserver", "kube-controller-manager", "kube-scheduler"):
            pods.append(pod(
                "kube-system", f"{component}-{node}", node, owner=("Node", node), host_network=True,
                image=f"registry.k8s.io/{component}:{KUBERNETES}",
            ))
        pods.append(pod(
            "storage", instance_manager_name(node), node,
            labels={"longhorn.io/component": "instance-manager", "longhorn.io/node": node},
            ip=f"10.42.{i}.10",
            networks=json.dumps([{"namespace": "storage", "name": "longhorn-storage", "interface": "lhnet1"}]),
            attachments=[{"name": "storage/longhorn-storage", "interface": "lhnet1", "ips": [STORAGE_IPS[node]]}],
        ))
        pods.append(pod(
            "storage", f"seaweedfs-volume-{i - 1}", node, owner=("StatefulSet", "seaweedfs-volume"),
            labels={"app.kubernetes.io/instance": "seaweedfs", "app.kubernetes.io/component": "volume"},
            ip=f"10.42.{i}.20",
        ))
        pods.append(pod("demo", f"web-{i}", node, owner=("ReplicaSet", "web-abc"), labels={"app": "web"}, ip=f"10.42.{i}.30"))
        pods.append(pod(
            "registries", f"harbor-postgres-{i}", node, owner=("Cluster", "harbor-postgres"),
            labels={"cnpg.io/cluster": "harbor-postgres", "cnpg.io/instanceRole": "primary" if node == "k8s-2" else "replica"},
            ip=f"10.42.{i}.40",
        ))
    return pods


def _budget(namespace: str, name: str, match: dict[str, str], *, allowed: int, healthy: int, desired: int,
            owner: dict[str, Any] | None = None) -> dict[str, Any]:
    metadata: dict[str, Any] = {"namespace": namespace, "name": name, "generation": 1}
    if owner:
        metadata["ownerReferences"] = [owner]
    return {
        "metadata": metadata,
        "spec": {"selector": {"matchLabels": match}},
        "status": {
            "observedGeneration": 1, "disruptionsAllowed": allowed,
            "currentHealthy": healthy, "desiredHealthy": desired, "expectedPods": healthy,
        },
    }


def _budgets() -> list[dict[str, Any]]:
    budgets = [
        _budget("demo", "web", {"app": "web"}, allowed=1, healthy=3, desired=2),
        _budget("storage", "seaweedfs-volume",
                {"app.kubernetes.io/instance": "seaweedfs", "app.kubernetes.io/component": "volume"},
                allowed=1, healthy=3, desired=2),
        _budget("registries", "harbor-postgres-primary",
                {"cnpg.io/cluster": "harbor-postgres", "cnpg.io/instanceRole": "primary"},
                allowed=0, healthy=1, desired=1,
                owner={"apiVersion": "postgresql.cnpg.io/v1", "kind": "Cluster", "name": "harbor-postgres", "controller": True}),
    ]
    for node in INVENTORY:
        budgets.append(_budget(
            "storage", instance_manager_name(node),
            {"longhorn.io/component": "instance-manager", "longhorn.io/node": node},
            allowed=0, healthy=1, desired=1,
        ))
    return budgets


def _ready(kind: str, namespace: str, name: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "metadata": {"namespace": namespace, "name": name, "generation": 2},
        "spec": {},
        "status": {"observedGeneration": 2, "conditions": [{"type": "Ready", "status": "True", "reason": "Succeeded"}]},
    }


def healthy(node: str = "k8s-2", phase: str = "pre") -> dict[str, Any]:
    nodes = []
    for name in INVENTORY:
        nodes.append({
            "metadata": {"name": name},
            "spec": {"unschedulable": True} if phase == "return" and name == node else {},
            "status": {
                "addresses": [{"type": "InternalIP", "address": LAN[name]}, {"type": "Hostname", "address": name}],
                "conditions": [{"type": "Ready", "status": "True", "reason": "KubeletReady"}],
                "nodeInfo": {"kubeletVersion": KUBERNETES, "osImage": f"Talos ({TALOS})"},
            },
        })
    kube = {
        "nodes": nodes,
        "pods": _pods(),
        "pdbs": _budgets(),
        "storage-network": {
            "metadata": {"namespace": "storage", "name": "longhorn-storage"},
            "spec": {"config": json.dumps({"type": "macvlan", "ipam": {"type": "whereabouts", "range": "10.100.1.0/24"}})},
        },
        "longhorn-volumes": [
            {
                "metadata": {"name": f"pvc-{index}"},
                "status": {"state": "attached", "robustness": "healthy",
                           "kubernetesStatus": {"namespace": "storage", "pvcName": f"data-{index}"}},
            }
            for index in range(2)
        ],
        "longhorn-replicas": [
            {
                "metadata": {"name": f"pvc-0-r-{_index(name)}"},
                "spec": {"nodeID": name, "desireState": "running"},
                "status": {"currentState": "running", "instanceManagerName": instance_manager_name(name),
                           "storageIP": STORAGE_IPS[name]},
            }
            for name in INVENTORY
        ],
        "longhorn-nodes": [
            {"metadata": {"name": name}, "status": {"conditions": [
                {"type": "Ready", "status": "True"}, {"type": "Schedulable", "status": "True"},
            ]}}
            for name in INVENTORY
        ],
        "longhorn-instance-managers": [
            {"metadata": {"name": instance_manager_name(name)},
             "status": {"instanceEngines": {}, "instanceReplicas": {f"pvc-0-r-{_index(name)}": {}}}}
            for name in INVENTORY
        ],
        "cnpg-clusters": [{
            "metadata": {"namespace": "registries", "name": "harbor-postgres"},
            "spec": {"instances": 3}, "status": {"readyInstances": 3},
        }],
        "flux": [
            _ready("Kustomization", "flux-system", "cluster"),
            _ready("HelmRelease", "storage", "longhorn"),
            _ready("GitRepository", "flux-system", "flux-system"),
        ],
        "alerts": [
            {"labels": {"alertname": "Watchdog", "severity": "none"}, "status": {"state": "active"}, "annotations": {}},
            {"labels": {"alertname": "InfoInhibitor", "severity": "none"}, "status": {"state": "suppressed"}, "annotations": {}},
        ],
        "seaweedfs-gauge": [
            {"metric": {"pod": f"seaweedfs-volume-{index}", "type": "IsReadOnly", "namespace": "storage"}, "value": [0, "0"]}
            for index in range(3)
        ],
    }
    talos = {}
    for name in INVENTORY:
        talos[LAN[name]] = {
            "nodename": name,
            "version": TALOS,
            "services": {
                service: {"running": True, "healthy": True, "unknown": False}
                for service in ("apid", "containerd", "cri", "etcd", "kubelet", "machined", "trustd", "udevd")
            } | {"dashboard": {"running": True, "healthy": False, "unknown": True}},
            "machine": {"stage": "running", "status": {"ready": True, "unmetConditions": []}},
            "cni_dir": [[".", "drwx------"], ["00-multus.conf", "-rw-------"], ["whereabouts.d", "drwxr-xr-x"]],
            "multus_conf": json.dumps({
                "cniVersion": "0.3.1", "name": "multus-cni-network", "type": "multus-shim",
                "clusterNetwork": "/etc/cni/multus/net.d/05-cilium.conflist",
            }),
            "etcd_errors": "",
        }
    return {
        "context": CONTEXT,
        "kube": kube,
        "kube_errors": {},
        "talos": talos,
        "etcd": {
            "members": [
                {"id": f"{_index(name):016x}", "hostname": name, "address": LAN[name], "learner": False}
                for name in INVENTORY
            ],
            "leaders": {},
            "leader": f"{1:016x}",
        },
        "unreachable_endpoints": [],
        "unreachable_nodes": [],
        "violations": [],
    }


def find_pod(state: dict[str, Any], namespace: str, name: str) -> dict[str, Any]:
    return next(item for item in state["kube"]["pods"]
                if item["metadata"]["namespace"] == namespace and item["metadata"]["name"] == name)


def find_named(items: list[dict[str, Any]], name: str, namespace: str | None = None) -> dict[str, Any]:
    return next(item for item in items if item["metadata"]["name"] == name
                and (namespace is None or item["metadata"].get("namespace") == namespace))


# --- Responder -------------------------------------------------------------

def _table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [max([len(header)] + [len(row[index]) for row in rows]) for index, header in enumerate(headers)]

    def line(cells: list[str]) -> str:
        return "".join(
            cell.ljust(widths[index] + 3) if index < len(cells) - 1 else cell for index, cell in enumerate(cells)
        )

    return "\n".join([line(headers)] + [line(row) for row in rows]) + "\n"


def _resource(address: str, namespace: str, kind: str, identifier: str, spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "metadata": {"created": CREATED, "id": identifier, "namespace": namespace, "phase": "running",
                     "type": kind, "updated": CREATED, "version": 1},
        "node": address,
        "spec": spec,
    }


def _talos_documents(state: dict[str, Any], address: str, args: list[str]) -> list[dict[str, Any]]:
    node = state["talos"][address]
    kind = args[0]
    if kind == "nodename":
        return [_resource(address, "k8s", "Nodenames.kubernetes.talos.dev", "nodename",
                          {"nodename": node["nodename"], "skipNodeRegistration": False})]
    if kind == "version":
        return [_resource(address, "runtime", "Versions.runtime.talos.dev", "version",
                          {"name": "Talos", "version": node["version"]})]
    if kind == "machinestatus":
        return [_resource(address, "runtime", "MachineStatuses.runtime.talos.dev", "machine", node["machine"])]
    if kind == "services":
        wanted = args[1:2]
        return [
            _resource(address, "runtime", "Services.v1alpha1.talos.dev", name, spec)
            for name, spec in node["services"].items() if not wanted or name == wanted[0]
        ]
    raise ValueError(f"unsupported talosctl get {kind}")


def _talos(state: dict[str, Any], argv: list[str]) -> tuple[int, str, str]:
    args = argv[1:]
    options: dict[str, str] = {}
    while args and args[0] in {"--talosconfig", "-e", "-n"}:
        options[args[0]] = args[1]
        args = args[2:]
    verb = tuple(args[:2]) if args[:1] == ["etcd"] else tuple(args[:1])
    if verb not in TALOS_VERBS or set(options) != {"--talosconfig", "-e", "-n"}:
        state["violations"].append(argv)
        return 99, "", "fake talosctl: refused command outside the read-only vocabulary\n"
    args = args[len(verb):]
    endpoint = options["-e"]
    if endpoint in state["unreachable_endpoints"]:
        return 1, "", f"error: rpc error: code = Unavailable desc = dial tcp {endpoint}:50000: connect: connection refused\n"
    addresses = options["-n"].split(",")
    blocked = set(state["unreachable_nodes"]) | set(state.get("unreachable_routes", {}).get(endpoint, []))
    stderr, answered = [], []
    for address in addresses:
        if address in blocked or address not in state["talos"]:
            stderr.append(f"error on {address}: rpc error: code = Unavailable desc = dial tcp {address}:50000: i/o timeout")
        else:
            answered.append(address)
    code = 1 if stderr else 0
    err = "".join(line + "\n" for line in stderr)
    if verb == ("get",):
        documents = [document for address in answered for document in _talos_documents(state, address, args[:-2])]
        return code, "\n".join(json.dumps(document, indent=4) for document in documents) + ("\n" if documents else ""), err
    if verb == ("etcd", "members"):
        rows = [
            [address, member["id"], member["hostname"], f"https://{member['address']}:2380",
             f"https://{member['address']}:2379", str(member["learner"]).lower()]
            for address in answered for member in state["etcd"]["members"]
        ]
        if not rows:
            return code, "", err
        return code, _table(["NODE", "ID", "HOSTNAME", "PEER URLS", "CLIENT URLS", "LEARNER"], rows), err
    if verb == ("etcd", "status"):
        members = {member["address"]: member for member in state["etcd"]["members"]}
        rows = []
        for address in answered:
            member = members[address]
            leader = state["etcd"]["leaders"].get(address, state["etcd"]["leader"])
            rows.append([address, member["id"], "261 MB", "63 MB (24.31%)", leader, "362173199", "77",
                         "362173199", str(member["learner"]).lower(), "3.7.2", "3.7.0",
                         state["talos"][address]["etcd_errors"]])
        if not rows:
            return code, "", err
        headers = ["NODE", "MEMBER", "DB SIZE", "IN USE", "LEADER", "RAFT INDEX", "RAFT TERM",
                   "RAFT APPLIED INDEX", "LEARNER", "PROTOCOL", "STORAGE", "ERRORS"]
        return code, _table(headers, rows), err
    if verb == ("ls",):
        rows = [
            [address, mode, "0", "0", "100", "Oct 23 10:59:01", "system_u:object_r:cni_conf_t:s0", name]
            for address in answered for name, mode in state["talos"][address]["cni_dir"]
        ]
        if not rows:
            return code, "", err
        return code, _table(["NODE", "MODE", "UID", "GID", "SIZE(B)", "LASTMOD", "LABEL", "NAME"], rows), err
    if verb == ("read",):
        if not answered:
            return code, "", err
        return 0, state["talos"][answered[0]]["multus_conf"], ""
    raise ValueError(f"unhandled talosctl verb {verb}")


KUBE_RESOURCES = {
    "nodes": "nodes",
    "pods": "pods",
    "poddisruptionbudgets.policy": "pdbs",
    "volumes.longhorn.io": "longhorn-volumes",
    "replicas.longhorn.io": "longhorn-replicas",
    "nodes.longhorn.io": "longhorn-nodes",
    "instancemanagers.longhorn.io": "longhorn-instance-managers",
    "clusters.postgresql.cnpg.io": "cnpg-clusters",
    FLUX_KINDS: "flux",
}


def _kubectl(state: dict[str, Any], argv: list[str]) -> tuple[int, str, str]:
    args = argv[1:]
    context = None
    if args[:1] == ["--context"]:
        context, args = args[1], args[2:]
    args = [arg for arg in args if not arg.startswith("--request-timeout=")]
    if args[:1] != ["get"]:
        state["violations"].append(argv)
        return 99, "", "fake kubectl: refused a command other than get\n"
    if context != state["context"]:
        return 1, "", f'error: context "{context}" does not exist\n'
    args = args[1:]
    if args[0] == "--raw":
        path = args[1]
        if path == ALERTMANAGER_ALERTS:
            source, body = "alerts", state["kube"]["alerts"]
        elif path.startswith(PROMETHEUS_QUERY):
            source = "seaweedfs-gauge"
            body = {"status": "success", "data": {"resultType": "vector", "result": state["kube"]["seaweedfs-gauge"]}}
        else:
            raise ValueError(f"unsupported raw path {path}")
    elif args[0] == "network-attachment-definitions.k8s.cni.cncf.io":
        source, body = "storage-network", state["kube"]["storage-network"]
    else:
        source = KUBE_RESOURCES[args[0]]
        body = {"apiVersion": "v1", "kind": "List", "items": state["kube"][source]}
    if source in state["kube_errors"]:
        return 1, "", state["kube_errors"][source] + "\n"
    return 0, json.dumps(body), ""


def respond(state: dict[str, Any], argv: list[str]) -> tuple[int, str, str]:
    binary = Path(argv[0]).name
    if binary == "kubectl":
        return _kubectl(state, argv)
    if binary == "talosctl":
        return _talos(state, argv)
    state["violations"].append(argv)
    return 99, "", f"fake cluster: unexpected binary {binary}\n"


def cli_respond(argv: list[str]) -> int:
    """Entry point for fake kubectl/talosctl executables used by CLI tests."""
    state_path = Path(os.environ["FAKE_CLUSTER_STATE"])
    state = json.loads(state_path.read_text(encoding="utf-8"))
    with open(os.environ["FAKE_CLUSTER_LOG"], "a", encoding="utf-8") as log:
        log.write(json.dumps(argv[:1] + argv[1:]) + "\n")
    code, stdout, stderr = respond(state, argv)
    if state["violations"]:
        with open(os.environ["FAKE_CLUSTER_LOG"] + ".violations", "a", encoding="utf-8") as log:
            log.write(json.dumps(argv) + "\n")
    sys.stdout.write(stdout)
    sys.stderr.write(stderr)
    return code
