"""Resolve Anton targets and classify cluster command preflight requirements."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import urlsplit


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
    executable: str = ""
    arguments: tuple[str, ...] = ()
    positionals: tuple[str, ...] = ()
    context: str | None = None
    config_path: str | None = None
    server: str | None = None
    cluster: str | None = None
    endpoints: tuple[str, ...] = ()
    nodes: tuple[str, ...] = ()
    execution_prefix: tuple[str, ...] = ()
    indirect: bool = False
    ambiguity: str | None = None


@dataclass(frozen=True)
class PreflightViolation:
    binary: str
    subcommand: str | None
    actual: str | None
    expected: str
    message: str


class TargetPreflightError(ValueError):
    """The selected Kubernetes target cannot be proved as Anton."""


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
        "--as",
        "--as-group",
        "--as-uid",
        "--as-user-extra",
        "--cache-dir",
        "--certificate-authority",
        "--client-certificate",
        "--client-key",
        "--kube-api-burst",
        "--kube-api-qps",
        "--kuberc",
        "--log-flush-frequency",
        "--mode",
        "--password",
        "--profile",
        "--profile-output",
        "--progress",
        "--request-timeout",
        "--siderov1-keys-dir",
        "--system-labels-to-wipe",
        "--timeout",
        "--tls-server-name",
        "--token",
        "--user-disks-to-wipe",
        "--username",
        "--v",
        "--vmodule",
        "--wipe-mode",
        "--drain-timeout",
        "-m",
        "-v",
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

SHELL_BINARIES = frozenset({"bash", "sh", "zsh"})
EVAL_BINARIES = frozenset({"eval"})
INDIRECT_BINARIES = frozenset({"sudo", "xargs", "parallel"})
DIRECT_WRAPPERS = frozenset(
    {"env", "command", "mise", "exec", "nohup", "nice", "timeout", "time"}
)
CLUSTER_BINARIES = frozenset({"kubectl", "talosctl", "flux"})
POLICY_BINARIES = frozenset({"task", "helmfile", "rm"})
GUARDED_BINARIES = CLUSTER_BINARIES | POLICY_BINARIES
SHELL_STATE_BINARIES = frozenset({"cd", "pushd", "popd", "export", "unset"})
TARGET_ENVIRONMENT = frozenset(
    {"KUBECONFIG", "TALOSCONFIG", "MISE_CONFIG_FILE", "MISE_CONFIG_DIR", "MISE_PROJECT_ROOT"}
)
EFFECTIVE_TARGET_ENVIRONMENT = TARGET_ENVIRONMENT | frozenset(
    {"HOME", "PATH", "KUBERNETES_MASTER", "XDG_CONFIG_HOME"}
)
SHELL_BOUNDARIES = frozenset(
    {
        "{",
        "}",
        ")",
        "if",
        "then",
        "elif",
        "else",
        "fi",
        "while",
        "until",
        "for",
        "select",
        "case",
        "in",
        "esac",
        "do",
        "done",
        "function",
        "coproc",
        "!",
    }
)
KUBE_SERVER_JSONPATH = "jsonpath={.clusters[0].cluster.server}"
TAILSCALE_EXECUTABLES = (
    "tailscale",
    "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
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
    for executable in TAILSCALE_EXECUTABLES:
        output = runner([executable, "status", "--json"])
        if output is None:
            continue
        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


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
    operator_prefix = str(inventory["kubernetes"]["operator_context_prefix"])
    fallback_context = str(inventory["kubernetes"]["fallback_context"])
    status = _tailscale_status(runner)
    suffix = str(status.get("MagicDNSSuffix", "")).strip() if status else ""
    if suffix:
        return f"{operator_prefix}{suffix}"
    return fallback_context


def expected_kube_endpoint(
    root: Path,
    expected_context: str,
    *,
    environ: Mapping[str, str] | None = None,
    runner: RunStdout = run_stdout,
) -> str | None:
    """Return an independently committed or operator-derived API endpoint."""
    environment = os.environ if environ is None else environ
    override = environment.get("ANTON_KUBE_ENDPOINT", "").strip()
    if override:
        return override

    kubernetes = load_inventory(root)["kubernetes"]
    operator_prefix = str(kubernetes["operator_context_prefix"])
    if expected_context.startswith(operator_prefix):
        return f"https://{expected_context}"
    if expected_context != str(kubernetes["fallback_context"]):
        return None

    source = (root / "talos" / "talconfig.yaml").read_text(encoding="utf-8")
    match = re.search(r'(?m)^endpoint:\s*["\']?([^"\'\s]+)', source)
    return match.group(1) if match else None


def anton_kubectl_prefix(
    root: Path,
    *,
    environ: Mapping[str, str] | None = None,
    runner: RunStdout = run_stdout,
) -> tuple[str, ...]:
    """Return a kubectl prefix bound to the verified Anton target."""

    environment = os.environ if environ is None else environ
    canonical = str(root / "kubeconfig")
    try:
        expected = expected_kube_context(root, environ=environment, runner=runner)
        expected_endpoint = expected_kube_endpoint(
            root,
            expected,
            environ=environment,
            runner=runner,
        )
    except (OSError, ValueError) as error:
        raise TargetPreflightError(
            "Anton target preflight failed: cannot resolve Kubernetes context"
        ) from error

    actual = runner(
        [
            "mise",
            "exec",
            "--",
            "kubectl",
            "--kubeconfig",
            canonical,
            "config",
            "current-context",
        ]
    )
    if actual is None:
        raise TargetPreflightError(
            "Anton target preflight failed: cannot resolve Kubernetes context"
        )
    if actual != expected:
        raise TargetPreflightError(
            "Anton target preflight failed: Kubernetes context is not the Anton target"
        )

    actual_endpoint = runner(
        [
            "mise",
            "exec",
            "--",
            "kubectl",
            "--kubeconfig",
            canonical,
            "--context",
            expected,
            "config",
            "view",
            "--minify",
            "-o",
            KUBE_SERVER_JSONPATH,
        ]
    )
    if not _same_endpoint(actual_endpoint, expected_endpoint):
        raise TargetPreflightError(
            "Anton target preflight failed: Kubernetes endpoint is not the Anton target"
        )
    return (
        "mise",
        "exec",
        "--",
        "kubectl",
        "--kubeconfig",
        canonical,
        "--context",
        expected,
    )


def expected_talos_context(root: Path, *, environ: Mapping[str, str] | None = None) -> str:
    environment = os.environ if environ is None else environ
    return environment.get("ANTON_TALOS_CONTEXT", "").strip() or str(load_inventory(root)["talos"]["context"])


def expected_talos_cluster(root: Path) -> str:
    return str(load_inventory(root)["talos"]["cluster"])


def _assignment(token: str) -> tuple[str, str] | None:
    name, separator, value = token.partition("=")
    if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        return None
    return name, value


def _unwrap_direct(
    tokens: list[str],
) -> tuple[list[str], dict[str, str], bool, frozenset[str], tuple[str, ...]]:
    """Remove execution-preserving wrappers and retain target env overrides."""
    environment: dict[str, str] = {}
    environment_cleared = False
    unset: set[str] = set()
    execution_prefix: list[str] = []
    while tokens:
        consumed = False
        while tokens:
            assignment = _assignment(tokens[0])
            if assignment is None:
                break
            name, value = assignment
            environment[name] = value
            unset.discard(name)
            tokens = tokens[1:]
            consumed = True

        binary = Path(tokens[0]).name if tokens else ""
        if binary == "mise":
            exec_index = next(
                (
                    index
                    for index, token in enumerate(tokens[1:], start=1)
                    if token == "exec"
                    and index + 1 < len(tokens)
                    and tokens[index + 1] == "--"
                ),
                None,
            )
            if exec_index is not None:
                execution_prefix.extend(tokens[: exec_index + 2])
                tokens = tokens[exec_index + 2 :]
                consumed = True
                continue

        if binary == "env":
            tokens = tokens[1:]
            while tokens:
                option = tokens[0]
                if option in {"-i", "--ignore-environment"}:
                    environment.clear()
                    unset.clear()
                    environment_cleared = True
                    tokens = tokens[1:]
                elif len(tokens) >= 2 and option in {"-u", "--unset"}:
                    name = tokens[1]
                    environment.pop(name, None)
                    unset.add(name)
                    tokens = tokens[2:]
                elif option.startswith("--unset="):
                    name = option.partition("=")[2]
                    environment.pop(name, None)
                    unset.add(name)
                    tokens = tokens[1:]
                elif len(tokens) >= 2 and option in {"-C", "--chdir", "-P"}:
                    environment_cleared = True
                    tokens = tokens[2:]
                elif option.startswith("--chdir="):
                    environment_cleared = True
                    tokens = tokens[1:]
                elif len(tokens) >= 2 and option in {"-S", "--split-string"}:
                    environment_cleared = True
                    tokens = [*_shell_tokens(tokens[1]), *tokens[2:]]
                elif re.fullmatch(r"-[iv]*S.+", option) is not None:
                    environment_cleared = True
                    split_value = option[option.index("S") + 1 :]
                    tokens = [*_shell_tokens(split_value), *tokens[1:]]
                elif option.startswith("--split-string="):
                    environment_cleared = True
                    tokens = [*_shell_tokens(option.partition("=")[2]), *tokens[1:]]
                elif option in {"-v", "--debug"}:
                    tokens = tokens[1:]
                elif option == "--":
                    tokens = tokens[1:]
                    break
                elif option.startswith("-"):
                    nested_index = next(
                        (
                            index
                            for index, token in enumerate(tokens[1:], start=1)
                            if Path(token).name
                            in GUARDED_BINARIES | SHELL_BINARIES | DIRECT_WRAPPERS
                        ),
                        None,
                    )
                    if nested_index is None:
                        return [], environment, True, frozenset(unset), tuple(execution_prefix)
                    environment_cleared = True
                    tokens = tokens[nested_index:]
                    break
                else:
                    break
            consumed = True
            continue

        if binary == "command":
            tokens = tokens[1:]
            if tokens and tokens[0] in {"-v", "-V"}:
                return [], environment, environment_cleared, frozenset(unset), tuple(execution_prefix)
            while tokens and tokens[0] == "-p":
                environment_cleared = True
                tokens = tokens[1:]
            if tokens and tokens[0] == "--":
                tokens = tokens[1:]
            consumed = True
            continue

        if binary == "exec":
            tokens = tokens[1:]
            while tokens:
                if tokens[0] == "-c":
                    environment_cleared = True
                    tokens = tokens[1:]
                elif len(tokens) >= 2 and tokens[0] == "-a":
                    tokens = tokens[2:]
                elif tokens[0] in {"-l", "--"}:
                    tokens = tokens[1:]
                else:
                    break
            consumed = True
            continue

        if binary == "nohup":
            tokens = tokens[1:]
            if tokens and tokens[0] == "--":
                tokens = tokens[1:]
            consumed = True
            continue

        if binary == "nice":
            tokens = tokens[1:]
            if len(tokens) >= 2 and tokens[0] in {"-n", "--adjustment"}:
                tokens = tokens[2:]
            elif tokens and (
                tokens[0].startswith("--adjustment=")
                or re.fullmatch(r"-n?-?\d+", tokens[0]) is not None
            ):
                tokens = tokens[1:]
            if tokens and tokens[0] == "--":
                tokens = tokens[1:]
            consumed = True
            continue

        if binary == "timeout":
            tokens = tokens[1:]
            while tokens:
                if len(tokens) >= 2 and tokens[0] in {"-k", "--kill-after", "-s", "--signal"}:
                    tokens = tokens[2:]
                elif re.fullmatch(r"-[ks].+", tokens[0]) is not None:
                    tokens = tokens[1:]
                elif tokens[0].startswith(("--kill-after=", "--signal=")):
                    tokens = tokens[1:]
                elif tokens[0] in {
                    "-f",
                    "-p",
                    "-v",
                    "--foreground",
                    "--preserve-status",
                    "--verbose",
                }:
                    tokens = tokens[1:]
                elif tokens[0] == "--":
                    tokens = tokens[1:]
                    break
                else:
                    break
            if tokens:
                tokens = tokens[1:]
            consumed = True
            continue

        if binary == "time":
            tokens = tokens[1:]
            while tokens:
                if len(tokens) >= 2 and tokens[0] in {"-o", "--output", "-f", "--format"}:
                    tokens = tokens[2:]
                elif tokens[0].startswith(("--output=", "--format=")):
                    tokens = tokens[1:]
                elif tokens[0].startswith("-") and tokens[0] != "--":
                    tokens = tokens[1:]
                elif tokens[0] == "--":
                    tokens = tokens[1:]
                    break
                else:
                    break
            consumed = True
            continue

        if not consumed:
            break
    return tokens, environment, environment_cleared, frozenset(unset), tuple(execution_prefix)


def _option_occurrences(tokens: list[str], *names: str) -> tuple[str, ...]:
    values: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        matched = False
        for name in names:
            if token == name:
                if index + 1 < len(tokens):
                    values.append(tokens[index + 1])
                    index += 1
                matched = True
                break
            prefix = f"{name}="
            if token.startswith(prefix):
                values.append(token[len(prefix) :])
                matched = True
                break
            if len(name) == 2 and token.startswith(name) and len(token) > 2:
                values.append(token[2:])
                matched = True
                break
        index += 1
    return tuple(values)


def _option_value(tokens: list[str], *names: str) -> str | None:
    values = _option_occurrences(tokens, *names)
    return values[-1] if values else None


def _option_values(tokens: list[str], *names: str) -> tuple[str, ...]:
    values: list[str] = []
    for occurrence in _option_occurrences(tokens, *names):
        for item in occurrence.split(","):
            item = item.strip()
            if item and item not in values:
                values.append(item)
    return tuple(values)


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


def _shell_tokens(command: str) -> tuple[str, ...]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()\n`")
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        return tuple(lexer)
    except ValueError:
        return ()


def _is_control_operator(token: str) -> bool:
    return bool(token) and all(character in ";&|\n" for character in token)


def _shell_command_index(tokens: list[str]) -> int | None:
    for index, token in enumerate(tokens[1:], start=1):
        if token == "-c" or (
            token.startswith("-") and not token.startswith("--") and "c" in token[1:]
        ):
            return index + 1 if index + 1 < len(tokens) else None
    return None


def _mark_indirect(operation: CommandOperation) -> CommandOperation:
    classification = (
        "ambiguous-mutation"
        if operation.classification == "cluster-mutation"
        else operation.classification
    )
    return replace(
        operation,
        classification=classification,
        indirect=True,
        ambiguity="indirect cluster mutation cannot prove its effective target",
    )


def _classify_invocation(tokens: list[str], *, inherited_indirect: bool) -> list[CommandOperation]:
    tokens, environment, environment_cleared, unset, execution_prefix = _unwrap_direct(tokens)
    if not tokens:
        return []
    binary = Path(tokens[0]).name
    if binary in EVAL_BINARIES:
        return [
            _mark_indirect(operation)
            for operation in _classify_token_stream(
                list(_shell_tokens(" ".join(tokens[1:]))),
                inherited_indirect=True,
            )
        ]
    if binary in SHELL_BINARIES:
        command_index = _shell_command_index(tokens)
        if command_index is None:
            return []
        return [
            _mark_indirect(operation)
            for operation in _classify_token_stream(
                list(_shell_tokens(tokens[command_index])),
                inherited_indirect=True,
            )
        ]
    if binary in INDIRECT_BINARIES:
        nested_index = next(
            (
                index
                for index, token in enumerate(tokens[1:], start=1)
                if Path(token).name
                in GUARDED_BINARIES | SHELL_BINARIES | EVAL_BINARIES | DIRECT_WRAPPERS
            ),
            None,
        )
        if nested_index is None:
            return []
        return [
            _mark_indirect(operation)
            for operation in _classify_invocation(tokens[nested_index:], inherited_indirect=True)
        ]
    if binary not in GUARDED_BINARIES:
        return []

    arguments = tokens[1:]
    commands = _subcommands(arguments)
    subcommand = commands[0] if commands else None
    if binary in POLICY_BINARIES:
        return [
            CommandOperation(
                binary,
                subcommand,
                "policy-command",
                executable=tokens[0],
                arguments=tuple(arguments),
                positionals=tuple(commands),
                execution_prefix=execution_prefix,
                indirect=inherited_indirect or environment_cleared,
                ambiguity=(
                    "indirect command cannot prove its execution semantics"
                    if inherited_indirect
                    else "environment-altering wrapper cannot prove its execution semantics"
                    if environment_cleared
                    else None
                ),
            )
        ]
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

    config_variable = "TALOSCONFIG" if binary == "talosctl" else "KUBECONFIG"
    config_flag = "--talosconfig" if binary == "talosctl" else "--kubeconfig"
    config_path = _option_value(arguments, config_flag) or environment.get(config_variable)
    environment_unknown = (
        environment_cleared or config_variable in unset
    ) and config_path is None
    unmodeled_environment = (
        (set(environment) | set(unset))
        & (EFFECTIVE_TARGET_ENVIRONMENT - {config_variable})
    )
    mise_environment_unknown = bool(execution_prefix) and any(
        name.startswith("MISE_") for name in environment
    )
    environment_unknown = bool(
        environment_unknown or mise_environment_unknown or unmodeled_environment
    )
    indirect = inherited_indirect or environment_unknown
    if indirect and classification == "cluster-mutation":
        classification = "ambiguous-mutation"
    ambiguity = None
    if environment_unknown:
        ambiguity = "environment-altering wrapper cannot prove its effective target"
    elif inherited_indirect:
        ambiguity = "indirect cluster mutation cannot prove its effective target"

    return [
        CommandOperation(
            binary,
            subcommand,
            classification,
            executable=tokens[0],
            arguments=tuple(arguments),
            positionals=tuple(commands),
            context=_option_value(arguments, "--context"),
            config_path=config_path,
            server=_option_value(arguments, "--server", "-s") if binary != "talosctl" else None,
            cluster=(
                _option_value(arguments, "--cluster", "-c")
                if binary == "talosctl"
                else _option_value(arguments, "--cluster")
            ),
            endpoints=_option_values(arguments, "--endpoints", "-e") if binary == "talosctl" else (),
            nodes=_option_values(arguments, "--nodes", "-n") if binary == "talosctl" else (),
            execution_prefix=execution_prefix,
            indirect=indirect,
            ambiguity=ambiguity,
        )
    ]


def _classify_token_stream(
    tokens: list[str],
    *,
    inherited_indirect: bool = False,
) -> list[CommandOperation]:
    operations: list[CommandOperation] = []
    flattened: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        embedded = [
            match.group(1)
            for pattern in (r"`([^`]*)`", r"\$\(([^()]*)\)")
            for match in re.finditer(pattern, token)
        ]
        for command in embedded:
            operations.extend(
                _mark_indirect(operation)
                for operation in _classify_token_stream(
                    list(_shell_tokens(command)),
                    inherited_indirect=True,
                )
            )
        if embedded:
            token = re.sub(r"`[^`]*`|\$\([^()]*\)", "", token)
            if not token:
                index += 1
                continue
        if token == "`":
            end = index + 1
            while end < len(tokens) and tokens[end] != "`":
                end += 1
            nested = tokens[index + 1 : end]
            operations.extend(
                _mark_indirect(operation)
                for operation in _classify_token_stream(nested, inherited_indirect=True)
            )
            index = end + 1 if end < len(tokens) else end
            continue
        if token == "(":
            depth = 1
            end = index + 1
            while end < len(tokens) and depth:
                if tokens[end] == "(":
                    depth += 1
                elif tokens[end] == ")":
                    depth -= 1
                end += 1
            nested = tokens[index + 1 : end - 1 if depth == 0 else end]
            operations.extend(
                _mark_indirect(operation)
                for operation in _classify_token_stream(nested, inherited_indirect=True)
            )
            if flattened and flattened[-1] == "$":
                flattened.pop()
            index = end
            continue
        flattened.append(token)
        index += 1

    segment: list[str] = []
    stateful_prefix = False

    def classify_segment(value: list[str]) -> None:
        nonlocal stateful_prefix
        if not value:
            return
        binary = Path(value[0]).name
        assignments = tuple(_assignment(token) for token in value)
        if binary in SHELL_STATE_BINARIES or (
            all(assignment is not None for assignment in assignments)
            and any(
                assignment[0] in EFFECTIVE_TARGET_ENVIRONMENT
                for assignment in assignments
                if assignment is not None
            )
        ):
            stateful_prefix = True
            return
        operations.extend(
            _classify_invocation(
                value,
                inherited_indirect=inherited_indirect or stateful_prefix,
            )
        )

    for token in flattened:
        if _is_control_operator(token) or token in SHELL_BOUNDARIES:
            classify_segment(segment)
            segment = []
            if token in SHELL_BOUNDARIES:
                stateful_prefix = True
            continue
        segment.append(token)
    classify_segment(segment)
    return operations


def classify_command(command: str) -> tuple[CommandOperation, ...]:
    return tuple(_classify_token_stream(list(_shell_tokens(command))))


def _talos_info(output: str | None) -> dict[str, str]:
    if output is None:
        return {}
    result: dict[str, str] = {}
    for line in output.splitlines():
        key, separator, value = line.partition(":")
        if separator:
            result[key.strip().lower()] = value.strip()
    return result


def _talos_context(output: str | None) -> str | None:
    info = _talos_info(output)
    return info.get("current context") or info.get("context")


def _kube_endpoint_command(
    *,
    execution_prefix: tuple[str, ...] = (),
    executable: str = "kubectl",
    config_path: str | None = None,
    context: str | None = None,
    cluster: str | None = None,
) -> list[str]:
    command = [*execution_prefix, executable]
    if config_path:
        command.extend(["--kubeconfig", config_path])
    if context:
        command.extend(["--context", context])
    if cluster:
        command.extend(["--cluster", cluster])
    command.extend(["config", "view", "--minify", "-o", KUBE_SERVER_JSONPATH])
    return command


def _same_endpoint(actual: str | None, expected: str | None) -> bool:
    if not actual or not expected:
        return False
    try:
        actual_url = urlsplit(actual)
        expected_url = urlsplit(expected)
        actual_port = actual_url.port or (443 if actual_url.scheme == "https" else 80)
        expected_port = expected_url.port or (443 if expected_url.scheme == "https" else 80)
    except ValueError:
        return False
    return (
        actual_url.scheme.lower(),
        (actual_url.hostname or "").lower(),
        actual_port,
        actual_url.path.rstrip("/"),
    ) == (
        expected_url.scheme.lower(),
        (expected_url.hostname or "").lower(),
        expected_port,
        expected_url.path.rstrip("/"),
    )


def _talos_selected_targets(info: dict[str, str]) -> set[str]:
    values: set[str] = set()
    for key in ("nodes", "endpoints"):
        values.update(
            item.strip()
            for item in info.get(key, "").split(",")
            if item.strip().lower() not in {"", "not defined", "none", "<none>"}
        )
    return values


def _talos_lan_targets(root: Path) -> set[str]:
    text = (root / "talos" / "talconfig.yaml").read_text(encoding="utf-8")
    return set(re.findall(r'(?m)^\s+ipAddress:\s*["\']?([^"\'\s]+)', text))


def preflight_command(
    command: str,
    root: Path,
    *,
    environ: Mapping[str, str] | None = None,
    runner: RunStdout = run_stdout,
) -> list[PreflightViolation]:
    violations: list[PreflightViolation] = []
    for operation in classify_command(command):
        if operation.classification not in {"cluster-mutation", "ambiguous-mutation"}:
            continue
        if operation.indirect:
            violations.append(
                PreflightViolation(
                    operation.binary,
                    operation.subcommand,
                    None,
                    "provable Anton target",
                    operation.ambiguity
                    or "indirect cluster mutation cannot prove its effective target",
                )
            )
            continue

        if (
            operation.binary == "flux"
            and operation.executable
            and operation.executable != operation.binary
        ):
            violations.append(
                PreflightViolation(
                    operation.binary,
                    operation.subcommand,
                    "noncanonical executable path",
                    "PATH-resolved flux executable",
                    "explicit Flux executable path cannot prove its target semantics",
                )
            )
            continue

        if operation.binary in {"kubectl", "flux"}:
            expected = expected_kube_context(root, environ=environ, runner=runner)
            expected_endpoint = expected_kube_endpoint(
                root,
                expected,
                environ=environ,
                runner=runner,
            )
            executable = (
                operation.executable or operation.binary
                if operation.binary == "kubectl"
                else "kubectl"
            )
            context_command = [*operation.execution_prefix, executable]
            if operation.config_path:
                context_command.extend(["--kubeconfig", operation.config_path])
            context_command.extend(["config", "current-context"])
            actual = operation.context or runner(context_command)
            if actual == expected:
                actual_endpoint = operation.server or runner(
                    _kube_endpoint_command(
                        execution_prefix=operation.execution_prefix,
                        executable=executable,
                        config_path=operation.config_path,
                        context=actual,
                        cluster=operation.cluster,
                    )
                )
                if not _same_endpoint(actual_endpoint, expected_endpoint):
                    violations.append(
                        PreflightViolation(
                            operation.binary,
                            operation.subcommand,
                            "different or unresolved endpoint",
                            "Anton cluster endpoint",
                            "selected cluster endpoint does not match the Anton target",
                        )
                    )
                    continue
        else:
            expected = expected_talos_context(root, environ=environ)
            expected_cluster = expected_talos_cluster(root)
            executable = operation.executable or operation.binary
            context_command = [*operation.execution_prefix, executable]
            if operation.config_path:
                context_command.extend(["--talosconfig", operation.config_path])
            if operation.context:
                context_command.extend(["--context", operation.context])
            context_command.extend(["config", "info"])
            info_output = runner(context_command)
            actual = operation.context or _talos_context(info_output)
            if (
                actual == expected
                and operation.cluster
                and operation.cluster != expected_cluster
            ):
                violations.append(
                    PreflightViolation(
                        operation.binary,
                        operation.subcommand,
                        "different Talos proxy cluster",
                        expected_cluster,
                        "selected Talos proxy cluster does not match the Anton cluster",
                    )
                )
                continue
            if actual == expected:
                resolution = resolve_talos_targets(root, environ=environ, runner=runner)
                allowed = {
                    value
                    for node in resolution.nodes
                    for value in (node.name, node.address)
                }
                allowed.update(_talos_lan_targets(root))
                selected = set(operation.endpoints) | set(operation.nodes)
                if not selected:
                    selected = _talos_selected_targets(_talos_info(info_output))
                if not selected or not selected.issubset(allowed):
                    violations.append(
                        PreflightViolation(
                            operation.binary,
                            operation.subcommand,
                            "outside or unresolved inventory",
                            "Anton Talos node inventory",
                            "selected Talos target is outside the Anton inventory",
                        )
                    )
                    continue
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
