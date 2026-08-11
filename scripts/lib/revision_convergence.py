"""Evaluate one Flux source revision against an explicit Kustomization scope."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import ceil
from datetime import datetime, timezone
import re
from typing import Any


class ObservationError(ValueError):
    """The Flux status cannot support a trustworthy observation."""


REVISION_RECORD_SCHEMA_VERSION = 1
REVISION_RECORD_V2_SCHEMA_VERSION = 2
ROLLING_WINDOW_SIZE = 30
FULL_REVISION = re.compile(r".+@sha1:[0-9a-f]{40}$")
M2_SOURCE_KIND = "GitRepository"
M2_SOURCE_NAMESPACE = "flux-system"
M2_SOURCE_NAME = "flux-system"
CRITICAL_CLASSIFICATIONS = frozenset(
    {"current_ready", "current_failed", "stale_ready", "stale_failed", "missing"}
)


@dataclass(frozen=True)
class CriticalKustomization:
    """A Kustomization that must report the observed source revision."""

    namespace: str
    name: str

    @property
    def identifier(self) -> str:
        return f"{self.namespace}/{self.name}"


DEFAULT_CRITICAL_KUSTOMIZATIONS: tuple[CriticalKustomization, ...] = (
    CriticalKustomization("flux-system", "flux-system"),
    CriticalKustomization("flux-system", "cluster-apps"),
    CriticalKustomization("flux-system", "flux-operator"),
    CriticalKustomization("flux-system", "flux-instance"),
    CriticalKustomization("kube-system", "cilium"),
    CriticalKustomization("kube-system", "coredns"),
    CriticalKustomization("external-secrets", "external-secrets"),
    CriticalKustomization("external-secrets", "onepassword-store"),
    CriticalKustomization("network", "envoy-gateway"),
    CriticalKustomization("network", "cloudflare-dns"),
    CriticalKustomization("network", "cloudflare-tunnel"),
    CriticalKustomization("network", "k8s-gateway"),
    CriticalKustomization("storage", "longhorn-config"),
    CriticalKustomization("storage", "longhorn"),
    CriticalKustomization("storage", "seaweedfs"),
    CriticalKustomization("storage", "seaweedfs-config"),
    CriticalKustomization("observability", "kube-prometheus-stack"),
    CriticalKustomization("observability", "ntfy"),
)


def parse_utc_timestamp(value: str) -> datetime:
    """Parse an RFC 3339 timestamp as a UTC datetime."""

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ObservationError("invalid RFC 3339 timestamp") from error
    if parsed.tzinfo is None:
        raise ObservationError("timestamp has no timezone")
    return parsed.astimezone(timezone.utc)


def format_utc_timestamp(value: datetime) -> str:
    """Format an observation time without sub-second instability."""

    if value.tzinfo is None:
        raise ObservationError("observation time has no timezone")
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def format_exact_utc_timestamp(value: datetime) -> str:
    """Format a UTC timestamp without discarding fractional seconds."""

    if value.tzinfo is None:
        raise ObservationError("observation time has no timezone")
    utc_value = value.astimezone(timezone.utc)
    timespec = "microseconds" if utc_value.microsecond else "seconds"
    return utc_value.isoformat(timespec=timespec).replace("+00:00", "Z")


def _mapping(value: object, description: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ObservationError(f"{description} must be an object")
    return value


def _string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _ready_condition(status: Mapping[str, Any]) -> Mapping[str, Any] | None:
    conditions = status.get("conditions", [])
    if not isinstance(conditions, list):
        return None
    for condition in conditions:
        if isinstance(condition, Mapping) and condition.get("type") == "Ready":
            return condition
    return None


def _generation_is_current(
    metadata: Mapping[str, Any], status: Mapping[str, Any], ready: Mapping[str, Any] | None
) -> bool:
    generation = _integer(metadata.get("generation"))
    return (
        generation is not None
        and _integer(status.get("observedGeneration")) == generation
        and ready is not None
        and _integer(ready.get("observedGeneration")) == generation
    )


def _source_identity(source: Mapping[str, Any]) -> tuple[str, str, str, str, datetime]:
    metadata = _mapping(source.get("metadata"), "GitRepository metadata")
    status = _mapping(source.get("status"), "GitRepository status")
    artifact = _mapping(status.get("artifact"), "GitRepository status.artifact")
    ready = _ready_condition(status)
    namespace = _string(metadata.get("namespace"))
    name = _string(metadata.get("name"))
    revision = _string(artifact.get("revision"))
    artifact_time = _string(artifact.get("lastUpdateTime"))
    if source.get("kind") != "GitRepository":
        raise ObservationError("source kind must be GitRepository")
    if not namespace or not name or not revision or not artifact_time:
        raise ObservationError("GitRepository lacks namespace, name, revision, or artifact update time")
    if ready is None or ready.get("status") != "True" or not _generation_is_current(metadata, status, ready):
        raise ObservationError("GitRepository is not Ready at its current generation")
    return namespace, name, revision, artifact_time, parse_utc_timestamp(artifact_time)


def _index_kustomizations(document: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    items = document.get("items")
    if not isinstance(items, list):
        raise ObservationError("Kustomization list lacks items")
    index: dict[str, Mapping[str, Any]] = {}
    for item in items:
        object_item = _mapping(item, "Kustomization list item")
        metadata = _mapping(object_item.get("metadata"), "Kustomization metadata")
        namespace = _string(metadata.get("namespace"))
        name = _string(metadata.get("name"))
        if not namespace or not name:
            raise ObservationError("Kustomization lacks namespace or name")
        identifier = f"{namespace}/{name}"
        if identifier in index:
            raise ObservationError(f"Kustomization list duplicates {identifier}")
        index[identifier] = object_item
    return index


def _source_ref(
    resource: Mapping[str, Any], metadata: Mapping[str, Any]
) -> tuple[str | None, str | None, str | None]:
    spec = resource.get("spec")
    if not isinstance(spec, Mapping):
        return None, None, None
    source_ref = spec.get("sourceRef")
    if not isinstance(source_ref, Mapping):
        return None, None, None
    namespace = _string(source_ref.get("namespace")) or _string(metadata.get("namespace"))
    return _string(source_ref.get("kind")), _string(source_ref.get("name")), namespace


def _resource_observation(
    critical: CriticalKustomization,
    resource: Mapping[str, Any] | None,
    source_namespace: str,
    source_name: str,
    source_revision: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "classification": "missing",
        "detail": "not_found",
        "last_applied_revision": None,
        "last_attempted_revision": None,
        "metadata_generation": None,
        "name": critical.name,
        "namespace": critical.namespace,
        "observed_generation": None,
        "ready_observed_generation": None,
        "ready_reason": None,
        "ready_status": None,
        "source_ref": {"kind": None, "name": None, "namespace": None},
    }
    if resource is None:
        return result

    metadata = _mapping(resource.get("metadata"), "Kustomization metadata")
    status_value = resource.get("status")
    status = status_value if isinstance(status_value, Mapping) else {}
    ready = _ready_condition(status)
    source_kind, resource_source_name, resource_source_namespace = _source_ref(resource, metadata)
    result.update(
        {
            "last_applied_revision": _string(status.get("lastAppliedRevision")),
            "last_attempted_revision": _string(status.get("lastAttemptedRevision")),
            "metadata_generation": _integer(metadata.get("generation")),
            "observed_generation": _integer(status.get("observedGeneration")),
            "ready_observed_generation": _integer(ready.get("observedGeneration")) if ready else None,
            "ready_reason": _string(ready.get("reason")) if ready else None,
            "ready_status": _string(ready.get("status")) if ready else None,
            "source_ref": {
                "kind": source_kind,
                "name": resource_source_name,
                "namespace": resource_source_namespace,
            },
        }
    )
    if (source_kind, resource_source_name, resource_source_namespace) != (
        "GitRepository",
        source_name,
        source_namespace,
    ):
        result["detail"] = "source_ref_mismatch"
        return result

    generation_current = _generation_is_current(metadata, status, ready)
    ready_true = result["ready_status"] == "True"
    applied_current = result["last_applied_revision"] == source_revision
    attempted_current = result["last_attempted_revision"] == source_revision
    if ready_true and applied_current and generation_current:
        result.update({"classification": "current_ready", "detail": "current"})
    elif not ready_true and attempted_current and generation_current:
        result.update({"classification": "current_failed", "detail": "current_attempt_not_ready"})
    elif ready_true:
        result.update({"classification": "stale_ready", "detail": "ready_not_current"})
    else:
        result.update({"classification": "stale_failed", "detail": "failed_not_current"})
    return result


def evaluate_revision_convergence(
    source: Mapping[str, Any],
    kustomizations: Mapping[str, Any],
    *,
    critical: Sequence[CriticalKustomization] = DEFAULT_CRITICAL_KUSTOMIZATIONS,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    """Return one stable, current-revision observation without inferring duration."""

    if not critical:
        raise ObservationError("critical Kustomization inventory cannot be empty")
    unique_critical = {item.identifier for item in critical}
    if len(unique_critical) != len(critical):
        raise ObservationError("critical Kustomization inventory has duplicates")
    source_namespace, source_name, source_revision, artifact_time, artifact_updated_at = _source_identity(source)
    observation_time = datetime.now(timezone.utc) if observed_at is None else observed_at
    if observation_time.tzinfo is None:
        raise ObservationError("observation time has no timezone")
    observation_time = observation_time.astimezone(timezone.utc)
    age_seconds = int((observation_time - artifact_updated_at).total_seconds())
    if age_seconds < 0:
        raise ObservationError("observation time precedes GitRepository artifact update")

    index = _index_kustomizations(kustomizations)
    resources = [
        _resource_observation(item, index.get(item.identifier), source_namespace, source_name, source_revision)
        for item in critical
    ]
    incomplete_count = sum(resource["classification"] != "current_ready" for resource in resources)
    return {
        "age_seconds": age_seconds,
        "complete": incomplete_count == 0,
        "critical_kustomizations": resources,
        "incomplete_count": incomplete_count,
        "observed_at": format_utc_timestamp(observation_time),
        "schema_version": 1,
        "source": {
            "artifact_last_update_time": artifact_time,
            "kind": "GitRepository",
            "name": source_name,
            "namespace": source_namespace,
            "revision": source_revision,
        },
    }


def _observation_identity(observation: Mapping[str, Any]) -> tuple[dict[str, str], datetime, datetime]:
    if observation.get("schema_version") != 1:
        raise ObservationError("revision observation schema must be version 1")
    source = _mapping(observation.get("source"), "revision observation source")
    identity: dict[str, str] = {}
    for field in ("kind", "namespace", "name", "revision", "artifact_last_update_time"):
        value = _string(source.get(field))
        if value is None:
            raise ObservationError(f"revision observation source lacks {field}")
        identity[field] = value
    if not FULL_REVISION.fullmatch(identity["revision"]):
        raise ObservationError("revision observation requires a full SHA-1 revision")
    if (
        identity["kind"],
        identity["namespace"],
        identity["name"],
    ) != (M2_SOURCE_KIND, M2_SOURCE_NAMESPACE, M2_SOURCE_NAME):
        raise ObservationError("revision observation source must be GitRepository flux-system/flux-system")
    observed_value = _string(observation.get("observed_at"))
    if observed_value is None:
        raise ObservationError("revision observation lacks observed_at")
    start = parse_utc_timestamp(identity["artifact_last_update_time"])
    observed = parse_utc_timestamp(observed_value)
    if observed < start:
        raise ObservationError("revision observation precedes the source event")
    return identity, start, observed


def _sanitized_critical_evidence(observation: Mapping[str, Any]) -> list[dict[str, str]]:
    resources = observation.get("critical_kustomizations")
    if not isinstance(resources, list):
        raise ObservationError("revision observation lacks critical Kustomizations")
    evidence: list[dict[str, str]] = []
    for resource in resources:
        item = _mapping(resource, "critical Kustomization observation")
        namespace = _string(item.get("namespace"))
        name = _string(item.get("name"))
        classification = _string(item.get("classification"))
        if namespace is None or name is None or classification is None:
            raise ObservationError("critical Kustomization observation lacks identity or classification")
        if classification not in CRITICAL_CLASSIFICATIONS:
            raise ObservationError("critical Kustomization observation has an invalid classification")
        evidence.append(
            {
                "classification": classification,
                "name": name,
                "namespace": namespace,
            }
        )
    expected = [item.identifier for item in DEFAULT_CRITICAL_KUSTOMIZATIONS]
    actual = [f"{item['namespace']}/{item['name']}" for item in evidence]
    if actual != expected:
        raise ObservationError("revision observation does not match the fixed critical scope")
    return evidence


def _observation_is_complete(observation: Mapping[str, Any], evidence: Sequence[Mapping[str, str]]) -> bool:
    incomplete_count = _integer(observation.get("incomplete_count"))
    if incomplete_count is None or incomplete_count < 0:
        raise ObservationError("revision observation has an invalid incomplete count")
    classified_incomplete = sum(item["classification"] != "current_ready" for item in evidence)
    if classified_incomplete != incomplete_count:
        raise ObservationError("revision observation incomplete count does not match its evidence")
    complete = observation.get("complete")
    if not isinstance(complete, bool) or complete != (incomplete_count == 0):
        raise ObservationError("revision observation complete state is inconsistent")
    return complete


def new_revision_record(observation: Mapping[str, Any]) -> dict[str, Any]:
    """Create one immutable-start revision record from an observer snapshot."""

    source, start, observed = _observation_identity(observation)
    evidence = _sanitized_critical_evidence(observation)
    complete = _observation_is_complete(observation, evidence)
    if complete:
        raise ObservationError("revision records must start incomplete")
    initial_incomplete_count = sum(item["classification"] != "current_ready" for item in evidence)
    observed_at = format_utc_timestamp(observed)
    return {
        "critical_kustomizations": [dict(item) for item in evidence],
        "duration_seconds": None,
        "duration_semantics": "first_observed_complete_upper_bound",
        "first_observed_at": observed_at,
        "initial_critical_kustomizations": evidence,
        "initial_incomplete_count": initial_incomplete_count,
        "last_observed_at": observed_at,
        "revision": source["revision"],
        "schema_version": REVISION_RECORD_SCHEMA_VERSION,
        "source": source,
        "start_event_time": format_utc_timestamp(start),
        "status": "incomplete",
        "stop_event_time": None,
    }


def update_revision_record(record: Mapping[str, Any], observation: Mapping[str, Any]) -> dict[str, Any]:
    """Advance one incomplete record with a later snapshot of the same revision."""

    validated = _validated_revision_record(record)
    if validated["status"] == "complete":
        raise ObservationError("complete revision records are immutable")
    source, start, observed = _observation_identity(observation)
    if source != validated["source"] or format_utc_timestamp(start) != validated["start_event_time"]:
        raise ObservationError("revision record and observation source identities differ")
    last_observed = parse_utc_timestamp(str(validated["last_observed_at"]))
    if observed <= last_observed:
        raise ObservationError("revision observations must advance in time")
    evidence = _sanitized_critical_evidence(observation)
    complete = _observation_is_complete(observation, evidence)
    result = dict(validated)
    result["critical_kustomizations"] = evidence
    result["last_observed_at"] = format_utc_timestamp(observed)
    if complete:
        result["duration_seconds"] = int((observed - start).total_seconds())
        result["status"] = "complete"
        result["stop_event_time"] = format_utc_timestamp(observed)
    return result


def _validated_revision_record(record: Mapping[str, Any]) -> dict[str, Any]:
    if record.get("schema_version") != REVISION_RECORD_SCHEMA_VERSION:
        raise ObservationError("revision record schema must be version 1")
    source = _mapping(record.get("source"), "revision record source")
    for field in ("kind", "namespace", "name", "artifact_last_update_time"):
        if _string(source.get(field)) is None:
            raise ObservationError(f"revision record source lacks {field}")
    if (
        source["kind"],
        source["namespace"],
        source["name"],
    ) != (M2_SOURCE_KIND, M2_SOURCE_NAMESPACE, M2_SOURCE_NAME):
        raise ObservationError("revision record source must be GitRepository flux-system/flux-system")
    revision = _string(record.get("revision"))
    if revision is None or not FULL_REVISION.fullmatch(revision) or source.get("revision") != revision:
        raise ObservationError("revision record requires one full source revision")
    critical = record.get("critical_kustomizations")
    if not isinstance(critical, list):
        raise ObservationError("revision record lacks critical evidence")
    expected = [item.identifier for item in DEFAULT_CRITICAL_KUSTOMIZATIONS]
    actual = [
        f"{item.get('namespace')}/{item.get('name')}"
        for item in critical
        if isinstance(item, Mapping)
    ]
    if actual != expected:
        raise ObservationError("revision record does not match the fixed critical scope")
    classifications = [
        _string(item.get("classification"))
        for item in critical
        if isinstance(item, Mapping)
    ]
    if len(classifications) != len(expected) or any(value is None for value in classifications):
        raise ObservationError("revision record critical evidence lacks classifications")
    if any(value not in CRITICAL_CLASSIFICATIONS for value in classifications):
        raise ObservationError("revision record critical evidence has an invalid classification")
    classified_incomplete = sum(value != "current_ready" for value in classifications)
    initial_critical = record.get("initial_critical_kustomizations")
    if not isinstance(initial_critical, list):
        raise ObservationError("revision record lacks initial critical evidence")
    initial_actual = [
        f"{item.get('namespace')}/{item.get('name')}"
        for item in initial_critical
        if isinstance(item, Mapping)
    ]
    if initial_actual != expected:
        raise ObservationError("revision record initial evidence does not match the fixed critical scope")
    initial_classifications = [
        _string(item.get("classification"))
        for item in initial_critical
        if isinstance(item, Mapping)
    ]
    if len(initial_classifications) != len(expected) or any(value is None for value in initial_classifications):
        raise ObservationError("revision record initial evidence lacks classifications")
    if any(value not in CRITICAL_CLASSIFICATIONS for value in initial_classifications):
        raise ObservationError("revision record initial evidence has an invalid classification")
    initial_incomplete_count = _integer(record.get("initial_incomplete_count"))
    if initial_incomplete_count is None or initial_incomplete_count <= 0:
        raise ObservationError("revision record initial evidence must be incomplete")
    if sum(value != "current_ready" for value in initial_classifications) != initial_incomplete_count:
        raise ObservationError("revision record initial incomplete count does not match its evidence")
    status = record.get("status")
    duration = record.get("duration_seconds")
    stop = record.get("stop_event_time")
    if status == "complete":
        if not isinstance(duration, int) or isinstance(duration, bool) or duration < 0 or not isinstance(stop, str):
            raise ObservationError("complete revision record lacks a valid duration or stop event")
        if classified_incomplete:
            raise ObservationError("complete revision record contains incomplete critical evidence")
    elif status == "incomplete":
        if duration is not None or stop is not None:
            raise ObservationError("incomplete revision record cannot have a duration or stop event")
        if classified_incomplete == 0:
            raise ObservationError("incomplete revision record lacks incomplete critical evidence")
    else:
        raise ObservationError("revision record has an invalid status")
    start = parse_utc_timestamp(str(record.get("start_event_time")))
    if parse_utc_timestamp(str(source["artifact_last_update_time"])) != start:
        raise ObservationError("revision record start does not match the source event")
    first = parse_utc_timestamp(str(record.get("first_observed_at")))
    last = parse_utc_timestamp(str(record.get("last_observed_at")))
    if first < start or last < first:
        raise ObservationError("revision record times are out of order")
    if status == "complete":
        parsed_stop = parse_utc_timestamp(str(stop))
        if first >= last:
            raise ObservationError("complete revision record must advance beyond its first observation")
        if parsed_stop != last:
            raise ObservationError("complete revision record stop must equal its last observation")
        if int((parsed_stop - start).total_seconds()) != duration:
            raise ObservationError("complete revision record duration does not match its events")
    if record.get("duration_semantics") != "first_observed_complete_upper_bound":
        raise ObservationError("revision record has unsupported duration semantics")
    return dict(record)


def _validated_v2_evidence(value: object, description: str) -> tuple[list[dict[str, str]], int]:
    if not isinstance(value, list):
        raise ObservationError(f"{description} must be a list")
    evidence: list[dict[str, str]] = []
    for raw_item in value:
        item = _mapping(raw_item, description)
        if set(item) != {"classification", "name", "namespace"}:
            raise ObservationError(f"{description} contains unsupported fields")
        classification = _string(item.get("classification"))
        name = _string(item.get("name"))
        namespace = _string(item.get("namespace"))
        if classification not in CRITICAL_CLASSIFICATIONS or name is None or namespace is None:
            raise ObservationError(f"{description} contains invalid evidence")
        evidence.append({"classification": classification, "name": name, "namespace": namespace})
    expected = [item.identifier for item in DEFAULT_CRITICAL_KUSTOMIZATIONS]
    actual = [f"{item['namespace']}/{item['name']}" for item in evidence]
    if actual != expected:
        raise ObservationError(f"{description} does not match the fixed critical scope")
    return evidence, sum(item["classification"] != "current_ready" for item in evidence)


def _canonical_v2_source(source: Mapping[str, Any], start: datetime) -> dict[str, str]:
    expected_fields = {"artifact_last_update_time", "kind", "name", "namespace", "revision"}
    if set(source) != expected_fields:
        raise ObservationError("revision record source contains unsupported fields")
    result: dict[str, str] = {}
    for field in expected_fields:
        value = _string(source.get(field))
        if value is None:
            raise ObservationError(f"revision record source lacks {field}")
        result[field] = value
    if (result["kind"], result["namespace"], result["name"]) != (
        M2_SOURCE_KIND,
        M2_SOURCE_NAMESPACE,
        M2_SOURCE_NAME,
    ):
        raise ObservationError("revision record source must be GitRepository flux-system/flux-system")
    if not FULL_REVISION.fullmatch(result["revision"]):
        raise ObservationError("revision record requires one full source revision")
    result["artifact_last_update_time"] = format_exact_utc_timestamp(start)
    return result


def new_revision_record_v2(observation: Mapping[str, Any]) -> dict[str, Any]:
    """Create a v2 record from the first observed state of one revision."""

    raw_source, start, observed = _observation_identity(observation)
    evidence = _sanitized_critical_evidence(observation)
    complete = _observation_is_complete(observation, evidence)
    source = _canonical_v2_source(raw_source, start)
    observed_at = format_exact_utc_timestamp(observed)
    start_at = format_exact_utc_timestamp(start)
    initial_incomplete_count = sum(item["classification"] != "current_ready" for item in evidence)
    result = {
        "admission": "complete_first" if complete else "incomplete_first",
        "critical_kustomizations": [dict(item) for item in evidence],
        "duration_seconds": ceil((observed - start).total_seconds()) if complete else None,
        "duration_semantics": "first_observed_complete_upper_bound",
        "first_observed_at": observed_at,
        "initial_critical_kustomizations": [dict(item) for item in evidence],
        "initial_incomplete_count": initial_incomplete_count,
        "last_observed_at": observed_at,
        "revision": source["revision"],
        "schema_version": REVISION_RECORD_V2_SCHEMA_VERSION,
        "source": source,
        "start_event_time": start_at,
        "status": "complete" if complete else "incomplete",
        "stop_event_time": observed_at if complete else None,
    }
    return _validated_revision_record_v2(result)


def update_revision_record_v2(record: Mapping[str, Any], observation: Mapping[str, Any]) -> dict[str, Any]:
    """Advance one v2 incomplete record with a later exact-revision observation."""

    validated = _validated_revision_record_v2(record)
    if validated["status"] == "complete":
        raise ObservationError("complete revision records are immutable")
    raw_source, start, observed = _observation_identity(observation)
    source = _canonical_v2_source(raw_source, start)
    if source != validated["source"] or format_exact_utc_timestamp(start) != validated["start_event_time"]:
        raise ObservationError("revision record and observation source identities differ")
    last_observed = parse_utc_timestamp(str(validated["last_observed_at"]))
    if observed <= last_observed:
        raise ObservationError("revision observations must advance in time")
    evidence = _sanitized_critical_evidence(observation)
    complete = _observation_is_complete(observation, evidence)
    result = dict(validated)
    result["critical_kustomizations"] = [dict(item) for item in evidence]
    result["last_observed_at"] = format_exact_utc_timestamp(observed)
    if complete:
        result["duration_seconds"] = ceil((observed - start).total_seconds())
        result["status"] = "complete"
        result["stop_event_time"] = format_exact_utc_timestamp(observed)
    return _validated_revision_record_v2(result)


def _validated_revision_record_v2(record: Mapping[str, Any]) -> dict[str, Any]:
    expected_fields = {
        "admission",
        "critical_kustomizations",
        "duration_seconds",
        "duration_semantics",
        "first_observed_at",
        "initial_critical_kustomizations",
        "initial_incomplete_count",
        "last_observed_at",
        "revision",
        "schema_version",
        "source",
        "start_event_time",
        "status",
        "stop_event_time",
    }
    if set(record) != expected_fields or record.get("schema_version") != REVISION_RECORD_V2_SCHEMA_VERSION:
        raise ObservationError("revision record must use the exact version 2 schema")
    source_value = _mapping(record.get("source"), "revision record source")
    source_time_value = _string(source_value.get("artifact_last_update_time"))
    if source_time_value is None:
        raise ObservationError("revision record source lacks artifact update time")
    source_time = parse_utc_timestamp(source_time_value)
    source = _canonical_v2_source(source_value, source_time)
    if source_time_value != source["artifact_last_update_time"]:
        raise ObservationError("revision record source timestamp is not canonical")
    revision = _string(record.get("revision"))
    if revision != source["revision"]:
        raise ObservationError("revision record source revision differs")

    current_evidence, current_incomplete = _validated_v2_evidence(
        record.get("critical_kustomizations"), "revision record evidence"
    )
    initial_evidence, initial_incomplete = _validated_v2_evidence(
        record.get("initial_critical_kustomizations"), "revision record initial evidence"
    )
    recorded_initial_count = _integer(record.get("initial_incomplete_count"))
    if recorded_initial_count is None or recorded_initial_count != initial_incomplete:
        raise ObservationError("revision record initial incomplete count does not match its evidence")

    timestamps: dict[str, datetime] = {}
    for field in ("start_event_time", "first_observed_at", "last_observed_at"):
        value = _string(record.get(field))
        if value is None:
            raise ObservationError(f"revision record lacks {field}")
        parsed = parse_utc_timestamp(value)
        if value != format_exact_utc_timestamp(parsed):
            raise ObservationError("revision record timestamp is not canonical")
        timestamps[field] = parsed
    if timestamps["start_event_time"] != source_time:
        raise ObservationError("revision record start does not match the source event")
    if timestamps["first_observed_at"] < source_time or timestamps["last_observed_at"] < timestamps["first_observed_at"]:
        raise ObservationError("revision record times are out of order")

    admission = record.get("admission")
    status = record.get("status")
    duration = record.get("duration_seconds")
    stop_value = record.get("stop_event_time")
    if record.get("duration_semantics") != "first_observed_complete_upper_bound":
        raise ObservationError("revision record has unsupported duration semantics")
    if admission == "incomplete_first":
        if initial_incomplete <= 0:
            raise ObservationError("incomplete-first record lacks incomplete initial evidence")
    elif admission == "complete_first":
        if initial_incomplete != 0 or current_incomplete != 0 or status != "complete":
            raise ObservationError("complete-first record lacks complete initial evidence")
    else:
        raise ObservationError("revision record has an invalid admission")

    if status == "incomplete":
        if admission != "incomplete_first" or current_incomplete == 0 or duration is not None or stop_value is not None:
            raise ObservationError("incomplete revision record has inconsistent state")
    elif status == "complete":
        if current_incomplete != 0 or not isinstance(duration, int) or isinstance(duration, bool) or duration < 0:
            raise ObservationError("complete revision record lacks complete evidence or duration")
        if not isinstance(stop_value, str):
            raise ObservationError("complete revision record lacks a stop event")
        stop = parse_utc_timestamp(stop_value)
        if stop_value != format_exact_utc_timestamp(stop) or stop != timestamps["last_observed_at"]:
            raise ObservationError("complete revision record stop is invalid")
        if ceil((stop - source_time).total_seconds()) != duration:
            raise ObservationError("complete revision record duration does not match its events")
        if admission == "complete_first" and timestamps["first_observed_at"] != timestamps["last_observed_at"]:
            raise ObservationError("complete-first record must stop at its first observation")
        if admission == "incomplete_first" and timestamps["first_observed_at"] >= timestamps["last_observed_at"]:
            raise ObservationError("incomplete-first completion must advance beyond its first observation")
    else:
        raise ObservationError("revision record has an invalid status")

    result = dict(record)
    result["source"] = source
    result["critical_kustomizations"] = current_evidence
    result["initial_critical_kustomizations"] = initial_evidence
    return result


def aggregate_revision_records_v2(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate the newest 30 validated v2 records."""

    validated = [_validated_revision_record_v2(record) for record in records]
    revisions = [str(record["revision"]) for record in validated]
    if len(set(revisions)) != len(revisions):
        raise ObservationError("revision record set has duplicate revisions")
    start_times = [parse_utc_timestamp(str(record["start_event_time"])) for record in validated]
    if len(set(start_times)) != len(start_times):
        raise ObservationError("revision record set has tied source event times")
    newest = sorted(
        validated,
        key=lambda record: parse_utc_timestamp(str(record["start_event_time"])),
        reverse=True,
    )[:ROLLING_WINDOW_SIZE]
    incomplete_count = sum(record["status"] != "complete" for record in newest)
    eligible = len(newest) == ROLLING_WINDOW_SIZE and incomplete_count == 0
    durations = sorted(int(record["duration_seconds"]) for record in newest if record["status"] == "complete")
    return {
        "complete_count": len(newest) - incomplete_count,
        "eligible": eligible,
        "incomplete_count": incomplete_count,
        "maximum_seconds": max(durations) if eligible else None,
        "p50_seconds": _nearest_rank(durations, 0.50) if eligible else None,
        "p95_seconds": _nearest_rank(durations, 0.95) if eligible else None,
        "record_count": len(records),
        "record_schema_version": REVISION_RECORD_V2_SCHEMA_VERSION,
        "window_count": len(newest),
        "window_size": ROLLING_WINDOW_SIZE,
        "window_revisions": [record["revision"] for record in newest],
    }


def _nearest_rank(values: Sequence[int], quantile: float) -> int:
    return values[max(0, ceil(quantile * len(values)) - 1)]


def aggregate_revision_records(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate the newest exact-revision records without hiding incomplete entries."""

    validated = [_validated_revision_record(record) for record in records]
    revisions = [str(record["revision"]) for record in validated]
    if len(set(revisions)) != len(revisions):
        raise ObservationError("revision record set has duplicate revisions")
    start_times = [parse_utc_timestamp(str(record["start_event_time"])) for record in validated]
    if len(set(start_times)) != len(start_times):
        raise ObservationError("revision record set has tied source event times")
    newest = sorted(
        validated,
        key=lambda record: parse_utc_timestamp(str(record["start_event_time"])),
        reverse=True,
    )[:ROLLING_WINDOW_SIZE]
    incomplete_count = sum(record["status"] != "complete" for record in newest)
    eligible = len(newest) == ROLLING_WINDOW_SIZE and incomplete_count == 0
    durations = sorted(int(record["duration_seconds"]) for record in newest if record["status"] == "complete")
    return {
        "complete_count": len(newest) - incomplete_count,
        "eligible": eligible,
        "incomplete_count": incomplete_count,
        "maximum_seconds": max(durations) if eligible else None,
        "p50_seconds": _nearest_rank(durations, 0.50) if eligible else None,
        "p95_seconds": _nearest_rank(durations, 0.95) if eligible else None,
        "record_count": len(records),
        "schema_version": REVISION_RECORD_SCHEMA_VERSION,
        "window_count": len(newest),
        "window_size": ROLLING_WINDOW_SIZE,
        "window_revisions": [record["revision"] for record in newest],
    }
