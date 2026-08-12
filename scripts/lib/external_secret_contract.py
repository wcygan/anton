"""Validate Anton ExternalSecret references, output contracts, and traffic."""

from __future__ import annotations

import json
import math
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REFRESH_CLASS_ANNOTATION = "anton.wcygan.net/secret-refresh-class"
COMBINED_KEY = re.compile(r"^[^/\s]+/[^/\s]+$")
DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s)")
SECONDS_PER_DAY = 86_400
SECONDS_PER_HOUR = 3_600


@dataclass(frozen=True)
class ContractReport:
    failures: tuple[str, ...]
    scheduled_operations: int
    manifest_count: int


def _duration_seconds(value: object) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    position = 0
    seconds = 0.0
    factors = {"h": 3600.0, "m": 60.0, "s": 1.0, "ms": 0.001}
    for match in DURATION_PART.finditer(value):
        if match.start() != position:
            return None
        seconds += float(match.group(1)) * factors[match.group(2)]
        position = match.end()
    if position != len(value) or seconds <= 0:
        return None
    return seconds


def _target_keys(spec: dict[str, Any]) -> list[str]:
    template_data = spec.get("target", {}).get("template", {}).get("data", {})
    if isinstance(template_data, dict) and template_data:
        return sorted(str(key) for key in template_data)
    return sorted(
        str(entry.get("secretKey"))
        for entry in spec.get("data", [])
        if isinstance(entry, dict) and entry.get("secretKey") is not None
    )


def _direct_entries(spec: dict[str, Any]) -> list[dict[str, Any]]:
    return [entry for entry in spec.get("data", []) if isinstance(entry, dict)]


def _extract_entries(spec: dict[str, Any]) -> list[dict[str, Any]]:
    return [entry for entry in spec.get("dataFrom", []) if isinstance(entry, dict)]


def validate_contract(
    documents: dict[str, dict[str, Any]], inventory: dict[str, Any]
) -> ContractReport:
    failures: list[str] = []
    scheduled_operations = 0
    approved = inventory.get("manifests", {})
    daily_limit = inventory.get("dailyOperationLimit")

    if not isinstance(approved, dict):
        return ContractReport(("inventory manifests must be an object",), 0, len(documents))
    if not isinstance(daily_limit, int) or daily_limit <= 0:
        failures.append("inventory dailyOperationLimit must be a positive integer")

    for path in sorted(set(documents) - set(approved)):
        failures.append(f"{path}: ExternalSecret manifest is not approved")
    for path in sorted(set(approved) - set(documents)):
        failures.append(f"{path}: approved ExternalSecret manifest is missing")

    for path in sorted(set(documents) & set(approved)):
        document = documents[path]
        expected = approved[path]
        prefix = f"{path}:"
        metadata = document.get("metadata", {})
        spec = document.get("spec", {})

        if document.get("kind") != "ExternalSecret":
            failures.append(f"{prefix} kind must be ExternalSecret")
            continue
        if metadata.get("name") != expected.get("name"):
            failures.append(f"{prefix} ExternalSecret name changed from the approved contract")

        target_name = spec.get("target", {}).get("name") or metadata.get("name")
        if target_name != expected.get("targetName"):
            failures.append(f"{prefix} target name changed from the approved Secret contract")
        actual_keys = _target_keys(spec)
        expected_keys = sorted(expected.get("targetKeys", []))
        if actual_keys != expected_keys:
            failures.append(
                f"{prefix} target keys changed: expected {expected_keys}, found {actual_keys}"
            )

        store = spec.get("secretStoreRef", {})
        if store != {"kind": "ClusterSecretStore", "name": "onepassword-connect"}:
            failures.append(f"{prefix} must use ClusterSecretStore onepassword-connect")

        refresh_class = metadata.get("annotations", {}).get(REFRESH_CLASS_ANNOTATION)
        if refresh_class != expected.get("refreshClass"):
            failures.append(f"{prefix} refresh class changed or is missing")
        if refresh_class not in {"stable", "development"}:
            failures.append(f"{prefix} refresh class must be stable or development")

        policy = spec.get("refreshPolicy")
        interval_seconds = _duration_seconds(spec.get("refreshInterval"))
        if refresh_class == "stable":
            if policy != "Periodic":
                failures.append(f"{prefix} stable secrets must use Periodic refreshPolicy")
            if interval_seconds is None or interval_seconds < 24 * SECONDS_PER_HOUR:
                failures.append(f"{prefix} stable refreshInterval must be at least 24h")
        elif refresh_class == "development":
            if policy not in {"OnChange", "Periodic"}:
                failures.append(
                    f"{prefix} development secrets must use OnChange or Periodic refreshPolicy"
                )
            if policy == "Periodic" and (
                interval_seconds is None or interval_seconds < 24 * SECONDS_PER_HOUR
            ):
                failures.append(
                    f"{prefix} scheduled development refreshInterval must be at least 24h"
                )

        direct_entries = _direct_entries(spec)
        remote_refs: list[str] = []
        source_keys: list[str] = []
        for entry in direct_entries:
            source_key = entry.get("secretKey")
            if not isinstance(source_key, str) or not source_key:
                failures.append(f"{prefix} data entry must define a non-empty secretKey")
            else:
                source_keys.append(source_key)
            remote_ref = entry.get("remoteRef")
            if not isinstance(remote_ref, dict):
                failures.append(f"{prefix} data entry must define remoteRef")
                continue
            unsupported = sorted(set(remote_ref) - {"key"})
            if "property" in remote_ref:
                failures.append(f"{prefix} remoteRef.property is unsafe with onepasswordSDK")
            elif unsupported:
                failures.append(f"{prefix} remoteRef has unsupported keys {unsupported}")
            key = remote_ref.get("key")
            if not isinstance(key, str) or not COMBINED_KEY.fullmatch(key):
                failures.append(f"{prefix} remoteRef.key must use one <item>/<field> combined key")
            else:
                remote_refs.append(key)
        if len(source_keys) != len(set(source_keys)):
            failures.append(f"{prefix} data secretKey values must be unique")

        extract_items: list[str] = []
        for entry in _extract_entries(spec):
            unsupported = sorted(set(entry) - {"extract"})
            if "find" in entry:
                failures.append(f"{prefix} dataFrom.find is not approved for onepasswordSDK")
            elif unsupported:
                failures.append(f"{prefix} dataFrom has unsupported keys {unsupported}")
            extract = entry.get("extract")
            if not isinstance(extract, dict):
                continue
            extract_key = extract.get("key")
            if not isinstance(extract_key, str) or "/" in extract_key or not extract_key.strip():
                failures.append(f"{prefix} dataFrom.extract.key must be one item title")
            else:
                extract_items.append(extract_key)

        expected_refs = sorted(expected.get("remoteRefs", []))
        if sorted(remote_refs) != expected_refs:
            failures.append(
                f"{prefix} approved references changed: expected {expected_refs}, "
                f"found {sorted(remote_refs)}"
            )
        expected_extracts = sorted(expected.get("extractItems", []))
        if sorted(extract_items) != expected_extracts:
            failures.append(
                f"{prefix} approved extract items changed: expected {expected_extracts}, "
                f"found {sorted(extract_items)}"
            )

        operation_count = len(remote_refs) + len(extract_items)
        if policy == "Periodic" and interval_seconds:
            scheduled_operations += operation_count * math.ceil(
                SECONDS_PER_DAY / interval_seconds
            )

    if isinstance(daily_limit, int) and scheduled_operations > daily_limit:
        failures.append(
            f"scheduled estimate {scheduled_operations} exceeds daily operation limit {daily_limit}"
        )

    return ContractReport(tuple(failures), scheduled_operations, len(documents))


def load_inventory(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_admission_guard(documents: list[dict[str, Any]]) -> tuple[str, ...]:
    failures: list[str] = []
    policy = next(
        (document for document in documents if document.get("kind") == "ValidatingAdmissionPolicy"),
        None,
    )
    binding = next(
        (
            document
            for document in documents
            if document.get("kind") == "ValidatingAdmissionPolicyBinding"
        ),
        None,
    )
    if policy is None:
        failures.append("admission guard must define a ValidatingAdmissionPolicy")
        return tuple(failures)
    if policy.get("metadata", {}).get("name") != "external-secret-onepassword-guard":
        failures.append("admission guard policy name changed")
    if policy.get("spec", {}).get("failurePolicy") != "Fail":
        failures.append("admission guard failurePolicy must be Fail")
    rules = policy.get("spec", {}).get("matchConstraints", {}).get("resourceRules", [])
    if not any(
        rule.get("apiGroups") == ["external-secrets.io"]
        and rule.get("apiVersions") == ["v1"]
        and set(rule.get("operations", [])) == {"CREATE", "UPDATE"}
        and rule.get("resources") == ["externalsecrets"]
        for rule in rules
        if isinstance(rule, dict)
    ):
        failures.append("admission guard must match ExternalSecret CREATE and UPDATE")
    expressions = "\n".join(
        validation.get("expression", "")
        for validation in policy.get("spec", {}).get("validations", [])
        if isinstance(validation, dict)
    )
    required_fragments = (
        "onepassword-connect",
        REFRESH_CLASS_ANNOTATION,
        "duration('24h')",
        "remoteRef.key.matches",
        "!has(entry.remoteRef.property)",
        "dataFrom",
    )
    for fragment in required_fragments:
        if fragment not in expressions:
            failures.append(f"admission guard is missing expression fragment {fragment!r}")
    if binding is None:
        failures.append("admission guard must define a ValidatingAdmissionPolicyBinding")
    else:
        binding_spec = binding.get("spec", {})
        if binding_spec.get("policyName") != "external-secret-onepassword-guard":
            failures.append("admission guard binding targets the wrong policy")
        if binding_spec.get("validationActions") != ["Deny"]:
            failures.append("admission guard binding must use Deny")
    return tuple(failures)


def load_yaml_documents(repo: Path, path: Path) -> list[dict[str, Any]]:
    result = subprocess.run(
        ["yq", "eval-all", "-o=json", "-I=0", "[.]", str(path)],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise ValueError(f"cannot parse {path.relative_to(repo)}: {result.stderr.strip()}")
    return json.loads(result.stdout)


def load_external_secrets(repo: Path) -> dict[str, dict[str, Any]]:
    documents: dict[str, dict[str, Any]] = {}
    root = repo / "kubernetes" / "apps"
    for path in sorted(root.rglob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        if "kind: ExternalSecret" not in text:
            continue
        result = subprocess.run(
            ["yq", "-o=json", ".", str(path)],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            raise ValueError(f"cannot parse {path.relative_to(repo)}: {result.stderr.strip()}")
        document = json.loads(result.stdout)
        documents[path.relative_to(repo).as_posix()] = document
    return documents
