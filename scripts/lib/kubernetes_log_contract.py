"""Anton Kubernetes logging vocabulary, invariants, and adapter validation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


SEVERITIES = ("fatal", "error", "warn", "info", "debug", "trace")
SEVERITY_ALIASES = {
    "critical": "fatal",
    "panic": "fatal",
    "err": "error",
    "warning": "warn",
}
DEFAULT_SEVERITY = "info"

INDEXED_RESOURCE_ATTRIBUTES = (
    "k8s.namespace.name",
    "k8s.container.name",
    "k8s.deployment.name",
    "k8s.statefulset.name",
    "k8s.daemonset.name",
    "k8s.job.name",
    "k8s.cronjob.name",
    "severity",
)
INDEXED_LOKI_LABELS = tuple(value.replace(".", "_") for value in INDEXED_RESOURCE_ATTRIBUTES)

DEFAULT_RETENTION = "24h"
RETENTION_STREAMS = {
    '{severity=~"fatal|error"}': "720h",
    '{severity="warn"}': "336h",
    '{severity=~"debug|trace"}': "6h",
    '{severity=~"info|unknown"}': "24h",
}


@dataclass(frozen=True)
class ContractViolation:
    adapter: str
    path: Path
    message: str

    def render(self, root: Path) -> str:
        try:
            rel = self.path.resolve().relative_to(root.resolve()).as_posix()
        except (OSError, ValueError):
            rel = self.path.as_posix()
        return f"[logging.{self.adapter}] {rel}: {self.message}"


def normalize_severity(severity_text: str | None, body: str = "") -> str:
    """Normalize a fixture using the same public behavior as the OTel adapter."""
    value = (severity_text or "").strip().lower()
    value = SEVERITY_ALIASES.get(value, value)
    if value in SEVERITIES:
        return value

    patterns = (
        ("fatal", r'''(?i)^(F[0-9]{4}|fatal|critical|panic)\b|(level|severity)["'=:\s]+["']?(fatal|critical|panic)\b'''),
        ("error", r'''(?i)^(E[0-9]{4}|error|err|failed|failure|exception)\b|(level|severity)["'=:\s]+["']?(error|err)\b'''),
        ("warn", r'''(?i)^(W[0-9]{4}|warn|warning)\b|(level|severity)["'=:\s]+["']?(warn|warning)\b'''),
        ("debug", r'''(?i)^(D[0-9]{4}|debug)\b|(level|severity)["'=:\s]+["']?debug\b'''),
        ("trace", r'''(?i)^trace\b|(level|severity)["'=:\s]+["']?trace\b'''),
    )
    for normalized, pattern in patterns:
        if re.search(pattern, body):
            return normalized
    return DEFAULT_SEVERITY


def load_fixtures(path: Path) -> list[dict[str, str | None]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("logging fixtures must be a JSON list")
    return data


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def validate_fixtures(path: Path) -> list[ContractViolation]:
    violations: list[ContractViolation] = []
    try:
        fixtures = load_fixtures(path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [ContractViolation("fixtures", path, f"cannot load golden records: {error}")]
    for fixture in fixtures:
        name = str(fixture.get("name", "unnamed"))
        actual = normalize_severity(
            fixture.get("severity_text") if isinstance(fixture.get("severity_text"), str) else None,
            str(fixture.get("body", "")),
        )
        expected = fixture.get("expected")
        if actual != expected:
            violations.append(
                ContractViolation("fixtures", path, f"{name!r} normalized to {actual!r}, expected {expected!r}")
            )
    return violations


def validate_otel(path: Path) -> list[ContractViolation]:
    text = _read(path)
    violations: list[ContractViolation] = []
    required_fragments = [
        'delete_key(resource.attributes, "severity")',
        'set(log.severity_text, log.attributes["severity_text"]) where log.attributes["severity_text"] != nil',
        'set(log.severity_text, log.attributes["level"]) where log.attributes["level"] != nil',
        'set(log.severity_text, log.attributes["severity"]) where log.attributes["severity"] != nil',
        r'''IsMatch(log.body, "(?i)^(F[0-9]{4}|fatal|critical|panic)\\b|(level|severity)[\"'=:\\s]+[\"']?(fatal|critical|panic)\\b")''',
        r'''IsMatch(log.body, "(?i)^(E[0-9]{4}|error|err|failed|failure|panic|exception)\\b|(level|severity)[\"'=:\\s]+[\"']?(error|err)\\b")''',
        r'''IsMatch(log.body, "(?i)^(W[0-9]{4}|warn|warning)\\b|(level|severity)[\"'=:\\s]+[\"']?(warn|warning)\\b")''',
        r'''IsMatch(log.body, "(?i)^(D[0-9]{4}|debug)\\b|(level|severity)[\"'=:\\s]+[\"']?debug\\b")''',
        r'''IsMatch(log.body, "(?i)^trace\\b|(level|severity)[\"'=:\\s]+[\"']?trace\\b")''',
        'set(log.attributes["severity"], "info") where log.attributes["severity"] == nil',
        "groupbyattrs/severity:",
        "start_at: end",
    ]
    required_fragments.extend(
        f'set(log.attributes["severity"], "{severity}")' for severity in SEVERITIES if severity != "info"
    )
    for fragment in required_fragments:
        if fragment not in text:
            violations.append(ContractViolation("otel", path, f"missing invariant {fragment!r}"))

    pipeline_order = [
        text.rfind("              - transform/severity"),
        text.rfind("              - groupbyattrs/severity"),
        text.rfind("              - batch"),
    ]
    if any(position < 0 for position in pipeline_order) or pipeline_order != sorted(pipeline_order):
        violations.append(
            ContractViolation("otel", path, "logs pipeline must normalize, group by severity, then batch")
        )
    return violations


def _retention_streams(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    pattern = re.compile(
        r"(?m)^\s*- selector:\s*(['\"])(?P<selector>.+?)\1\s*$"
        r"(?:\n^\s+priority:\s*\d+\s*$)?"
        r"\n^\s+period:\s*(?P<period>\S+)\s*$"
    )
    for match in pattern.finditer(text):
        result[match.group("selector")] = match.group("period")
    return result


def _indexed_attributes(text: str) -> tuple[str, ...]:
    match = re.search(
        r"(?m)^\s+default_resource_attributes_as_index_labels:\s*$\n"
        r"(?P<items>(?:^\s+-\s+\S+\s*$\n?)+)",
        text,
    )
    if not match:
        return ()
    return tuple(re.findall(r"(?m)^\s+-\s+(\S+)\s*$", match.group("items")))


def validate_loki(path: Path) -> list[ContractViolation]:
    text = _read(path)
    violations: list[ContractViolation] = []
    default_match = re.search(r"(?m)^\s+retention_period:\s*(\S+)\s*$", text)
    actual_default = default_match.group(1) if default_match else None
    if actual_default != DEFAULT_RETENTION:
        violations.append(
            ContractViolation("loki", path, f"default retention is {actual_default!r}, expected {DEFAULT_RETENTION!r}")
        )

    actual_streams = _retention_streams(text)
    if actual_streams != RETENTION_STREAMS:
        violations.append(
            ContractViolation(
                "loki",
                path,
                f"retention streams are {actual_streams!r}, expected {RETENTION_STREAMS!r}",
            )
        )

    actual_labels = _indexed_attributes(text)
    if actual_labels != INDEXED_RESOURCE_ATTRIBUTES:
        violations.append(
            ContractViolation(
                "loki",
                path,
                f"indexed resource attributes are {actual_labels!r}, expected {INDEXED_RESOURCE_ATTRIBUTES!r}",
            )
        )
    return violations


def validate_grafana(path: Path) -> list[ContractViolation]:
    text = _read(path)
    required = (
        "        - name: Loki",
        "          uid: loki",
        "          url: http://loki.observability.svc.cluster.local:3100",
        "          editable: false",
    )
    return [
        ContractViolation("grafana", path, f"missing datasource invariant {fragment.strip()!r}")
        for fragment in required
        if fragment not in text
    ]


def validate_query_catalog(path: Path) -> list[ContractViolation]:
    text = _read(path)
    violations: list[ContractViolation] = []
    for selector in re.findall(r"\{([^{}]+)\}", text):
        for label in re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*(?:=~|!~|!=|=)", selector):
            if label not in INDEXED_LOKI_LABELS:
                violations.append(
                    ContractViolation("queries", path, f"query uses non-indexed selector label {label!r}")
                )
    return violations


def validate_pointer(path: Path) -> list[ContractViolation]:
    if "scripts/validate-log-contract.py --show" in _read(path):
        return []
    return [
        ContractViolation(
            "documentation",
            path,
            "must point to 'scripts/validate-log-contract.py --show' instead of copying contract facts",
        )
    ]


def validate_runbook(path: Path) -> list[ContractViolation]:
    text = _read(path)
    violations = validate_pointer(path)
    required = (
        "mise exec -- task contracts:validate",
        "seaweedfs-buckets-ensure",
    )
    violations.extend(
        ContractViolation("documentation", path, f"missing operational invariant {fragment!r}")
        for fragment in required
        if fragment not in text
    )
    if "seaweedfs-lakehouse-buckets-ensure" in text:
        violations.append(ContractViolation("documentation", path, "references removed lakehouse bucket Job"))

    rollout = text.partition("## Rollout and ClickStack teardown")[2]
    storage_position = rollout.find("seaweedfs-config")
    loki_position = rollout.find("Loki app")
    if storage_position < 0 or loki_position < 0 or storage_position >= loki_position:
        violations.append(
            ContractViolation(
                "documentation",
                path,
                "rollout must provision the storage-owned Loki bucket before reconciling Loki",
            )
        )
    return violations


def validate_repository(root: Path) -> list[ContractViolation]:
    return [
        *validate_fixtures(root / "scripts" / "tests" / "fixtures" / "kubernetes-log-records.json"),
        *validate_otel(root / "kubernetes" / "apps" / "observability" / "otel-collector" / "app" / "helmrelease.yaml"),
        *validate_loki(root / "kubernetes" / "apps" / "observability" / "loki" / "app" / "helmrelease.yaml"),
        *validate_grafana(root / "kubernetes" / "apps" / "observability" / "kube-prometheus-stack" / "app" / "helmrelease.yaml"),
        *validate_query_catalog(root / ".agents" / "skills" / "query-kubernetes-logs" / "references" / "query-catalog.md"),
        *validate_runbook(root / "docs" / "docs" / "runbooks" / "kubernetes-logs-loki.md"),
        *validate_pointer(root / ".agents" / "skills" / "query-kubernetes-logs" / "SKILL.md"),
    ]


def contract_summary() -> str:
    lines = [
        "Kubernetes logging contract (ADR 0030)",
        f"severity: {', '.join(SEVERITIES)}; default={DEFAULT_SEVERITY}",
        f"indexed labels: {', '.join(INDEXED_LOKI_LABELS)}",
        f"default retention: {DEFAULT_RETENTION}",
        "stream retention:",
    ]
    lines.extend(f"  {selector}: {period}" for selector, period in RETENTION_STREAMS.items())
    return "\n".join(lines)
