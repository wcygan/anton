"""Resolve Anton targets and classify cluster command preflight requirements."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping


RunStdout = Callable[[list[str]], str | None]


@dataclass(frozen=True)
class NodeTarget:
    name: str
    address: str


@dataclass(frozen=True)
class TargetResolution:
    nodes: tuple[NodeTarget, ...]
    source: str
    fallback_reason: str | None = None

    def mapping(self) -> str:
        return ",".join(f"{node.name}={node.address}" for node in self.nodes)

    def addresses(self) -> str:
        return ",".join(node.address for node in self.nodes)

    def evidence(self, *, show_addresses: bool = False) -> dict:
        return {
            "source": self.source,
            "fallback_reason": self.fallback_reason,
            "nodes": [
                {"name": node.name, "address": node.address if show_addresses else "<redacted>"}
                for node in self.nodes
            ],
        }


@dataclass(frozen=True)
class CommandOperation:
    binary: str
    subcommand: str | None
    classification: str


@dataclass(frozen=True)
class PreflightViolation:
    binary: str
    subcommand: str | None
    actual: str | None
    expected: str
    message: str


READ_ONLY_KUBECTL = frozenset(
    {
        "get",
        "describe",
        "logs",
        "top",
        "explain",
        "api-resources",
        "api-versions",
        "version",
        "cluster-info",
        "auth",
        "events",
        "wait",
        "diff",
        "kustomize",
    }
)
READ_ONLY_KUBECTL_CONFIG = frozenset(
    {"current-context", "view", "get-contexts", "get-clusters", "get-users"}
)
READ_ONLY_KUBECTL_AUTH = frozenset({"can-i", "whoami"})
READ_ONLY_TALOSCTL = frozenset(
    {
        "get",
        "read",
        "list",
        "ls",
        "containers",
        "dmesg",
        "health",
        "logs",
        "memory",
        "processes",
        "ps",
        "service",
        "services",
        "stats",
        "time",
        "version",
        "disks",
        "dashboard",
        "inspect",
        "interfaces",
        "pcap",
        "meta",
        "netstat",
        "support",
    }
)
READ_ONLY_TALOSCTL_CONFIG = frozenset({"info"})
READ_ONLY_FLUX = frozenset(
    {"get", "stats", "version", "check", "tree", "trace", "events", "logs", "diff", "envsubst", "completion"}
)

FLAGS_WITH_ARG = frozenset(
    {
        "-n",
        "--namespace",
        "-o",
        "--output",
        "-l",
        "--selector",
        "-f",
        "--filename",
        "-c",
        "--container",
        "-s",
        "--server",
        "-p",
        "--patch",
        "-e",
        "--endpoints",
        "--context",
        "--kubeconfig",
        "--cluster",
        "--user",
        "--talosconfig",
        "--nodes",
    }
)


def load_inventory(root: Path) -> dict:
    path = root / "scripts" / "cluster-targets.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != 1:
        raise ValueError(f"unsupported cluster target schema in {path}")
    return data


def _validated_nodes(nodes: list[dict]) -> tuple[NodeTarget, ...]:
    result: list[NodeTarget] = []
    names: set[str] = set()
    for node in nodes:
        name = str(node.get("name", ""))
        address = str(node.get("tailscale_ipv4", ""))
        if not name or name in names:
            raise ValueError("cluster targets require unique non-empty node names")
        parsed = ipaddress.ip_address(address)
        if parsed.version != 4:
            raise ValueError(f"target {name} must use an IPv4 address")
        names.add(name)
        result.append(NodeTarget(name, address))
    if not result:
        raise ValueError("cluster targets require at least one node")
    return tuple(result)


def parse_mapping(value: str, expected_names: tuple[str, ...]) -> tuple[NodeTarget, ...]:
    raw_nodes: list[dict[str, str]] = []
    for item in value.split(","):
        name, separator, address = item.partition("=")
        if not separator:
            raise ValueError(f"invalid node mapping {item!r}")
        raw_nodes.append({"name": name.strip(), "tailscale_ipv4": address.strip()})
    nodes = _validated_nodes(raw_nodes)
    if tuple(node.name for node in nodes) != expected_names:
        raise ValueError(f"node mapping must contain {', '.join(expected_names)} in order")
    return nodes


def run_stdout(command: list[str]) -> str | None:
    if not shutil.which(command[0]):
        return None
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _tailscale_status(runner: RunStdout) -> dict | None:
    output = runner(["tailscale", "status", "--json"])
    if output is None:
        return None
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _live_nodes(status: dict, expected_names: tuple[str, ...]) -> tuple[NodeTarget, ...] | None:
    peers: list[dict] = []
    if isinstance(status.get("Self"), dict):
        peers.append(status["Self"])
    if isinstance(status.get("Peer"), dict):
        peers.extend(value for value in status["Peer"].values() if isinstance(value, dict))

    discovered: dict[str, str] = {}
    for peer in peers:
        hostname = str(peer.get("HostName") or peer.get("DNSName") or "").rstrip(".").split(".", 1)[0]
        addresses = peer.get("TailscaleIPs")
        if hostname not in expected_names or not isinstance(addresses, list):
            continue
        for address in addresses:
            try:
                parsed = ipaddress.ip_address(str(address))
            except ValueError:
                continue
            if parsed.version == 4:
                discovered[hostname] = str(parsed)
                break
    if set(discovered) != set(expected_names):
        return None
    return tuple(NodeTarget(name, discovered[name]) for name in expected_names)


def resolve_talos_targets(
    root: Path,
    *,
    source: str = "auto",
    environ: Mapping[str, str] | None = None,
    runner: RunStdout = run_stdout,
) -> TargetResolution:
    if source not in {"auto", "live", "fallback"}:
        raise ValueError(f"unsupported target source {source!r}")
    environment = os.environ if environ is None else environ
    inventory = load_inventory(root)
    fallback = _validated_nodes(inventory["talos"]["nodes"])
    expected_names = tuple(node.name for node in fallback)

    override = environment.get("TALOS_TAILSCALE_NODES", "").strip()
    if override:
        return TargetResolution(parse_mapping(override, expected_names), "override")
    if source == "fallback":
        return TargetResolution(fallback, "fallback")

    status = _tailscale_status(runner)
    live = _live_nodes(status, expected_names) if status else None
    if live:
        return TargetResolution(live, "live")
    if source == "live":
        raise ValueError("live Tailscale status did not resolve every Anton node")
    reason = "tailscale status unavailable" if status is None else "live node set incomplete"
    return TargetResolution(fallback, "fallback", reason)


def expected_kube_context(
    root: Path,
    *,
    environ: Mapping[str, str] | None = None,
    runner: RunStdout = run_stdout,
) -> str:
    environment = os.environ if environ is None else environ
    override = environment.get("ANTON_KUBE_CONTEXT", "").strip()
    if override:
        return override
    inventory = load_inventory(root)
    status = _tailscale_status(runner)
    suffix = str(status.get("MagicDNSSuffix", "")).strip() if status else ""
    if suffix:
        return f"{inventory['kubernetes']['operator_context_prefix']}{suffix}"
    return str(inventory["kubernetes"]["fallback_context"])


def expected_talos_context(root: Path, *, environ: Mapping[str, str] | None = None) -> str:
    environment = os.environ if environ is None else environ
    return environment.get("ANTON_TALOS_CONTEXT", "").strip() or str(load_inventory(root)["talos"]["context"])


def _strip_wrappers(tokens: list[str]) -> list[str]:
    while tokens and "=" in tokens[0] and not tokens[0].startswith("-"):
        tokens = tokens[1:]
    if tokens[:3] == ["mise", "exec", "--"]:
        tokens = tokens[3:]
    return tokens


def _subcommands(tokens: list[str]) -> list[str]:
    result: list[str] = []
    skip_next = False
    for token in tokens:
        if skip_next:
            skip_next = False
            continue
        if token.startswith("-"):
            if token in FLAGS_WITH_ARG:
                skip_next = True
            continue
        if "=" in token:
            continue
        result.append(token)
    return result


def _shell_segments(command: str) -> tuple[str, ...]:
    """Split shell control operators while preserving quoted operator text."""
    segments: list[str] = []
    current: list[str] = []
    quote: str | None = None
    escaped = False
    for character in command:
        if escaped:
            current.append(character)
            escaped = False
            continue
        if character == "\\" and quote != "'":
            current.append(character)
            escaped = True
            continue
        if character in {"'", '"'}:
            if quote is None:
                quote = character
            elif quote == character:
                quote = None
            current.append(character)
            continue
        if quote is None and character in ";|&\n":
            segment = "".join(current).strip()
            if segment:
                segments.append(segment)
            current = []
            continue
        current.append(character)
    segment = "".join(current).strip()
    if segment:
        segments.append(segment)
    return tuple(segments)


def classify_command(command: str) -> tuple[CommandOperation, ...]:
    operations: list[CommandOperation] = []
    for segment in _shell_segments(command):
        try:
            tokens = _strip_wrappers(shlex.split(segment))
        except ValueError:
            continue
        if not tokens:
            continue
        binary = Path(tokens[0]).name
        if binary not in {"kubectl", "talosctl", "flux"}:
            continue
        commands = _subcommands(tokens[1:])
        subcommand = commands[0] if commands else None
        classification = "cluster-mutation"
        if binary == "kubectl":
            if subcommand == "config":
                nested = commands[1] if len(commands) > 1 else None
                classification = "read" if nested in READ_ONLY_KUBECTL_CONFIG else "local-mutation"
            elif subcommand == "auth":
                nested = commands[1] if len(commands) > 1 else None
                classification = "read" if nested in READ_ONLY_KUBECTL_AUTH else "cluster-mutation"
            elif subcommand in READ_ONLY_KUBECTL:
                classification = "read"
        elif binary == "talosctl":
            if subcommand == "config":
                nested = commands[1] if len(commands) > 1 else None
                classification = "read" if nested in READ_ONLY_TALOSCTL_CONFIG else "local-mutation"
            elif subcommand in READ_ONLY_TALOSCTL:
                classification = "read"
        elif binary == "flux" and subcommand in READ_ONLY_FLUX:
            classification = "read"
        operations.append(CommandOperation(binary, subcommand, classification))
    return tuple(operations)


def _talos_context(output: str | None) -> str | None:
    if output is None:
        return None
    for line in output.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip().lower() == "context":
            return value.strip()
    return None


def preflight_command(
    command: str,
    root: Path,
    *,
    environ: Mapping[str, str] | None = None,
    runner: RunStdout = run_stdout,
) -> list[PreflightViolation]:
    violations: list[PreflightViolation] = []
    for operation in classify_command(command):
        if operation.classification != "cluster-mutation":
            continue
        if operation.binary in {"kubectl", "flux"}:
            expected = expected_kube_context(root, environ=environ, runner=runner)
            actual = runner(["kubectl", "config", "current-context"])
        else:
            expected = expected_talos_context(root, environ=environ)
            actual = _talos_context(runner(["talosctl", "config", "info"]))
        if actual is None:
            violations.append(
                PreflightViolation(
                    operation.binary,
                    operation.subcommand,
                    None,
                    expected,
                    "cannot resolve current context for a cluster mutation",
                )
            )
        elif actual != expected:
            violations.append(
                PreflightViolation(
                    operation.binary,
                    operation.subcommand,
                    actual,
                    expected,
                    "current context does not match the Anton target",
                )
            )
    return violations
