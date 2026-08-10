"""Shared Anton safety semantics for Claude and Codex hook adapters."""

from __future__ import annotations

import os
import posixpath
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from cluster_target_contract import CommandOperation, classify_command


@dataclass(frozen=True)
class PolicyViolation:
    code: str
    message: str


DESTRUCTIVE_OVERRIDE = re.compile(r"^\s*ANTON_DESTRUCTIVE_OK=1\s+")
SECRET_OVERRIDE = re.compile(r"^\s*ANTON_ALLOW_SECRET_READ=1\s+")

DANGEROUS_SECRET_OUTPUT = re.compile(
    r"(?:^|\s)(?:-o\s*=?\s*|--output(?:\s*=\s*|\s+))"
    r"(?:yaml|json|jsonpath(?:-as-json|-file)?|go-template(?:-file)?|custom-columns(?:-file)?|template)\b"
)

PROTECTED_BASENAMES = frozenset(
    {
        "age.key",
        "github-deploy.key",
        "cloudflare-tunnel.json",
        "github-push-token.txt",
    }
)
SOPS_FOOTER = re.compile(r"^sops:", re.MULTILINE)
WATCH_YAML_PREFIXES = ("kubernetes/", "talos/", "bootstrap/")
YAML_SUFFIXES = (".yaml", ".yml")
PLAN_PATTERN = re.compile(r"^\d{4}-.+\.md$")
FALLBACK_PLAN_STATUS = frozenset({"draft", "in-progress", "blocked", "done", "abandoned"})

PROTECTED_KUBECTL_RESOURCES = frozenset(
    {
        "namespace",
        "namespaces",
        "ns",
        "persistentvolume",
        "persistentvolumes",
        "pv",
        "pvs",
        "persistentvolumeclaim",
        "persistentvolumeclaims",
        "pvc",
        "pvcs",
        "customresourcedefinition",
        "customresourcedefinitions",
        "crd",
        "crds",
    }
)
SECRET_RESOURCES = frozenset({"secret", "secrets"})


def _resource_names(token: str) -> tuple[str, ...]:
    return tuple(
        item.split("/", 1)[0].split(".", 1)[0].lower()
        for item in token.split(",")
        if item
    )


def _has_flag(operation: CommandOperation, *names: str) -> bool:
    return any(
        token == name or token.startswith(f"{name}=")
        for token in operation.arguments
        for name in names
    )


def _rm_targets(arguments: tuple[str, ...]) -> tuple[str, ...]:
    options = True
    targets: list[str] = []
    for token in arguments:
        if options and token == "--":
            options = False
        elif options and token.startswith("-"):
            continue
        else:
            targets.append(token)
    return tuple(targets)


def _is_broad_rm_target(target: str) -> bool:
    normalized = posixpath.normpath(target)
    return (
        target in {"/", "/*", "~", "$HOME"}
        or (target.startswith("/") and normalized == "/")
        or re.fullmatch(r"/+(?:\./*)*", target) is not None
        or target.startswith("~/")
        or target.startswith("$HOME/")
        or (
            re.match(
                r"^\$\{HOME(?:(?:[:]?[-+?=]|[%#]{1,2})[^}]*)?\}(?:/|$)",
                target,
            )
            is not None
        )
        or re.fullmatch(r"/Users/[^/]+", normalized) is not None
    )


def _cluster_destructive_reason(operation: CommandOperation) -> str | None:
    if operation.binary == "talosctl":
        if operation.subcommand == "reset":
            return "talosctl reset wipes a Talos node."
        if operation.subcommand == "apply-config":
            return "talosctl apply-config changes node configuration."
    if operation.binary == "flux":
        if operation.subcommand == "uninstall":
            return "flux uninstall removes Flux."
        if operation.subcommand == "suspend":
            return "flux suspend halts reconciliation for its selected resources."
    if operation.binary == "kubectl":
        if operation.subcommand == "delete" and any(
            resource in PROTECTED_KUBECTL_RESOURCES
            for token in operation.positionals[1:]
            for resource in _resource_names(token)
        ):
            return "kubectl delete of a namespace, volume, or CRD can cascade."
        if operation.subcommand == "drain" and _has_flag(
            operation, "--delete-emptydir-data", "--delete-local-data"
        ):
            return "kubectl drain with emptyDir deletion destroys local pod data."
    if operation.binary == "task" and "talos:reset" in operation.positionals:
        return "task talos:reset wipes the cluster."
    if operation.binary == "helmfile" and "destroy" in operation.positionals:
        return "helmfile destroy removes bootstrap releases."
    if operation.binary == "rm":
        recursive = _has_flag(operation, "--recursive") or any(
            token.startswith("-") and not token.startswith("--") and "r" in token[1:]
            for token in operation.arguments
        )
        force = _has_flag(operation, "--force") or any(
            token.startswith("-") and not token.startswith("--") and "f" in token[1:]
            for token in operation.arguments
        )
        if recursive and force and any(
            _is_broad_rm_target(target)
            for target in _rm_targets(operation.arguments)
        ):
            return "recursive rm at HOME or the filesystem root is catastrophic."
    return None


def _secret_output_operation(operation: CommandOperation) -> bool:
    return (
        operation.binary == "kubectl"
        and operation.subcommand == "get"
        and any(
            resource in SECRET_RESOURCES
            for token in operation.positionals[1:]
            for resource in _resource_names(token)
        )
        and DANGEROUS_SECRET_OUTPUT.search(" ".join(operation.arguments)) is not None
    )


def destructive_command_violation(command: str) -> PolicyViolation | None:
    if not command or DESTRUCTIVE_OVERRIDE.match(command):
        return None
    for operation in classify_command(command):
        reason = _cluster_destructive_reason(operation)
        if reason:
            return PolicyViolation(
                "command.destructive",
                f"{reason} Ask for explicit operator approval and prefix the approved "
                "command with ANTON_DESTRUCTIVE_OK=1.",
            )
    return None


def secret_output_violation(command: str) -> PolicyViolation | None:
    if not command or SECRET_OVERRIDE.match(command):
        return None
    for operation in classify_command(command):
        if _secret_output_operation(operation):
            return PolicyViolation(
                "command.secret-output",
                "kubectl Secret output would expose .data values; use ExternalSecret "
                "status or describe, or obtain explicit approval with "
                "ANTON_ALLOW_SECRET_READ=1.",
            )
    return None


def tailnet_content_violation(
    texts: Iterable[str],
    *,
    environ: Mapping[str, str] | None = None,
) -> PolicyViolation | None:
    environment = os.environ if environ is None else environ
    tailnet = environment.get("ANTON_TAILNET_NAME", "").strip()
    if not tailnet:
        return None
    needle = f"{tailnet}.ts.net"
    if any(isinstance(text, str) and needle in text for text in texts):
        return PolicyViolation(
            "content.tailnet",
            f"payload contains real tailnet name {needle!r}; use '<tailnet-name>.ts.net'.",
        )
    return None


def _is_sops_path(path: Path) -> bool:
    return any(".sops." in part for part in path.parts)


def protected_edit_violation(path: Path) -> PolicyViolation | None:
    if path.name.lower() in PROTECTED_BASENAMES:
        return PolicyViolation(
            "edit.protected-credential",
            f"{path} is a protected credential artifact; use its rotation workflow.",
        )
    if not _is_sops_path(path) or not path.exists():
        return None
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return None
    if "ENC[AES256" in text or SOPS_FOOTER.search(text):
        return PolicyViolation(
            "edit.encrypted-sops",
            f"{path} is already SOPS-encrypted; edit it with sops and keep the footer intact.",
        )
    return None


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def yaml_file_violation(path: Path, root: Path) -> PolicyViolation | None:
    relative = _relative(path, root)
    if not path.exists() or path.suffix not in YAML_SUFFIXES or ".sops." in path.name:
        return None
    if not any(relative.startswith(prefix) for prefix in WATCH_YAML_PREFIXES):
        return None
    if not shutil.which("yq"):
        return None
    try:
        result = subprocess.run(["yq", ".", str(path)], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode == 0:
        return None
    return PolicyViolation(
        "validation.yaml",
        f"YAML syntax error in {relative}: {result.stderr.strip()}",
    )


def _plan_statuses(root: Path) -> frozenset[str]:
    path = root / ".claude" / "skills" / "planner" / "references" / "statuses.txt"
    try:
        values = {
            line.strip().lower()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        }
    except (OSError, UnicodeDecodeError):
        return FALLBACK_PLAN_STATUS
    return frozenset(values) or FALLBACK_PLAN_STATUS


def plan_status_violation(path: Path, root: Path) -> PolicyViolation | None:
    relative = _relative(path, root)
    if not relative.startswith("context/plans/") or path.parent.name != "plans" or not PLAN_PATTERN.match(path.name):
        return None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            return None
        if stripped.startswith("status:"):
            status = stripped.partition(":")[2].strip().lower()
            statuses = _plan_statuses(root)
            if status and status not in statuses:
                allowed = ", ".join(sorted(statuses))
                return PolicyViolation(
                    "validation.plan-status",
                    f"Plan {path.name} has invalid status {status!r}; expected one of: {allowed}.",
                )
            return None
    return None
