"""Read-only gate for one Anton node during Talos or Kubernetes maintenance.

Run it at three points of a node's maintenance:

- ``pre``: before cordon. Every check must pass before the node is cordoned.
- ``return``: after the reboot, while the node is still cordoned. It must pass
  before uncordon.
- ``post``: after uncordon. It must pass before the next node starts.

The gate only reads. Kubernetes reads always go through ``kubectl get`` and
Talos reads through ``require_read_only``, so it cannot change any state.
"""

from __future__ import annotations

import ipaddress
import json
import math
import re
import subprocess
import time
import urllib.parse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


PHASES = ("pre", "return", "post")

STORAGE_NAMESPACE = "storage"
STORAGE_NETWORK = "longhorn-storage"
STORAGE_INTERFACE = "lhnet1"
CNI_DIR = "/etc/cni/net.d"
MULTUS_CONFIG = "00-multus.conf"
CNI_DAEMONSETS = (
    ("kube-system", "cilium"),
    ("network", "kube-multus-ds"),
    ("network", "whereabouts"),
    ("network", "storage-vxlan"),
)
CONTROL_PLANE = ("kube-apiserver", "kube-controller-manager", "kube-scheduler")
NETWORK_STATUS = "k8s.v1.cni.cncf.io/network-status"
NETWORKS = "k8s.v1.cni.cncf.io/networks"
ALWAYS_ACTIVE_ALERTS = frozenset({"Watchdog", "InfoInhibitor"})
# Every reboot raises these: NodeUnexpectedReboot while uptime is under 30
# minutes, MultusDaemonRestarting for the restart during boot. They are
# tolerated only for the target after its reboot and for --rebooted nodes.
REBOOT_ALERTS = frozenset({"NodeUnexpectedReboot", "MultusDaemonRestarting"})
ALERTMANAGER_ALERTS = (
    "/api/v1/namespaces/observability/services/"
    "kube-prometheus-stack-alertmanager:9093/proxy/api/v2/alerts?active=true"
)
PROMETHEUS_QUERY = (
    "/api/v1/namespaces/observability/services/"
    "kube-prometheus-stack-prometheus:9090/proxy/api/v1/query?query="
)
SEAWEEDFS_READ_ONLY = f'SeaweedFS_volumeServer_read_only_volumes{{namespace="{STORAGE_NAMESPACE}"}}'
FLUX_KINDS = ",".join(
    (
        "kustomizations.kustomize.toolkit.fluxcd.io",
        "helmreleases.helm.toolkit.fluxcd.io",
        "gitrepositories.source.toolkit.fluxcd.io",
        "ocirepositories.source.toolkit.fluxcd.io",
        "helmrepositories.source.toolkit.fluxcd.io",
    )
)
# A pod this young, or terminating this recently, is settling, not unhealthy.
SETTLE_SECONDS = 120
COMMAND_TIMEOUT = 30.0
MAX_PRINTED_PROBLEMS = 8

KUBECTL_VERBS = frozenset({("get",)})
TALOSCTL_VERBS = frozenset({("get",), ("ls",), ("read",), ("etcd", "members"), ("etcd", "status")})


class NotReadOnly(ValueError):
    """The gate refused a command outside its read-only vocabulary."""


class Unavailable(Exception):
    """A check needed an observation that could not be collected."""


def require_read_only(binary: str, verb: tuple[str, ...]) -> None:
    allowed = {"kubectl": KUBECTL_VERBS, "talosctl": TALOSCTL_VERBS}.get(binary, frozenset())
    if verb not in allowed:
        raise NotReadOnly(f"node-gate refuses to run {binary} {' '.join(verb)}")


# --- Redaction -------------------------------------------------------------

_TAILNET = re.compile(r"(?<![A-Za-z0-9-])[A-Za-z0-9-]+\.ts\.net\b", re.IGNORECASE)
_TAILSCALE_IP = re.compile(r"(?<![\d.])100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}(?!\d)")


def redact(value: Any) -> Any:
    """Hide the tailnet name and Tailscale addresses in every string."""
    if isinstance(value, str):
        return _TAILSCALE_IP.sub("<tailscale-ip>", _TAILNET.sub("<tailnet-name>.ts.net", value))
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    return value


# --- Commands --------------------------------------------------------------

@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[Sequence[str], float], CommandResult]


def run_command(argv: Sequence[str], timeout: float) -> CommandResult:
    try:
        result = subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return CommandResult(124, "", f"{argv[0]} timed out after {timeout:.0f}s")
    except OSError as error:
        return CommandResult(127, "", f"could not run {argv[0]}: {error}")
    return CommandResult(result.returncode, result.stdout, result.stderr)


@dataclass
class Observation:
    value: Any = None
    ok: bool = False
    # Command error text. A multi-node Talos read can be ok with an error:
    # some nodes answered and the check reports the ones that did not.
    error: str | None = None


def _error_text(result: CommandResult) -> str:
    text = (result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}").splitlines()
    return redact(" ".join(line.strip() for line in text[-3:]))[:400]


class Kube:
    def __init__(self, runner: Runner, context: str):
        self.runner = runner
        self.context = context

    def get(self, *args: str) -> CommandResult:
        argv = ["kubectl", "--context", self.context, f"--request-timeout={COMMAND_TIMEOUT:.0f}s", "get", *args]
        return self.runner(argv, COMMAND_TIMEOUT + 5)

    def _json(self, *args: str) -> Observation:
        result = self.get(*args)
        if result.returncode != 0:
            return Observation(error=_error_text(result))
        try:
            return Observation(json.loads(result.stdout), ok=True)
        except json.JSONDecodeError:
            return Observation(error="kubectl returned invalid JSON")

    def items(self, *args: str) -> Observation:
        observation = self._json(*args, "-o", "json")
        if observation.ok:
            items = observation.value.get("items") if isinstance(observation.value, dict) else None
            if not isinstance(items, list):
                return Observation(error="kubectl returned no items list")
            observation.value = items
        return observation

    def object(self, *args: str) -> Observation:
        return self._json(*args, "-o", "json")

    def raw(self, path: str) -> Observation:
        return self._json("--raw", path)

    def prometheus(self, query: str) -> Observation:
        observation = self.raw(PROMETHEUS_QUERY + urllib.parse.quote(query, safe=""))
        if observation.ok:
            body = observation.value
            if not isinstance(body, dict) or body.get("status") != "success":
                return Observation(error=f"Prometheus query failed: {str(body)[:200]}")
            observation.value = body.get("data", {}).get("result", [])
        return observation


def parse_json_stream(text: str) -> list[Any]:
    decoder = json.JSONDecoder()
    index, documents = 0, []
    while True:
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            return documents
        value, index = decoder.raw_decode(text, index)
        documents.append(value)


_HEADER_CELL = re.compile(r"\S+(?: \S+)*")


def parse_table(text: str) -> list[dict[str, str]]:
    """Parse talosctl's aligned table output by its header column offsets."""
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return []
    columns = [(match.start(), match.group()) for match in _HEADER_CELL.finditer(lines[0])]
    rows = []
    for line in lines[1:]:
        row = {}
        for index, (start, name) in enumerate(columns):
            end = columns[index + 1][0] if index + 1 < len(columns) else None
            row[name] = line[start:end].strip()
        rows.append(row)
    return rows


class Talos:
    def __init__(self, runner: Runner, talosconfig: str, endpoint: str):
        self.runner = runner
        self.talosconfig = talosconfig
        self.endpoint = endpoint

    def run(self, nodes: Sequence[str], verb: tuple[str, ...], *args: str) -> CommandResult:
        require_read_only("talosctl", verb)
        argv = [
            "talosctl", "--talosconfig", self.talosconfig,
            "-e", self.endpoint, "-n", ",".join(nodes), *verb, *args,
        ]
        return self.runner(argv, COMMAND_TIMEOUT)

    def _partial(self, result: CommandResult, value: Any, answered: bool) -> Observation:
        error = _error_text(result) if result.returncode != 0 else None
        return Observation(value, ok=result.returncode == 0 or answered, error=error)

    def resources(self, nodes: Sequence[str], *args: str) -> Observation:
        result = self.run(nodes, ("get",), *args, "-o", "json")
        try:
            documents = parse_json_stream(result.stdout)
        except json.JSONDecodeError:
            return Observation(error="talosctl returned invalid JSON")
        return self._partial(result, documents, bool(documents))

    def table(self, nodes: Sequence[str], verb: tuple[str, ...], *args: str) -> Observation:
        result = self.run(nodes, verb, *args)
        rows = parse_table(result.stdout)
        return self._partial(result, rows, bool(rows))

    def text(self, nodes: Sequence[str], verb: tuple[str, ...], *args: str) -> Observation:
        result = self.run(nodes, verb, *args)
        if result.returncode != 0:
            return Observation(error=_error_text(result))
        return Observation(result.stdout, ok=True)


# --- Inputs ----------------------------------------------------------------

@dataclass(frozen=True)
class Plan:
    node: str
    phase: str
    inventory: tuple[str, ...]
    lan_ips: Mapping[str, str]
    talos_version: str
    kubernetes_version: str
    accepted_alerts: frozenset[str] = frozenset()
    rebooted: frozenset[str] = frozenset()

    @property
    def reboot_expected(self) -> frozenset[str]:
        """Nodes whose by-design reboot alerts the alert check tolerates."""
        return self.rebooted | (frozenset({self.node}) if self.phase != "pre" else frozenset())

    def address(self, node: str | None = None) -> str:
        return self.lan_ips[node or self.node]

    def every_address(self) -> list[str]:
        return [self.lan_ips[name] for name in self.inventory]


def talconfig_addresses(text: str, names: Sequence[str]) -> dict[str, str]:
    """Map each talconfig.yaml node hostname to its management ipAddress."""
    addresses: dict[str, str] = {}
    current = None
    for line in text.splitlines():
        hostname = re.match(r"""^\s*-\s+hostname:\s*["']?([^"'\s#]+)""", line)
        if hostname:
            current = hostname.group(1)
            continue
        address = re.match(r"""^\s+ipAddress:\s*["']?([^"'\s#]+)""", line)
        if address and current and current not in addresses:
            addresses[current] = address.group(1)
    if sorted(addresses) != sorted(names):
        raise ValueError(f"talconfig.yaml nodes {sorted(addresses)} do not match the inventory {list(names)}")
    for name, value in addresses.items():
        if ipaddress.ip_address(value).version != 4:
            raise ValueError(f"talconfig.yaml gives {name} a non-IPv4 address")
    if len(set(addresses.values())) != len(addresses):
        raise ValueError("talconfig.yaml assigns one address to two nodes")
    return {name: addresses[name] for name in names}


def talenv_versions(text: str) -> tuple[str, str]:
    """Return (talosVersion, kubernetesVersion) pinned in talenv.yaml."""
    versions = []
    for key in ("talosVersion", "kubernetesVersion"):
        match = re.search(rf"""(?m)^{key}:\s*["']?(v\d+\.\d+\.\d+[^"'\s#]*)""", text)
        if not match:
            raise ValueError(f"talenv.yaml has no {key}")
        versions.append(match.group(1))
    return versions[0], versions[1]


# --- Snapshot --------------------------------------------------------------

SOURCE_LABELS = {
    "nodes": "Kubernetes nodes",
    "pods": "pods",
    "pdbs": "PodDisruptionBudgets",
    "storage-network": f"NetworkAttachmentDefinition {STORAGE_NAMESPACE}/{STORAGE_NETWORK}",
    "longhorn-volumes": "Longhorn volumes",
    "longhorn-replicas": "Longhorn replicas",
    "longhorn-nodes": "Longhorn nodes",
    "longhorn-instance-managers": "Longhorn instance managers",
    "cnpg-clusters": "CloudNativePG clusters",
    "flux": "Flux objects",
    "alerts": "Alertmanager alerts",
    "seaweedfs-gauge": "the SeaweedFS read-only gauge from Prometheus",
    "talos-nodenames": "Talos node names",
    "talos-version": "the Talos version",
    "talos-etcd-services": "Talos etcd service status",
    "talos-etcd-members": "etcd members",
    "talos-etcd-status": "etcd status",
    "talos-services": "Talos services",
    "talos-machinestatus": "Talos machine status",
    "talos-cni-dir": f"the {CNI_DIR} listing",
    "talos-multus-conf": f"{CNI_DIR}/{MULTUS_CONFIG}",
}


@dataclass
class Snapshot:
    observations: dict[str, Observation]
    talos_endpoint: str | None = None

    def get(self, name: str) -> Any:
        observation = self.observations.get(name)
        if observation is None or not observation.ok:
            reason = observation.error if observation and observation.error else "not collected"
            raise Unavailable(f"could not read {SOURCE_LABELS[name]}: {reason}")
        return observation.value

    def missing(self, name: str) -> str:
        """Suffix explaining why some nodes are absent from a partial read."""
        observation = self.observations.get(name)
        return f" ({observation.error})" if observation and observation.error else ""


def _kube_fetchers(kube: Kube) -> dict[str, Callable[[], Observation]]:
    return {
        "nodes": lambda: kube.items("nodes"),
        "pods": lambda: kube.items("pods", "-A"),
        "pdbs": lambda: kube.items("poddisruptionbudgets.policy", "-A"),
        "storage-network": lambda: kube.object(
            "network-attachment-definitions.k8s.cni.cncf.io", "-n", STORAGE_NAMESPACE, STORAGE_NETWORK
        ),
        "longhorn-volumes": lambda: kube.items("volumes.longhorn.io", "-n", STORAGE_NAMESPACE),
        "longhorn-replicas": lambda: kube.items("replicas.longhorn.io", "-n", STORAGE_NAMESPACE),
        "longhorn-nodes": lambda: kube.items("nodes.longhorn.io", "-n", STORAGE_NAMESPACE),
        "longhorn-instance-managers": lambda: kube.items("instancemanagers.longhorn.io", "-n", STORAGE_NAMESPACE),
        "cnpg-clusters": lambda: kube.items("clusters.postgresql.cnpg.io", "-A"),
        "flux": lambda: kube.items(FLUX_KINDS, "-A"),
        "alerts": lambda: kube.raw(ALERTMANAGER_ALERTS),
        "seaweedfs-gauge": lambda: kube.prometheus(SEAWEEDFS_READ_ONLY),
    }


def _talos_fetchers(talos: Talos, plan: Plan) -> dict[str, Callable[[], Observation]]:
    target, every = [plan.address()], plan.every_address()
    return {
        "talos-version": lambda: talos.resources(target, "version"),
        "talos-etcd-services": lambda: talos.resources(every, "services", "etcd"),
        "talos-etcd-members": lambda: talos.table(target, ("etcd", "members")),
        "talos-etcd-status": lambda: talos.table(every, ("etcd", "status")),
        "talos-services": lambda: talos.resources(target, "services"),
        "talos-machinestatus": lambda: talos.resources(target, "machinestatus"),
        "talos-cni-dir": lambda: talos.table(target, ("ls",), "-l", CNI_DIR),
        "talos-multus-conf": lambda: talos.text(target, ("read",), f"{CNI_DIR}/{MULTUS_CONFIG}"),
    }


def collect(
    plan: Plan,
    needed: set[str],
    *,
    runner: Runner,
    context: str,
    talosconfig: str,
    endpoints: Sequence[tuple[str, str]],
) -> Snapshot:
    """Read every needed source once.

    Talos goes through the first endpoint that reaches every node, or else the
    one that reaches the most, so one peer's path problem is not a node failure.
    """
    observations: dict[str, Observation] = {}
    fetchers = _kube_fetchers(Kube(runner, context))
    endpoint_name = None
    if any(name.startswith("talos-") for name in needed):
        errors, talos, answered = [], None, 0
        for name, address in endpoints:
            candidate = Talos(runner, talosconfig, address)
            names = candidate.resources(plan.every_address(), "nodename")
            count = len({document.get("node") for document in names.value}) if names.ok else 0
            if count > answered:
                talos, endpoint_name, answered = candidate, name, count
                observations["talos-nodenames"] = names
            if count == len(plan.inventory):
                break
            errors.append(f"through {name}: {names.error or 'no answer'}")
        if talos is None:
            failure = Observation(error="Talos API unreachable " + "; ".join(errors))
            for name in SOURCE_LABELS:
                if name.startswith("talos-"):
                    observations[name] = failure
        else:
            fetchers.update(_talos_fetchers(talos, plan))
    pending = sorted(name for name in needed if name not in observations)
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {name: pool.submit(fetchers[name]) for name in pending}
        for name, future in futures.items():
            observations[name] = future.result()
    return Snapshot(observations, endpoint_name)


# --- Object helpers --------------------------------------------------------

def _meta(item: Mapping[str, Any]) -> Mapping[str, Any]:
    return item.get("metadata") or {}


def _key(item: Mapping[str, Any]) -> str:
    return f"{_meta(item).get('namespace')}/{_meta(item).get('name')}"


def condition(item: Mapping[str, Any], kind: str) -> Mapping[str, Any]:
    for entry in (item.get("status") or {}).get("conditions") or []:
        if entry.get("type") == kind:
            return entry
    return {}


def controller_of(item: Mapping[str, Any]) -> tuple[str | None, str | None] | None:
    for owner in _meta(item).get("ownerReferences") or []:
        if owner.get("controller"):
            return owner.get("kind"), owner.get("name")
    return None


def pod_ready(pod: Mapping[str, Any]) -> bool:
    return (
        (pod.get("status") or {}).get("phase") == "Running"
        and not _meta(pod).get("deletionTimestamp")
        and condition(pod, "Ready").get("status") == "True"
    )


def pod_state(pod: Mapping[str, Any]) -> str:
    status = pod.get("status") or {}
    parts = [status.get("phase") or "Unknown"]
    if _meta(pod).get("deletionTimestamp"):
        parts.append("terminating")
    for container in status.get("containerStatuses") or []:
        waiting = (container.get("state") or {}).get("waiting")
        if waiting:
            parts.append(f"{container.get('name')} {waiting.get('reason') or 'waiting'}")
        elif not container.get("ready"):
            parts.append(f"{container.get('name')} not ready")
        if container.get("restartCount"):
            parts.append(f"{container.get('name')} restarted {container['restartCount']}x")
    return ", ".join(parts)


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _age(value: str | None, now: datetime) -> float:
    moment = parse_time(value)
    return (now - moment).total_seconds() if moment else math.inf


def internal_ip(node: Mapping[str, Any]) -> str | None:
    for address in (node.get("status") or {}).get("addresses") or []:
        if address.get("type") == "InternalIP":
            return address.get("address")
    return None


def selector_matches(selector: Mapping[str, Any] | None, labels: Mapping[str, str]) -> bool:
    """policy/v1 semantics: a null selector selects nothing, {} selects every pod."""
    if selector is None:
        return False
    for key, value in (selector.get("matchLabels") or {}).items():
        if labels.get(key) != value:
            return False
    for expression in selector.get("matchExpressions") or []:
        key, operator = expression.get("key"), expression.get("operator")
        values = expression.get("values") or []
        if operator == "In" and labels.get(key) not in values:
            return False
        if operator == "NotIn" and key in labels and labels[key] in values:
            return False
        if operator == "Exists" and key not in labels:
            return False
        if operator == "DoesNotExist" and key in labels:
            return False
        if operator not in {"In", "NotIn", "Exists", "DoesNotExist"}:
            return False
    return True


def parse_version(value: str | None) -> tuple[int, int, int] | None:
    match = re.match(r"^v?(\d+)\.(\d+)\.(\d+)", value or "")
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


def upgrade_step_problem(current: str, target: str) -> str | None:
    """Reject a downgrade or a skipped minor; patch and next-minor steps pass."""
    have, want = parse_version(current), parse_version(target)
    if have is None or want is None:
        return f"cannot compare {current!r} with {target!r}"
    if want < have:
        return f"{target} is older than the running {current}; that is a rollback, not an upgrade"
    if want[0] != have[0] or want[1] > have[1] + 1:
        return f"{current} -> {target} skips a minor version; upgrade one minor at a time"
    return None


def network_statuses(pod: Mapping[str, Any]) -> tuple[list[dict[str, Any]] | None, str | None]:
    raw = (_meta(pod).get("annotations") or {}).get(NETWORK_STATUS)
    if raw is None:
        return None, None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return [], "not JSON"
    if not isinstance(value, list) or not all(isinstance(entry, dict) for entry in value):
        return [], "not a list of attachments"
    return value, None


def requested_networks(pod: Mapping[str, Any]) -> list[tuple[str, str | None]]:
    """Return (namespace/name, interface) for each NetworkAttachmentDefinition a pod requests."""
    raw = ((_meta(pod).get("annotations") or {}).get(NETWORKS) or "").strip()
    namespace = _meta(pod).get("namespace")
    if not raw:
        return []
    if raw.startswith("["):
        return [
            (f"{entry.get('namespace') or namespace}/{entry.get('name')}", entry.get("interface"))
            for entry in json.loads(raw)
        ]
    requested = []
    for item in raw.split(","):
        name, _, interface = item.strip().partition("@")
        requested.append((name if "/" in name else f"{namespace}/{name}", interface or None))
    return requested


def _nodes(snapshot: Snapshot) -> dict[str, Mapping[str, Any]]:
    return {_meta(node).get("name"): node for node in snapshot.get("nodes")}


def _pods_on(snapshot: Snapshot, node: str) -> list[Mapping[str, Any]]:
    return [pod for pod in snapshot.get("pods") if (pod.get("spec") or {}).get("nodeName") == node]


def _for_node(documents: Sequence[Mapping[str, Any]], address: str) -> list[Mapping[str, Any]]:
    return [document for document in documents if document.get("node") == address]


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" + ("" if count == 1 else "s")


# --- Checks ----------------------------------------------------------------

@dataclass
class Outcome:
    summary: str
    problems: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CheckResult:
    id: str
    title: str
    status: str
    summary: str
    problems: tuple[str, ...]
    details: Mapping[str, Any]


def check_identity(plan: Plan, snapshot: Snapshot, now: datetime) -> Outcome:
    nodes = _nodes(snapshot)
    problems = []
    missing = [name for name in plan.inventory if name not in nodes]
    extra = sorted(set(nodes) - set(plan.inventory))
    if missing:
        problems.append(f"Kubernetes has no node {', '.join(missing)}")
    if extra:
        problems.append(f"Kubernetes has nodes outside the inventory: {', '.join(extra)}")
    for name in plan.inventory:
        if name in nodes and internal_ip(nodes[name]) != plan.address(name):
            problems.append(
                f"{name} has InternalIP {internal_ip(nodes[name])}, but talconfig.yaml assigns {plan.address(name)}"
            )
    reported = {
        document.get("node"): (document.get("spec") or {}).get("nodename")
        for document in snapshot.get("talos-nodenames")
    }
    for name in plan.inventory:
        answer = reported.get(plan.address(name))
        if answer is None:
            problems.append(f"Talos on {name} ({plan.address(name)}) did not answer{snapshot.missing('talos-nodenames')}")
        elif answer != name:
            problems.append(f"Talos at {plan.address(name)} reports nodename {answer}, expected {name}")
    return Outcome(
        f"{', '.join(plan.inventory)} match talconfig.yaml, Kubernetes and Talos; Talos API through {snapshot.talos_endpoint}",
        problems,
        {"addresses": dict(plan.lan_ips), "talos_endpoint": snapshot.talos_endpoint},
    )


def check_nodes(plan: Plan, snapshot: Snapshot, now: datetime) -> Outcome:
    nodes = _nodes(snapshot)
    problems, cordoned = [], []
    for name in plan.inventory:
        node = nodes.get(name)
        if node is None:
            problems.append(f"{name} is missing")
            continue
        ready = condition(node, "Ready")
        if ready.get("status") != "True":
            problems.append(f"{name} is not Ready ({ready.get('reason') or ready.get('status') or 'no Ready condition'})")
        is_cordoned = (node.get("spec") or {}).get("unschedulable") is True
        should_be = plan.phase == "return" and name == plan.node
        if is_cordoned:
            cordoned.append(name)
        if is_cordoned == should_be:
            continue
        if should_be:
            problems.append(f"{name} is schedulable; keep it cordoned until the return gate passes")
        elif name != plan.node:
            problems.append(f"{name} is cordoned; maintain one node at a time")
        elif plan.phase == "pre":
            problems.append(f"{name} is already cordoned; the pre gate must pass before cordon")
        else:
            problems.append(f"{name} is still cordoned; uncordon it once the return gate passes")
    return Outcome(
        f"{len(plan.inventory)}/{len(plan.inventory)} Ready; cordoned: {', '.join(cordoned) or 'none'}",
        problems,
        {"cordoned": cordoned},
    )


def check_versions(plan: Plan, snapshot: Snapshot, now: datetime) -> Outcome:
    node = _nodes(snapshot).get(plan.node)
    if node is None:
        return Outcome("", [f"{plan.node} is missing from Kubernetes"])
    info = (node.get("status") or {}).get("nodeInfo") or {}
    kubelet, os_image = info.get("kubeletVersion"), info.get("osImage") or ""
    documents = _for_node(snapshot.get("talos-version"), plan.address())
    talos = (documents[0].get("spec") or {}).get("version") if documents else None
    problems, pending = [], []
    if talos is None:
        problems.append(f"Talos on {plan.node} did not report its version{snapshot.missing('talos-version')}")
    elif os_image != f"Talos ({talos})":
        problems.append(f"kubelet reports {os_image!r} but Talos reports {talos}")
    if plan.phase == "pre":
        for label, current, target in (
            ("Talos", talos, plan.talos_version),
            ("Kubernetes", kubelet, plan.kubernetes_version),
        ):
            if current is None or current == target:
                continue
            problem = upgrade_step_problem(current, target)
            if problem:
                problems.append(f"{label} {problem}")
            else:
                pending.append(f"{label} {current} -> {target}")
        if len(pending) == 2:
            problems.append("Talos and Kubernetes upgrades are both pending; bump and roll one pin at a time")
        summary = f"Talos {talos}, kubelet {kubelet}; " + (f"pending: {', '.join(pending)}" if pending else "no upgrade pending")
    else:
        if talos is not None and talos != plan.talos_version:
            problems.append(f"Talos is {talos}, expected {plan.talos_version}")
        if kubelet != plan.kubernetes_version:
            problems.append(f"kubelet is {kubelet}, expected {plan.kubernetes_version}")
        summary = f"Talos {talos} and kubelet {kubelet} as expected"
    return Outcome(
        summary,
        problems,
        {
            "talos": talos,
            "kubelet": kubelet,
            "expected_talos": plan.talos_version,
            "expected_kubernetes": plan.kubernetes_version,
            "pending": pending,
        },
    )


def check_etcd(plan: Plan, snapshot: Snapshot, now: datetime) -> Outcome:
    problems = []
    services = {
        document.get("node"): document.get("spec") or {}
        for document in snapshot.get("talos-etcd-services")
    }
    for name in plan.inventory:
        spec = services.get(plan.address(name))
        if spec is None:
            problems.append(f"no etcd service status from {name}{snapshot.missing('talos-etcd-services')}")
        elif not (spec.get("running") and spec.get("healthy")):
            problems.append(f"etcd on {name} is running={spec.get('running')} healthy={spec.get('healthy')}")
    members = snapshot.get("talos-etcd-members")
    hostnames = sorted(row.get("HOSTNAME", "") for row in members)
    if hostnames != sorted(plan.inventory):
        problems.append(f"etcd members are [{', '.join(hostnames)}]; expected exactly {', '.join(plan.inventory)}")
    learners = [row.get("HOSTNAME") for row in members if row.get("LEARNER", "false") != "false"]
    if learners:
        problems.append(f"etcd learner members: {', '.join(learners)}")
    member_hosts = {row.get("ID"): row.get("HOSTNAME") for row in members}
    rows = {row.get("NODE"): row for row in snapshot.get("talos-etcd-status")}
    leaders = set()
    for name in plan.inventory:
        row = rows.get(plan.address(name))
        if row is None:
            problems.append(f"no etcd status from {name}{snapshot.missing('talos-etcd-status')}")
            continue
        if row.get("ERRORS"):
            problems.append(f"etcd on {name} reports errors: {row['ERRORS']}")
        if member_hosts.get(row.get("MEMBER")) != name:
            problems.append(f"etcd on {name} answers as member {row.get('MEMBER')}, which is not {name}'s member")
        leaders.add(row.get("LEADER"))
    leader = member_hosts.get(next(iter(leaders))) if len(leaders) == 1 else None
    if rows and leader is None:
        problems.append(f"etcd members do not agree on one listed leader: {sorted(str(item) for item in leaders)}")
    return Outcome(
        f"{len(members)} members, all healthy voters; leader {leader}",
        problems,
        {"members": member_hosts, "leader": leader},
    )


def check_talos_services(plan: Plan, snapshot: Snapshot, now: datetime) -> Outcome:
    problems = []
    machines = _for_node(snapshot.get("talos-machinestatus"), plan.address())
    if not machines:
        problems.append(f"Talos on {plan.node} reported no machine status{snapshot.missing('talos-machinestatus')}")
    else:
        spec = machines[0].get("spec") or {}
        status = spec.get("status") or {}
        if spec.get("stage") != "running":
            problems.append(f"machine stage is {spec.get('stage')}, not running")
        if status.get("ready") is not True:
            unmet = "; ".join(
                f"{item.get('name')}: {item.get('reason')}" for item in status.get("unmetConditions") or []
            )
            problems.append("machine is not ready" + (f" ({unmet})" if unmet else ""))
    services = _for_node(snapshot.get("talos-services"), plan.address())
    if not services:
        problems.append(f"Talos on {plan.node} reported no services{snapshot.missing('talos-services')}")
    for service in services:
        name, spec = _meta(service).get("id"), service.get("spec") or {}
        if not spec.get("running"):
            problems.append(f"service {name} is not running")
        elif not spec.get("unknown") and not spec.get("healthy"):
            problems.append(f"service {name} is unhealthy")
    return Outcome(f"machine running and ready; {_plural(len(services), 'service')} running", problems)


def check_control_plane(plan: Plan, snapshot: Snapshot, now: datetime) -> Outcome:
    pods = {_key(pod): pod for pod in _pods_on(snapshot, plan.node)}
    problems, images = [], {}
    for component in CONTROL_PLANE:
        pod = pods.get(f"kube-system/{component}-{plan.node}")
        if pod is None:
            problems.append(f"{component} has no pod on {plan.node}")
            continue
        containers = (pod.get("spec") or {}).get("containers") or [{}]
        images[component] = containers[0].get("image")
        if not pod_ready(pod):
            problems.append(f"{component} on {plan.node} is not Ready ({pod_state(pod)})")
        if plan.phase != "pre" and not str(images[component]).endswith(f":{plan.kubernetes_version}"):
            problems.append(f"{component} runs {images[component]}, expected {plan.kubernetes_version}")
    return Outcome(f"{', '.join(CONTROL_PLANE)} Ready on {plan.node}", problems, {"images": images})


def check_cni_config(plan: Plan, snapshot: Snapshot, now: datetime) -> Outcome:
    entries = {
        row.get("NAME"): row.get("MODE", "")
        for row in snapshot.get("talos-cni-dir")
        if row.get("NAME") not in {".", "..", ""}
    }
    problems = []
    details: dict[str, Any] = {"entries": sorted(entries)}
    mode = entries.pop(MULTUS_CONFIG, None)
    if mode is None:
        problems.append(f"{CNI_DIR}/{MULTUS_CONFIG} is missing; containerd has no CNI config until Multus writes it")
    elif not mode.startswith("-"):
        problems.append(f"{CNI_DIR}/{MULTUS_CONFIG} is not a regular file (mode {mode})")
    for name, entry_mode in sorted(entries.items()):
        if name == "whereabouts.d" and entry_mode.startswith("d"):
            continue
        problems.append(
            f"unexpected {CNI_DIR}/{name}; only {MULTUS_CONFIG} and whereabouts.d belong there, "
            "or containerd can start pods without Multus"
        )
    if mode is not None and mode.startswith("-"):
        config = json.loads(snapshot.get("talos-multus-conf"))
        kind = config.get("type") if isinstance(config, dict) else None
        details.update(multus_type=kind, cluster_network=config.get("clusterNetwork") if isinstance(config, dict) else None)
        if kind != "multus-shim":
            problems.append(f"{MULTUS_CONFIG} has type {kind!r}, expected multus-shim")
    return Outcome(f"{CNI_DIR} holds only {MULTUS_CONFIG} (multus-shim) and whereabouts.d", problems, details)


def check_cni_daemons(plan: Plan, snapshot: Snapshot, now: datetime) -> Outcome:
    pods = _pods_on(snapshot, plan.node)
    problems = []
    for namespace, daemonset in CNI_DAEMONSETS:
        owned = [
            pod for pod in pods
            if _meta(pod).get("namespace") == namespace
            and controller_of(pod) == ("DaemonSet", daemonset)
            and not _meta(pod).get("deletionTimestamp")
        ]
        if not owned:
            problems.append(f"no {namespace}/{daemonset} pod on {plan.node}")
        for pod in owned:
            if not pod_ready(pod):
                problems.append(f"{_key(pod)} on {plan.node} is not Ready ({pod_state(pod)})")
    names = ", ".join(name for _, name in CNI_DAEMONSETS)
    return Outcome(f"{names} Ready on {plan.node}", problems)


def _storage_network(snapshot: Snapshot) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
    attachment = snapshot.get("storage-network")
    config = json.loads((attachment.get("spec") or {}).get("config") or "{}")
    address_range = (config.get("ipam") or {}).get("range")
    if not address_range:
        raise ValueError(f"{STORAGE_NAMESPACE}/{STORAGE_NETWORK} has no IPAM range")
    return ipaddress.ip_network(address_range, strict=False)


def _in_network(address: str, network: ipaddress.IPv4Network | ipaddress.IPv6Network) -> bool:
    try:
        return ipaddress.ip_address(address.split("/")[0]) in network
    except ValueError:
        return False


def check_instance_managers(plan: Plan, snapshot: Snapshot, now: datetime) -> Outcome:
    network = _storage_network(snapshot)
    managers = {_meta(item).get("name"): item for item in snapshot.get("longhorn-instance-managers")}
    pods = [
        pod for pod in snapshot.get("pods")
        if _meta(pod).get("namespace") == STORAGE_NAMESPACE
        and (_meta(pod).get("labels") or {}).get("longhorn.io/component") == "instance-manager"
    ]
    problems, rows, storage_ips, broken = [], [], {}, set()
    for pod in sorted(pods, key=lambda item: _meta(item).get("name") or ""):
        name, node = _meta(pod).get("name"), (pod.get("spec") or {}).get("nodeName")
        status = (managers.get(name) or {}).get("status") or {}
        engines, replicas = len(status.get("instanceEngines") or {}), len(status.get("instanceReplicas") or {})
        serving = f"{_plural(engines, 'engine')}, {_plural(replicas, 'replica')}"
        if not pod_ready(pod):
            problems.append(f"{name} on {node} is not Ready ({pod_state(pod)})")
        statuses, error = network_statuses(pod)
        attachment = next((entry for entry in statuses or [] if entry.get("interface") == STORAGE_INTERFACE), None)
        if attachment is None:
            broken.add(name)
            reason = f"unreadable network-status ({error})" if error else f"no {STORAGE_INTERFACE}"
            problems.append(
                f"{name} on {node} has {reason}: Multus did not attach the storage network ({serving})"
            )
            continue
        addresses = [address for address in attachment.get("ips") or [] if _in_network(address, network)]
        if not addresses:
            broken.add(name)
            problems.append(f"{name} on {node} has {STORAGE_INTERFACE} {attachment.get('ips')} outside {network}")
            continue
        storage_ips[name] = addresses[0]
        rows.append({"pod": name, "node": node, "storage_ip": addresses[0], "engines": engines, "replicas": replicas})
    for node in plan.inventory:
        if not any((pod.get("spec") or {}).get("nodeName") == node for pod in pods):
            problems.append(f"no Longhorn instance manager pod on {node}")
    mismatched: dict[str, set[str]] = defaultdict(set)
    running = 0
    for replica in snapshot.get("longhorn-replicas"):
        status = replica.get("status") or {}
        if status.get("currentState") != "running":
            continue
        running += 1
        manager = status.get("instanceManagerName")
        if manager in broken:
            continue
        if manager not in storage_ips:
            problems.append(f"replica {_meta(replica).get('name')} runs on {manager}, which has no pod")
        elif status.get("storageIP") != storage_ips[manager]:
            mismatched[manager].add(str(status.get("storageIP")))
    for manager, addresses in sorted(mismatched.items()):
        problems.append(
            f"running replicas on {manager} serve on {', '.join(sorted(addresses))}, "
            f"not its storage IP {storage_ips[manager]}"
        )
    return Outcome(
        f"{_plural(len(rows), 'instance manager')} on {len(plan.inventory)} nodes have {STORAGE_INTERFACE} in {network}; "
        f"{_plural(running, 'running replica')} use their storage IPs",
        problems,
        {"storage_network": str(network), "instance_managers": rows},
    )


def check_multus_status(plan: Plan, snapshot: Snapshot, now: datetime) -> Outcome:
    problems, checked = [], 0
    for pod in _pods_on(snapshot, plan.node):
        status = pod.get("status") or {}
        if (
            status.get("phase") != "Running"
            or (pod.get("spec") or {}).get("hostNetwork")
            or _meta(pod).get("deletionTimestamp")
        ):
            continue
        checked += 1
        sandbox = condition(pod, "PodReadyToStartContainers").get("lastTransitionTime") or status.get("startTime")
        key = f"{_key(pod)} (sandbox since {sandbox or 'unknown'})"
        statuses, error = network_statuses(pod)
        if statuses is None:
            problems.append(f"{key} has no network-status: it started without Multus")
            continue
        if error:
            problems.append(f"{key} has unreadable network-status ({error})")
            continue
        default = next((entry for entry in statuses if entry.get("default")), None)
        pod_ips = {entry.get("ip") for entry in status.get("podIPs") or []} | {status.get("podIP")}
        if default is None:
            problems.append(f"{key} network-status has no default network entry")
        elif not pod_ips & set(default.get("ips") or []):
            problems.append(
                f"{key} network-status lists {default.get('ips')}, but the pod IP is {status.get('podIP')}: "
                "its current sandbox started without Multus"
            )
        for network, interface in requested_networks(pod):
            if not any(
                entry.get("name") == network and (interface is None or entry.get("interface") == interface)
                for entry in statuses
            ):
                problems.append(f"{key} requested {network} but Multus did not attach it")
    return Outcome(f"{_plural(checked, 'pod-network pod')} on {plan.node} started through Multus", problems)


def check_longhorn(plan: Plan, snapshot: Snapshot, now: datetime) -> Outcome:
    problems = []
    longhorn_nodes = {_meta(item).get("name"): item for item in snapshot.get("longhorn-nodes")}
    for name in plan.inventory:
        node = longhorn_nodes.get(name)
        if node is None:
            problems.append(f"Longhorn has no node {name}")
            continue
        for kind in ("Ready", "Schedulable"):
            state = condition(node, kind)
            if state.get("status") != "True":
                problems.append(f"Longhorn node {name} is not {kind}: {state.get('reason') or state.get('status')}")
    healthy, detached = 0, []
    for volume in snapshot.get("longhorn-volumes"):
        status = volume.get("status") or {}
        claim = status.get("kubernetesStatus") or {}
        label = _meta(volume).get("name")
        if claim.get("pvcName"):
            label = f"{label} ({claim.get('namespace')}/{claim.get('pvcName')})"
        state, robustness = status.get("state"), status.get("robustness")
        if state == "attached" and robustness == "healthy":
            healthy += 1
        elif state == "detached" and robustness in {"unknown", "healthy"}:
            detached.append(label)
        else:
            problems.append(f"volume {label} is {state}/{robustness}")
    return Outcome(
        f"{healthy} attached volumes healthy, {len(detached)} detached; Longhorn nodes Ready and Schedulable",
        problems,
        {"detached": detached},
    )


def check_seaweedfs(plan: Plan, snapshot: Snapshot, now: datetime) -> Outcome:
    series = snapshot.get("seaweedfs-gauge")
    servers = [
        pod for pod in snapshot.get("pods")
        if _meta(pod).get("namespace") == STORAGE_NAMESPACE
        and (_meta(pod).get("labels") or {}).get("app.kubernetes.io/instance") == "seaweedfs"
        and (_meta(pod).get("labels") or {}).get("app.kubernetes.io/component") == "volume"
    ]
    problems = []
    if not servers:
        problems.append("no SeaweedFS volume server pods")
    reporting = {sample.get("metric", {}).get("pod") for sample in series}
    for pod in servers:
        name = _meta(pod).get("name")
        if not pod_ready(pod):
            problems.append(f"{name} is not Ready ({pod_state(pod)})")
        if name not in reporting:
            problems.append(f"Prometheus has no read-only gauge from {name}, so it cannot show 0")
    for sample in series:
        metric = sample.get("metric") or {}
        value = float((sample.get("value") or [0, "nan"])[1])
        if not math.isfinite(value) or value > 0:
            where = f" in collection {metric['collection']}" if metric.get("collection") else ""
            problems.append(f"{metric.get('pod')} reports {value:g} {metric.get('type')} volumes{where}")
    return Outcome(f"{_plural(len(servers), 'volume server')} report 0 read-only volumes", problems)


def check_pods(plan: Plan, snapshot: Snapshot, now: datetime) -> Outcome:
    problems, settling, tombstones, total = [], [], [], 0
    for pod in snapshot.get("pods"):
        total += 1
        status = pod.get("status") or {}
        if status.get("phase") == "Succeeded" or pod_ready(pod):
            continue
        where = f"{_key(pod)} on {(pod.get('spec') or {}).get('nodeName') or 'no node'}"
        # Failed pods are tombstones their controllers already replaced; the
        # pod-gc CronJob deletes them (ADR 0014). Their replacements are checked.
        if status.get("phase") == "Failed":
            tombstones.append(where)
            continue
        deleting = _meta(pod).get("deletionTimestamp")
        young = _age(_meta(pod).get("creationTimestamp"), now) < SETTLE_SECONDS
        if (deleting and _age(deleting, now) < SETTLE_SECONDS) or (
            not deleting and young and status.get("phase") in {"Pending", "Running"}
        ):
            settling.append(where)
            continue
        problems.append(f"{where} is {pod_state(pod)}")
    notes = [f"{len(settling)} settling"] if settling else []
    notes += [f"{len(tombstones)} Failed left for pod-gc"] if tombstones else []
    return Outcome(
        f"{total - len(settling) - len(tombstones)} pods Running and Ready or Succeeded"
        + (f"; {', '.join(notes)}" if notes else ""),
        problems,
        {"settling": settling, "failed_tombstones": tombstones},
    )


def check_flux(plan: Plan, snapshot: Snapshot, now: datetime) -> Outcome:
    items = snapshot.get("flux")
    problems, ready = [], 0
    for item in items:
        label = f"{item.get('kind')} {_key(item)}"
        generation, observed = _meta(item).get("generation"), (item.get("status") or {}).get("observedGeneration")
        state = condition(item, "Ready")
        if (item.get("spec") or {}).get("suspend"):
            problems.append(f"{label} is suspended")
        elif observed != generation:
            problems.append(f"{label} has not reconciled generation {generation} (observed {observed})")
        elif state.get("status") != "True":
            message = " ".join(str(state.get("message") or "").split())[:200]
            problems.append(f"{label} is not Ready: {state.get('reason')}: {message}")
        else:
            ready += 1
    if not items:
        problems.append("no Flux objects found")
    return Outcome(f"{ready} Flux objects Ready at their current generation", problems)


def check_alerts(plan: Plan, snapshot: Snapshot, now: datetime) -> Outcome:
    alerts = snapshot.get("alerts")
    if not isinstance(alerts, list):
        raise ValueError("Alertmanager did not return a list")
    nodes = _nodes(snapshot)
    by_address = {internal_ip(node): name for name, node in nodes.items()}
    pod_nodes = {
        (_meta(pod).get("namespace"), _meta(pod).get("name")): (pod.get("spec") or {}).get("nodeName")
        for pod in snapshot.get("pods")
    }

    def node_of(labels: Mapping[str, str]) -> str | None:
        if labels.get("node") in nodes:
            return labels["node"]
        host = re.sub(r":\d+$", "", labels.get("instance", ""))
        if host in nodes or host in by_address:
            return host if host in nodes else by_address[host]
        return pod_nodes.get((labels.get("namespace"), labels.get("pod")))

    problems, accepted, expected, muted = [], [], [], []
    if not any((alert.get("labels") or {}).get("alertname") == "Watchdog" for alert in alerts):
        problems.append("Watchdog is not active, so Prometheus is not delivering alerts and an empty list proves nothing")
    for alert in alerts:
        labels = alert.get("labels") or {}
        name = labels.get("alertname")
        if name in ALWAYS_ACTIVE_ALERTS:
            continue
        node = node_of(labels)
        where = node or "/".join(filter(None, (labels.get("namespace"), labels.get("pod")))) or labels.get("instance") or "cluster"
        entry = f"{name} ({labels.get('severity', 'none')}) on {where}"
        if (alert.get("status") or {}).get("state") == "suppressed":
            muted.append(entry)
        elif name in plan.accepted_alerts:
            accepted.append(entry)
        elif name in REBOOT_ALERTS and node in plan.reboot_expected:
            expected.append(entry)
        else:
            summary = " ".join(str((alert.get("annotations") or {}).get("summary") or "").split())[:160]
            problems.append(entry + (f": {summary}" if summary else ""))
    notes = [f"{label}: {len(values)}" for label, values in (
        ("accepted", accepted), ("expected after reboot", expected), ("silenced or inhibited", muted)
    ) if values]
    return Outcome(
        "no unexpected firing alerts" + (f" ({'; '.join(notes)})" if notes else ""),
        problems,
        {"accepted": accepted, "expected_after_reboot": expected, "silenced_or_inhibited": muted},
    )


def _longhorn_instance_manager_budget(budget: Mapping[str, Any]) -> bool:
    labels = ((budget.get("spec") or {}).get("selector") or {}).get("matchLabels") or {}
    return _meta(budget).get("namespace") == STORAGE_NAMESPACE and labels.get("longhorn.io/component") == "instance-manager"


def _cnpg_primary_owner(budget: Mapping[str, Any]) -> str | None:
    labels = ((budget.get("spec") or {}).get("selector") or {}).get("matchLabels") or {}
    if labels.get("cnpg.io/instanceRole") != "primary":
        return None
    for owner in _meta(budget).get("ownerReferences") or []:
        if owner.get("kind") == "Cluster" and str(owner.get("apiVersion", "")).startswith("postgresql.cnpg.io/"):
            return owner.get("name")
    return None


def check_disruption_budgets(plan: Plan, snapshot: Snapshot, now: datetime) -> Outcome:
    budgets, pods = snapshot.get("pdbs"), snapshot.get("pods")
    problems, gating, released = [], [], []
    for budget in budgets:
        key, spec, status = _key(budget), budget.get("spec") or {}, budget.get("status") or {}
        if (status.get("observedGeneration") or 0) < (_meta(budget).get("generation") or 0):
            problems.append(f"{key} status has not observed its current generation")
            continue
        healthy, desired = status.get("currentHealthy", 0), status.get("desiredHealthy", 0)
        if healthy < desired:
            problems.append(f"{key} has {healthy} healthy pods, below its minimum of {desired}")
            continue
        if plan.phase != "pre":
            continue
        covered = sorted(
            _meta(pod).get("name") for pod in pods
            if _meta(pod).get("namespace") == _meta(budget).get("namespace")
            and (pod.get("spec") or {}).get("nodeName") == plan.node
            and (pod.get("status") or {}).get("phase") not in {"Succeeded", "Failed"}
            and selector_matches(spec.get("selector"), _meta(pod).get("labels") or {})
        )
        if not covered:
            continue
        allowed = status.get("disruptionsAllowed", 0)
        if allowed >= 1:
            gating.append(f"{key} allows {allowed} for {', '.join(covered)}")
        elif _longhorn_instance_manager_budget(budget):
            released.append(f"{key}: Longhorn releases it after cordon while every volume has a healthy replica elsewhere")
        elif (owner := _cnpg_primary_owner(budget)) is not None:
            clusters = {_key(item): item for item in snapshot.get("cnpg-clusters")}
            cluster = clusters.get(f"{_meta(budget).get('namespace')}/{owner}") or {}
            instances = (cluster.get("spec") or {}).get("instances") or 0
            ready = (cluster.get("status") or {}).get("readyInstances") or 0
            if instances >= 2 and ready == instances:
                released.append(f"{key}: CloudNativePG switches {', '.join(covered)} to a ready standby after cordon")
            else:
                problems.append(
                    f"{key} protects primary {', '.join(covered)} on {plan.node}, but cluster {owner} has "
                    f"{ready}/{instances} instances ready, so no standby can take over"
                )
        else:
            problems.append(f"{key} allows 0 disruptions and covers {', '.join(covered)} on {plan.node}; the drain would block")
    if plan.phase == "pre":
        summary = f"{_plural(len(gating), 'budget')} on {plan.node} allow the drain; {len(released)} released by their controllers"
    else:
        summary = f"{_plural(len(budgets), 'budget')} at or above their healthy minimum"
    return Outcome(summary, problems, {"allows_drain": gating, "released_by_controller": released})


@dataclass(frozen=True)
class CheckSpec:
    id: str
    title: str
    sources: tuple[str, ...]
    evaluate: Callable[[Plan, Snapshot, datetime], Outcome]


CHECKS = (
    CheckSpec("identity", "Target identity", ("nodes", "talos-nodenames"), check_identity),
    CheckSpec("nodes", "Kubernetes nodes", ("nodes",), check_nodes),
    CheckSpec("versions", "Talos and Kubernetes versions", ("nodes", "talos-version"), check_versions),
    CheckSpec(
        "etcd", "etcd quorum", ("talos-etcd-services", "talos-etcd-members", "talos-etcd-status"), check_etcd
    ),
    CheckSpec("talos-services", "Talos services", ("talos-services", "talos-machinestatus"), check_talos_services),
    CheckSpec("control-plane", "Control-plane pods", ("pods",), check_control_plane),
    CheckSpec("cni-config", "CNI config", ("talos-cni-dir", "talos-multus-conf"), check_cni_config),
    CheckSpec("cni-daemons", "CNI daemons", ("pods",), check_cni_daemons),
    CheckSpec(
        "instance-managers",
        "Longhorn instance managers",
        ("pods", "longhorn-replicas", "longhorn-instance-managers", "storage-network"),
        check_instance_managers,
    ),
    CheckSpec("multus-status", "Multus network-status", ("pods",), check_multus_status),
    CheckSpec("longhorn", "Longhorn volumes", ("longhorn-volumes", "longhorn-nodes"), check_longhorn),
    CheckSpec("seaweedfs", "SeaweedFS read-only volumes", ("seaweedfs-gauge", "pods"), check_seaweedfs),
    CheckSpec("pods", "Pod health", ("pods",), check_pods),
    CheckSpec("flux", "Flux", ("flux",), check_flux),
    CheckSpec("alerts", "Firing alerts", ("alerts", "pods", "nodes"), check_alerts),
    CheckSpec("disruption-budgets", "Disruption budgets", ("pdbs", "pods", "cnpg-clusters"), check_disruption_budgets),
)

NODE_CHECKS = (
    "identity", "nodes", "versions", "etcd", "talos-services", "control-plane",
    "cni-config", "cni-daemons", "instance-managers",
)
CLUSTER_CHECKS = ("longhorn", "seaweedfs", "pods", "flux", "alerts", "disruption-budgets")
# Pods that bypassed Multus before the node's last boot are recreated by the
# drain and reboot, so multus-status gates only the boot that just happened.
PHASE_CHECKS = {
    "pre": NODE_CHECKS + CLUSTER_CHECKS,
    "return": NODE_CHECKS + ("multus-status",),
    "post": NODE_CHECKS + ("multus-status",) + CLUSTER_CHECKS,
}


def checks_for(phase: str) -> tuple[CheckSpec, ...]:
    wanted = PHASE_CHECKS[phase]
    by_id = {spec.id: spec for spec in CHECKS}
    return tuple(by_id[check_id] for check_id in wanted)


def evaluate(plan: Plan, snapshot: Snapshot, now: datetime) -> list[CheckResult]:
    results = []
    for spec in checks_for(plan.phase):
        try:
            outcome = spec.evaluate(plan, snapshot, now)
        except Unavailable as missing:
            outcome = Outcome(str(missing), [str(missing)])
        except (KeyError, TypeError, ValueError, AttributeError, IndexError) as error:
            outcome = Outcome("", [f"unexpected data shape ({type(error).__name__}: {error})"])
        problems = tuple(redact(problem) for problem in outcome.problems)
        if problems:
            summary = problems[0] if len(problems) == 1 else f"{len(problems)} problems"
        else:
            summary = outcome.summary
        results.append(
            CheckResult(spec.id, spec.title, "FAIL" if problems else "PASS", redact(summary), problems, redact(outcome.details))
        )
    return results


# --- Run -------------------------------------------------------------------

@dataclass(frozen=True)
class GateRun:
    plan: Plan
    results: tuple[CheckResult, ...]
    attempts: int
    started: datetime
    finished: datetime
    talos_endpoint: str | None

    @property
    def passed(self) -> bool:
        return all(result.status == "PASS" for result in self.results)


def gate(
    plan: Plan,
    *,
    runner: Runner,
    context: str,
    talosconfig: str,
    endpoints: Sequence[tuple[str, str]],
    wait: float = 0.0,
    interval: float = 20.0,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    progress: Callable[[str], None] | None = None,
) -> GateRun:
    """Collect and evaluate until every check passes or ``wait`` seconds pass."""
    needed = {source for spec in checks_for(plan.phase) for source in spec.sources}
    started, deadline, attempts = now(), clock() + wait, 0
    while True:
        attempts += 1
        snapshot = collect(
            plan, needed, runner=runner, context=context, talosconfig=talosconfig, endpoints=endpoints
        )
        results = evaluate(plan, snapshot, now())
        failed = [result.id for result in results if result.status != "PASS"]
        remaining = deadline - clock()
        if not failed or remaining <= 0:
            return GateRun(plan, tuple(results), attempts, started, now(), snapshot.talos_endpoint)
        if progress:
            progress(f"attempt {attempts}: FAIL {', '.join(failed)}; retrying for up to {remaining:.0f}s")
        sleep(min(interval, remaining))


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def report(run: GateRun, *, context: str, target_source: str | None = None) -> dict[str, Any]:
    plan = run.plan
    return redact({
        "schema": 1,
        "tool": "node-gate",
        "node": plan.node,
        "phase": plan.phase,
        "verdict": "PASS" if run.passed else "FAIL",
        "started_at": _iso(run.started),
        "finished_at": _iso(run.finished),
        "attempts": run.attempts,
        "expected": {"talos": plan.talos_version, "kubernetes": plan.kubernetes_version},
        "kube_context": context,
        "talos_endpoint": run.talos_endpoint,
        "talos_target_source": target_source,
        "rebooted_nodes": sorted(plan.reboot_expected),
        "accepted_alerts": sorted(plan.accepted_alerts),
        "checks": [
            {
                "id": result.id,
                "title": result.title,
                "status": result.status,
                "summary": result.summary,
                "problems": list(result.problems),
                "details": dict(result.details),
            }
            for result in run.results
        ],
    })


def render(run: GateRun) -> str:
    plan = run.plan
    width = max(len(result.id) for result in run.results)
    lines = [
        f"node-gate {plan.phase} {plan.node}: expect Talos {plan.talos_version}, "
        f"Kubernetes {plan.kubernetes_version}"
    ]
    for result in run.results:
        lines.append(f"{result.status}  {result.id:<{width}}  {result.summary}")
        if len(result.problems) > 1:
            lines.extend(f"      - {problem}" for problem in result.problems[:MAX_PRINTED_PROBLEMS])
            if len(result.problems) > MAX_PRINTED_PROBLEMS:
                lines.append(f"      - and {len(result.problems) - MAX_PRINTED_PROBLEMS} more in the JSON report")
    failed = [result.id for result in run.results if result.status != "PASS"]
    passed = len(run.results) - len(failed)
    attempts = _plural(run.attempts, "attempt")
    if failed:
        lines.append(
            f"NODE GATE FAIL {plan.node} phase={plan.phase}: {', '.join(failed)} "
            f"({passed}/{len(run.results)} checks passed, {attempts})"
        )
    else:
        lines.append(f"NODE GATE PASS {plan.node} phase={plan.phase} ({passed}/{len(run.results)} checks, {attempts})")
    return redact("\n".join(lines))


def write_report(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
