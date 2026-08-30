"""Collect one final evidence report for an exact Spark Attempt."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any, Literal, TypeAlias


REPO = Path(__file__).resolve().parents[2]
CONTRACT_SOURCE = REPO / "images" / "flight-recorder-contract"
if str(CONTRACT_SOURCE) not in sys.path:
    sys.path.insert(0, str(CONTRACT_SOURCE))

from anton_flight_recorder_contract import (  # noqa: E402
    CHUNKS_PER_HOUR,
    COMPLETE_HOUR_ENTRY_LIMIT,
    COMPLETE_HOUR_KIND,
    COMPLETE_HOUR_MANIFEST_FIELDS,
    COMPLETE_HOUR_SCHEMA_VERSION,
    COMPLETE_HOUR_STATUS,
    COMPONENT_QUERIES,
    HOUR_SECONDS,
    MAX_COMPLETE_RAW_BYTES,
    SOURCE_MANIFEST_FIELDS,
    component_catalog_sha256,
    hour_manifest_key,
)
from airflow_lakehouse_operations import (  # noqa: E402
    AttemptObservationSource,
    KubectlClient,
    OperationError,
)
from lakehouse_trino import (  # noqa: E402
    FlightRecorderTrinoFacts,
    TrinoReadError,
    flight_recorder_facts_from_checks,
    read_flight_recorder_facts,
)


IMAGE_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
SOURCE_RECEIPT_FIELDS = SOURCE_MANIFEST_FIELDS | {"attempt", "manifest_key"}
HOUR_RECEIPT_FIELDS = (COMPLETE_HOUR_MANIFEST_FIELDS - {"sources"}) | {
    "attempt", "manifest_key", "manifest_sha256",
}
HOUR_REJECTION_FIELDS = frozenset({
    "source_hour_id", "attempt", "component", "chunk_index",
    "completed_queries", "complete_manifest_published",
})
COMPONENTS = frozenset(component for component, _query in COMPONENT_QUERIES)
TABLE_CONTRACTS = {
    "events": (
        (("fingerprint", "varchar"), ("event_timestamp", "timestamp(6) with time zone"),
         ("event_date", "date"), ("source_window_id", "varchar"),
         ("source_timestamp_ns", "varchar"), ("namespace", "varchar"),
         ("workload_kind", "varchar"), ("workload_name", "varchar"),
         ("pod_name", "varchar"), ("container_name", "varchar"),
         ("severity", "varchar"), ("redacted_preview", "varchar"),
         ("rejected", "boolean"), ("rejection_reason", "varchar"),
         ("source_component", "varchar"), ("source_chunk_id", "integer")),
        "event_date",
    ),
    "hourly": (
        (("hour", "timestamp(6) with time zone"), ("namespace", "varchar"),
         ("workload_kind", "varchar"), ("workload_name", "varchar"),
         ("severity", "varchar"), ("event_count", "bigint"),
         ("rejection_count", "bigint"), ("source_component", "varchar")),
        "day(hour)",
    ),
    "run_receipts": (
        (("source_window_id", "varchar"), ("raw_sha256", "varchar"),
         ("manifest_uri", "varchar"), ("raw_uri", "varchar"),
         ("source_count", "bigint"), ("accepted_count", "bigint"),
         ("rejected_count", "bigint"), ("final_event_count", "bigint"),
         ("spark_attempt", "varchar"), ("window_start", "timestamp(6) with time zone"),
         ("window_end", "timestamp(6) with time zone"),
         ("completed_at", "timestamp(6) with time zone"),
         ("completion_date", "date"), ("source_kind", "varchar"),
         ("complete_manifest_sha256", "varchar")),
        "completion_date",
    ),
    "component_counts": (
        (("source_window_id", "varchar"), ("source_component", "varchar"),
         ("source_count", "bigint"), ("accepted_count", "bigint"),
         ("rejected_count", "bigint"), ("deduplicated_count", "bigint"),
         ("written_count", "bigint"), ("completed_at", "timestamp(6) with time zone"),
         ("completion_date", "date")),
        "completion_date",
    ),
}
WORKFLOW_QUERY = '{k8s_namespace_name="airflow"}'
ReadTrinoFacts: TypeAlias = Callable[[Path], FlightRecorderTrinoFacts]


@dataclass(frozen=True, slots=True)
class LakehouseEvidenceRequest:
    """Request retained and live lakehouse evidence."""

    run_id: str
    try_number: int = 1
    target: Literal["shadow", "authoritative"] = "shadow"
    ledger_path: Path | None = None

    def __post_init__(self) -> None:
        if self.target not in {"shadow", "authoritative"}:
            raise OperationError(f"unsupported evidence target: {self.target}")


@dataclass(frozen=True, slots=True)
class FlightRecorderInitialEvidenceRequest:
    """Request initial Flight Recorder acceptance evidence."""

    run_id: str
    namespace_baseline_path: Path
    try_number: int = 1


@dataclass(frozen=True, slots=True)
class FlightRecorderReplayEvidenceRequest:
    """Request exact Flight Recorder replay evidence."""

    run_id: str
    baseline_path: Path
    try_number: int = 1


@dataclass(frozen=True, slots=True)
class FlightRecorderRejectionEvidenceRequest:
    """Request terminal Flight Recorder rejection evidence."""

    run_id: str
    try_number: int = 1


EvidenceRequest: TypeAlias = (
    LakehouseEvidenceRequest
    | FlightRecorderInitialEvidenceRequest
    | FlightRecorderReplayEvidenceRequest
    | FlightRecorderRejectionEvidenceRequest
)


def _parse_utc(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S.%f UTC").replace(
                tzinfo=timezone.utc,
            )
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _nanoseconds(value: datetime) -> int:
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    delta = value - epoch
    return (
        delta.days * 86_400_000_000_000
        + delta.seconds * 1_000_000_000
        + delta.microseconds * 1_000
    )


def _source_receipt(report: Mapping[str, object]) -> Mapping[str, object] | None:
    live = report.get("live")
    source = live.get("flight_recorder_source_loki") if isinstance(live, Mapping) else None
    hour_receipts = source.get("hour_receipts") if isinstance(source, Mapping) else None
    if (
        isinstance(hour_receipts, list)
        and len(hour_receipts) == 1
        and isinstance(hour_receipts[0], Mapping)
    ):
        return hour_receipts[0]
    receipts = source.get("source_receipts") if isinstance(source, Mapping) else None
    if not isinstance(receipts, list) or len(receipts) != 1 or not isinstance(receipts[0], Mapping):
        return None
    return receipts[0]


def _hour_rejection(report: Mapping[str, object]) -> Mapping[str, object] | None:
    live = report.get("live")
    source = live.get("flight_recorder_source_loki") if isinstance(live, Mapping) else None
    rejections = source.get("hour_rejections") if isinstance(source, Mapping) else None
    if not isinstance(rejections, list) or len(rejections) != 1 or not isinstance(rejections[0], Mapping):
        return None
    return rejections[0]


def _valid_hour_rejection(report: Mapping[str, object]) -> bool:
    identity = report.get("identity")
    live = report.get("live")
    rejection = _hour_rejection(report)
    if not isinstance(identity, Mapping) or not isinstance(live, Mapping) or rejection is None:
        return False
    source = live.get("flight_recorder_source_loki")
    if not isinstance(source, Mapping) or source.get("hour_receipts") or source.get("source_receipts"):
        return False
    if set(rejection) != HOUR_REJECTION_FIELDS:
        return False
    try:
        start_ns, end_ns = (
            int(value) for value in str(rejection.get("source_hour_id")).split("-", maxsplit=1)
        )
    except (TypeError, ValueError):
        return False
    component = rejection.get("component")
    chunk_index = rejection.get("chunk_index")
    completed = rejection.get("completed_queries")
    total_chunks = len(COMPONENTS) * CHUNKS_PER_HOUR
    component_failure = (
        isinstance(component, str)
        and component in COMPONENTS
        and type(chunk_index) is int
        and 0 <= chunk_index < CHUNKS_PER_HOUR
        and type(completed) is int
        and 0 <= completed < total_chunks
    )
    complete_failure = (
        component == "complete_manifest"
        and chunk_index == -1
        and completed == total_chunks
    )
    pods = live.get("pods")
    task_pods = live.get("airflow_task_pods")
    expected_digest = live.get("expected_airflow_digest")
    task_images_match = (
        isinstance(expected_digest, str)
        and IMAGE_DIGEST.fullmatch(expected_digest) is not None
        and isinstance(task_pods, list)
        and bool(task_pods)
        and all(
            isinstance(pod, Mapping)
            and isinstance(pod.get("requested_images"), list)
            and any(
                expected_digest in str(image)
                for image in pod["requested_images"]
            )
            and isinstance(pod.get("containers"), list)
            and any(
                isinstance(container, Mapping)
                and expected_digest in str(container.get("image_id"))
                for container in pod["containers"]
            )
            for pod in task_pods
        )
    )
    return (
        end_ns - start_ns == HOUR_SECONDS * 1_000_000_000
        and start_ns % (HOUR_SECONDS * 1_000_000_000) == 0
        and end_ns % (HOUR_SECONDS * 1_000_000_000) == 0
        and rejection.get("attempt") == identity.get("attempt_name")
        and rejection.get("complete_manifest_published") is False
        and (component_failure or complete_failure)
        and type(source.get("samples")) is int
        and int(source["samples"]) >= 1
        and live.get("spark_application") is None
        and live.get("lease_holder") is None
        and isinstance(pods, list)
        and not pods
        and task_images_match
        and all(
            isinstance(pod, Mapping) and pod.get("phase") not in {"Pending", "Running"}
            for pod in task_pods
        )
    )


def _valid_source_receipt(
    receipt: Mapping[str, object] | None,
    *,
    attempt: object,
    summary: Mapping[str, object],
) -> bool:
    if receipt is not None and receipt.get("kind") == COMPLETE_HOUR_KIND:
        if set(receipt) != HOUR_RECEIPT_FIELDS:
            return False
        start = _parse_utc(receipt.get("hour_start"))
        end = _parse_utc(receipt.get("hour_end"))
        checksum = receipt.get("manifest_sha256")
        if start is None or end is None or not isinstance(checksum, str):
            return False
        start_ns = _nanoseconds(start)
        end_ns = _nanoseconds(end)
        hour_id = f"{start_ns}-{end_ns}"
        try:
            expected_key = hour_manifest_key(
                start_ns=start_ns,
                end_ns=end_ns,
                checksum=checksum,
            )
        except ValueError:
            return False
        return (
            receipt.get("schema_version") == COMPLETE_HOUR_SCHEMA_VERSION
            and receipt.get("status") == COMPLETE_HOUR_STATUS
            and (end - start).total_seconds() == HOUR_SECONDS
            and not any((
                start.minute, start.second, start.microsecond,
                end.minute, end.second, end.microsecond,
            ))
            and receipt.get("source_hour_id") == hour_id
            and receipt.get("catalog_sha256") == component_catalog_sha256()
            and receipt.get("component_count") == len(COMPONENTS)
            and receipt.get("chunk_count") == len(COMPONENTS) * CHUNKS_PER_HOUR
            and type(receipt.get("source_count")) is int
            and 0 < int(receipt["source_count"])
            <= len(COMPONENTS) * CHUNKS_PER_HOUR * COMPLETE_HOUR_ENTRY_LIMIT
            and type(receipt.get("raw_bytes")) is int
            and 0 < int(receipt["raw_bytes"]) <= MAX_COMPLETE_RAW_BYTES
            and receipt.get("attempt") == attempt
            and receipt.get("manifest_key") == expected_key
            and summary.get("latest_source_window_id") == hour_id
            and summary.get("latest_complete_manifest_sha256") == checksum
            and summary.get("latest_source_kind") == "complete_hour"
            and summary.get("latest_source_count") == receipt.get("source_count")
        )
    if receipt is None or set(receipt) != SOURCE_RECEIPT_FIELDS:
        return False
    start = _parse_utc(receipt.get("window_start"))
    end = _parse_utc(receipt.get("window_end"))
    if start is None or end is None or end <= start:
        return False
    window_id = f"{_nanoseconds(start)}-{_nanoseconds(end)}"
    checksum = receipt.get("raw_sha256")
    return (
        receipt.get("schema_version") == 1
        and receipt.get("query") == WORKFLOW_QUERY
        and (end - start).total_seconds() == 300
        and type(receipt.get("entry_count")) is int
        and int(receipt["entry_count"]) > 0
        and type(receipt.get("raw_bytes")) is int
        and int(receipt["raw_bytes"]) > 0
        and isinstance(checksum, str)
        and re.fullmatch(r"[0-9a-f]{64}", checksum) is not None
        and receipt.get("attempt") == attempt
        and isinstance(receipt.get("raw_key"), str)
        and str(receipt["raw_key"]).startswith(f"flight-recorder/raw/{window_id}/")
        and isinstance(receipt.get("manifest_key"), str)
        and str(receipt["manifest_key"]).startswith(f"flight-recorder/manifests/{window_id}/")
        and summary.get("latest_source_window_id") == window_id
        and summary.get("latest_raw_sha256") == checksum
        and summary.get("latest_source_count") == receipt.get("entry_count")
    )


def _field(row: Mapping[str, object], name: str) -> object:
    return next((value for key, value in row.items() if str(key).lower() == name.lower()), None)


def _valid_contracts(results: Sequence[Sequence[object]]) -> bool:
    if len(results) != len(TABLE_CONTRACTS) * 2:
        return False
    for index, (table, (expected_columns, partition)) in enumerate(TABLE_CONTRACTS.items()):
        column_rows, ddl_rows = results[index * 2:index * 2 + 2]
        if len(ddl_rows) != 1:
            return False
        columns = tuple(
            (str(_field(row, "column") or "").lower(), str(_field(row, "type") or "").lower())
            for row in column_rows
            if isinstance(row, Mapping)
        )
        ddl_row = ddl_rows[0]
        ddl = str(next(iter(ddl_row.values()), "")) if isinstance(ddl_row, Mapping) else ""
        compact = re.sub(r"\s+", " ", ddl).lower()
        location = f"s3://iceberg-warehouse/flight_recorder/{table}"
        partition_pattern = (
            rf"partitioning\s*=\s*array\s*\[\s*['\"]{re.escape(partition)}['\"]\s*\]"
        )
        if (
            columns != expected_columns
            or f"iceberg.flight_recorder.{table}" not in compact
            or location not in compact
            or re.search(r"format_version\s*=\s*2", compact) is None
            or re.search(partition_pattern, compact) is None
        ):
            return False
    return True


def _valid_snapshots(results: Sequence[Sequence[object]]) -> bool:
    return (
        len(results) == len(TABLE_CONTRACTS)
        and all(
            bool(rows)
            and all(
                isinstance(row, Mapping)
                and row.get("snapshot_id") is not None
                and _parse_utc(row.get("committed_at")) is not None
                for row in rows
            )
            for rows in results
        )
    )


def _snapshot_identities(check: Mapping[str, object]) -> dict[str, object] | None:
    if check.get("check") != "flight-recorder-namespace-isolation":
        return None
    results = check.get("results")
    if not isinstance(results, list) or len(results) != 1:
        return None
    rows = results[0]
    if not isinstance(rows, list) or len(rows) != 2:
        return None
    identities: dict[str, object] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            return None
        table = row.get("table_name")
        committed = _parse_utc(row.get("committed_at"))
        if (
            not isinstance(table, str)
            or table not in {"normalized", "hourly"}
            or committed is None
            or row.get("snapshot_id") is None
        ):
            return None
        identities[str(table)] = row.get("snapshot_id")
    return identities if set(identities) == {"normalized", "hourly"} else None


def _namespace_isolated(
    current: Sequence[tuple[str, object, str]],
    baseline: Mapping[str, object] | None,
) -> bool:
    identities = {
        table: snapshot_id
        for table, snapshot_id, committed_at in current
        if (
            table in {"normalized", "hourly"}
            and snapshot_id is not None
            and _parse_utc(committed_at) is not None
        )
    }
    return (
        len(current) == 2
        and set(identities) == {"normalized", "hourly"}
        and baseline is not None
        and identities == _snapshot_identities(baseline)
    )


def _same_source(
    first: Mapping[str, object] | None,
    second: Mapping[str, object] | None,
) -> bool:
    if first is None or second is None:
        return False
    return {key: value for key, value in first.items() if key != "attempt"} == {
        key: value for key, value in second.items() if key != "attempt"
    }


def _valid_component_counts(
    rows: Sequence[Mapping[str, object]],
    summary: Mapping[str, object],
    source: Mapping[str, object] | None,
) -> bool:
    if len(rows) != len(COMPONENTS) or source is None:
        return False
    retained: dict[str, Mapping[str, object]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            return False
        component = row.get("source_component")
        if not isinstance(component, str) or component not in COMPONENTS:
            return False
        if component in retained or row.get("source_window_id") != source.get("source_hour_id"):
            return False
        values = tuple(row.get(name) for name in (
            "source_count", "accepted_count", "rejected_count",
            "deduplicated_count", "written_count",
        ))
        if any(type(value) is not int or value < 0 for value in values):
            return False
        source_count, accepted, rejected, deduplicated, written = values
        if source_count != accepted + rejected or deduplicated != written:
            return False
        retained[component] = row
    return (
        set(retained) == COMPONENTS
        and sum(int(row["source_count"]) for row in retained.values())
        == summary.get("latest_source_count")
        and sum(int(row["accepted_count"]) for row in retained.values())
        == summary.get("latest_accepted_count")
        and sum(int(row["rejected_count"]) for row in retained.values())
        == summary.get("latest_rejected_count")
        and sum(int(row["written_count"]) for row in retained.values())
        == summary.get("latest_final_event_count")
    )


def _valid_summary(summary: Mapping[str, object]) -> bool:
    count_names = (
        "latest_source_count",
        "latest_accepted_count",
        "latest_rejected_count",
        "latest_final_event_count",
        "event_count",
        "hourly_event_count_sum",
        "rejected_count",
        "hourly_rejection_count_sum",
        "receipt_count",
    )
    counts = {name: summary.get(name) for name in count_names}
    if any(type(value) is not int or value < 0 for value in counts.values()):
        return False
    receipt_count = summary.get("receipt_count")
    return (
        counts["latest_source_count"]
        == counts["latest_accepted_count"] + counts["latest_rejected_count"]
        and (
            summary.get("latest_source_kind") == "complete_hour"
            or counts["latest_source_count"] == counts["latest_final_event_count"]
        )
        and counts["event_count"] == counts["hourly_event_count_sum"]
        and counts["rejected_count"] == counts["hourly_rejection_count_sum"]
        and receipt_count >= 1
    )


def _read_mapping(path: Path, description: str) -> Mapping[str, object]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise OperationError(f"{description} could not be read: {path}") from error
    if not isinstance(document, Mapping):
        raise OperationError(f"{description} must be a JSON object: {path}")
    return document


def _semantic_replay_matches(
    baseline: Mapping[str, object],
    current: FlightRecorderTrinoFacts,
) -> bool:
    raw = baseline.get("trino")
    if not isinstance(raw, Mapping) or any(
        not isinstance(name, str) or not isinstance(check, Mapping)
        for name, check in raw.items()
    ):
        return False
    try:
        retained = flight_recorder_facts_from_checks(raw)  # type: ignore[arg-type]
    except TrinoReadError:
        return False
    return retained.comparison_key == current.comparison_key


def _evaluate_flight_recorder_rejection(
    base: Mapping[str, object],
) -> dict[str, Any]:
    report = deepcopy(dict(base))
    rejection = _hour_rejection(report)
    report["trino"] = {}
    if rejection is None:
        report["missing"] = ["flight_recorder_hour_rejection"]
        report["status"] = "incomplete"
        return report
    report["rejection"] = dict(rejection)
    report["missing"] = [] if _valid_hour_rejection(report) else [
        "flight_recorder_hour_rejection",
    ]
    report["status"] = "rejected" if not report["missing"] else "incomplete"
    return report


def _evaluate_lakehouse_report(base: Mapping[str, object]) -> dict[str, Any]:
    report = deepcopy(dict(base))
    missing = report.get("missing")
    if not isinstance(missing, list):
        raise OperationError("Spark Attempt observations have invalid missing checks")
    report["status"] = "complete" if not missing else "incomplete"
    return report


def _evaluate_flight_recorder_report(
    base: Mapping[str, object],
    facts: FlightRecorderTrinoFacts,
    *,
    namespace_baseline: Mapping[str, object] | None = None,
    namespace_baseline_path: Path | None = None,
    replay_baseline: Mapping[str, object] | None = None,
    replay_baseline_path: Path | None = None,
) -> dict[str, Any]:
    report = deepcopy(dict(base))
    trino = deepcopy(dict(facts.raw_checks))
    report["trino"] = trino
    missing = [
        item
        for item in report.get("missing", [])
        if not str(item).startswith("flight_recorder_")
    ]
    summary = facts.summary
    if not _valid_summary(summary):
        missing.append("flight_recorder_trino_consistency")
    if not _valid_contracts(facts.table_contract):
        missing.append("flight_recorder_table_contract")
    if not _valid_snapshots(facts.table_snapshots):
        missing.append("flight_recorder_snapshots")
    identity = report.get("identity") if isinstance(report.get("identity"), Mapping) else {}
    receipt = _source_receipt(report)
    if not _valid_source_receipt(
        receipt,
        attempt=identity.get("attempt_name"),
        summary=summary,
    ):
        missing.append("flight_recorder_source_receipt")
    if (
        receipt is not None
        and receipt.get("kind") == COMPLETE_HOUR_KIND
        and not _valid_component_counts(
            facts.component_counts,
            summary,
            receipt,
        )
    ):
        missing.append("flight_recorder_component_counts")

    if replay_baseline is None:
        if not _namespace_isolated(
            facts.namespace_snapshots,
            namespace_baseline,
        ):
            missing.append("flight_recorder_namespace_isolation")
        elif namespace_baseline_path is not None:
            report["namespace_baseline"] = str(namespace_baseline_path)
        if summary.get("latest_spark_attempt") != identity.get("attempt_name"):
            missing.append("flight_recorder_receipt_identity")
    else:
        baseline_identity = replay_baseline.get("identity")
        if (
            not isinstance(baseline_identity, Mapping)
            or baseline_identity.get("dag_id") != "airflow_flight_recorder"
        ):
            raise OperationError("baseline is not Flight Recorder evidence")
        if replay_baseline.get("status") != "complete" or replay_baseline.get("missing"):
            raise OperationError("baseline Flight Recorder evidence is not complete")
        if baseline_identity.get("run_id") == identity.get("run_id"):
            raise OperationError("replay evidence requires a new Workflow Run ID")
        if not _same_source(_source_receipt(replay_baseline), receipt):
            missing.append("flight_recorder_replay_source_changed")
        if not _semantic_replay_matches(replay_baseline, facts):
            missing.append("flight_recorder_replay_changed_state")
        if replay_baseline_path is not None:
            report["replay_baseline"] = str(replay_baseline_path)

    report["missing"] = sorted(set(missing))
    report["status"] = "complete" if not report["missing"] else "incomplete"
    return report


def collect_spark_attempt_evidence(
    request: EvidenceRequest,
    *,
    kubectl: KubectlClient,
    root: Path,
    expected_airflow_digest: str | None = None,
    read_trino_facts: ReadTrinoFacts = read_flight_recorder_facts,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Collect one complete report without caller-side result assembly."""
    observations = AttemptObservationSource(kubectl)
    if isinstance(request, LakehouseEvidenceRequest):
        return _evaluate_lakehouse_report(
            observations.lakehouse(
                run_id=request.run_id,
                try_number=request.try_number,
                target=request.target,
                ledger_path=request.ledger_path,
                now=now,
            ),
        )

    if IMAGE_DIGEST.fullmatch(str(expected_airflow_digest or "")) is None:
        raise OperationError("Flight Recorder evidence requires an Airflow image digest")
    base = observations.flight_recorder(
        run_id=request.run_id,
        try_number=request.try_number,
        expected_airflow_digest=str(expected_airflow_digest),
        now=now,
    )

    if isinstance(request, FlightRecorderRejectionEvidenceRequest):
        return _evaluate_flight_recorder_rejection(base)

    facts = read_trino_facts(root)
    if isinstance(request, FlightRecorderReplayEvidenceRequest):
        baseline = _read_mapping(request.baseline_path, "Flight Recorder baseline")
        return _evaluate_flight_recorder_report(
            base,
            facts,
            replay_baseline=baseline,
            replay_baseline_path=request.baseline_path,
        )
    namespace_baseline = _read_mapping(
        request.namespace_baseline_path,
        "namespace baseline",
    )
    return _evaluate_flight_recorder_report(
        base,
        facts,
        namespace_baseline=namespace_baseline,
        namespace_baseline_path=request.namespace_baseline_path,
    )
