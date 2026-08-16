"""Validate retained Flight Recorder evidence."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

from airflow_lakehouse_operations import OperationError
from lakehouse_trino import run_check


SOURCE_RECEIPT_FIELDS = frozenset({
    "schema_version", "query", "window_start", "window_end", "entry_count",
    "raw_bytes", "raw_key", "raw_sha256", "attempt", "manifest_key",
})
HOUR_RECEIPT_FIELDS = frozenset({
    "schema_version", "kind", "status", "hour_start", "hour_end", "source_hour_id",
    "catalog_sha256", "component_count", "chunk_count", "source_count", "raw_bytes",
    "attempt", "manifest_key", "manifest_sha256",
})
HOUR_REJECTION_FIELDS = frozenset({
    "source_hour_id", "attempt", "component", "chunk_index",
    "completed_queries", "complete_manifest_published",
})
COMPONENTS = {"workflow", "spark_operator", "trino", "seaweedfs"}
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
TRINO_CHECKS = (
    "flight-recorder-summary",
    "flight-recorder-contract",
    "flight-recorder-snapshots",
    "flight-recorder-components",
    "flight-recorder-namespace-isolation",
)
WORKFLOW_QUERY = '{k8s_namespace_name="airflow"}'
IMAGE_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
RunCheck = Callable[[Path, str], dict[str, object]]


def _parse_utc(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S.%f UTC").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _nanoseconds(value: datetime) -> int:
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    delta = value - epoch
    return delta.days * 86_400_000_000_000 + delta.seconds * 1_000_000_000 + delta.microseconds * 1_000


def _one_row(check: Mapping[str, object]) -> Mapping[str, object]:
    results = check.get("results")
    if not isinstance(results, list) or len(results) != 1:
        return {}
    rows = results[0]
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], Mapping):
        return {}
    return rows[0]


def _source_receipt(result: Mapping[str, object]) -> Mapping[str, object] | None:
    live = result.get("live")
    source = live.get("flight_recorder_source_loki") if isinstance(live, Mapping) else None
    hour_receipts = source.get("hour_receipts") if isinstance(source, Mapping) else None
    if isinstance(hour_receipts, list) and len(hour_receipts) == 1 and isinstance(hour_receipts[0], Mapping):
        return hour_receipts[0]
    receipts = source.get("source_receipts") if isinstance(source, Mapping) else None
    if not isinstance(receipts, list) or len(receipts) != 1 or not isinstance(receipts[0], Mapping):
        return None
    return receipts[0]


def _hour_rejection(result: Mapping[str, object]) -> Mapping[str, object] | None:
    live = result.get("live")
    source = live.get("flight_recorder_source_loki") if isinstance(live, Mapping) else None
    rejections = source.get("hour_rejections") if isinstance(source, Mapping) else None
    if not isinstance(rejections, list) or len(rejections) != 1 or not isinstance(rejections[0], Mapping):
        return None
    return rejections[0]


def _valid_hour_rejection(result: Mapping[str, object]) -> bool:
    identity = result.get("identity")
    live = result.get("live")
    rejection = _hour_rejection(result)
    if not isinstance(identity, Mapping) or not isinstance(live, Mapping) or rejection is None:
        return False
    source = live.get("flight_recorder_source_loki")
    if not isinstance(source, Mapping) or source.get("hour_receipts") or source.get("source_receipts"):
        return False
    if set(rejection) != HOUR_REJECTION_FIELDS:
        return False
    hour_id = rejection.get("source_hour_id")
    try:
        start_ns, end_ns = (int(value) for value in str(hour_id).split("-", maxsplit=1))
    except (TypeError, ValueError):
        return False
    component = rejection.get("component")
    chunk_index = rejection.get("chunk_index")
    completed = rejection.get("completed_queries")
    component_failure = (
        component in COMPONENTS
        and type(chunk_index) is int and 0 <= chunk_index < 12
        and type(completed) is int and 0 <= completed < 48
    )
    complete_failure = component == "complete_manifest" and chunk_index == -1 and completed == 48
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
            and any(expected_digest in str(image) for image in pod.get("requested_images", []))
            and any(
                isinstance(container, Mapping)
                and expected_digest in str(container.get("image_id"))
                for container in pod.get("containers", [])
            )
            for pod in task_pods
        )
    )
    return (
        end_ns - start_ns == 3_600_000_000_000
        and start_ns % 3_600_000_000_000 == 0
        and end_ns % 3_600_000_000_000 == 0
        and rejection.get("attempt") == identity.get("attempt_name")
        and rejection.get("complete_manifest_published") is False
        and (component_failure or complete_failure)
        and type(source.get("samples")) is int and int(source["samples"]) >= 1
        and live.get("spark_application") is None
        and live.get("lease_holder") is None
        and isinstance(pods, list) and not pods
        and task_images_match
        and all(isinstance(pod, Mapping) and pod.get("phase") not in {"Pending", "Running"} for pod in task_pods)
    )


def _valid_source_receipt(
    receipt: Mapping[str, object] | None,
    *,
    attempt: object,
    summary: Mapping[str, object],
) -> bool:
    if receipt is not None and receipt.get("kind") == "flight_recorder_complete_hour":
        if set(receipt) != HOUR_RECEIPT_FIELDS:
            return False
        start = _parse_utc(receipt.get("hour_start"))
        end = _parse_utc(receipt.get("hour_end"))
        if start is None or end is None:
            return False
        hour_id = f"{_nanoseconds(start)}-{_nanoseconds(end)}"
        checksum = receipt.get("manifest_sha256")
        return (
            receipt.get("schema_version") == 2 and receipt.get("status") == "complete"
            and (end - start).total_seconds() == 3600
            and not any((start.minute, start.second, start.microsecond,
                         end.minute, end.second, end.microsecond))
            and receipt.get("source_hour_id") == hour_id
            and receipt.get("component_count") == 4 and receipt.get("chunk_count") == 48
            and type(receipt.get("source_count")) is int and int(receipt["source_count"]) > 0
            and type(receipt.get("raw_bytes")) is int and int(receipt["raw_bytes"]) > 0
            and isinstance(receipt.get("catalog_sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("catalog_sha256"))) is not None
            and isinstance(checksum, str) and re.fullmatch(r"[0-9a-f]{64}", checksum) is not None
            and receipt.get("attempt") == attempt
            and receipt.get("manifest_key")
            == f"flight-recorder/hours/{hour_id}/{checksum}.complete.json"
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
        and type(receipt.get("entry_count")) is int and int(receipt["entry_count"]) > 0
        and type(receipt.get("raw_bytes")) is int and int(receipt["raw_bytes"]) > 0
        and isinstance(checksum, str) and re.fullmatch(r"[0-9a-f]{64}", checksum) is not None
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


def _valid_contracts(check: Mapping[str, object]) -> bool:
    results = check.get("results")
    if not isinstance(results, list) or len(results) != len(TABLE_CONTRACTS) * 2:
        return False
    for index, (table, (expected_columns, partition)) in enumerate(TABLE_CONTRACTS.items()):
        column_rows, ddl_rows = results[index * 2:index * 2 + 2]
        if not isinstance(column_rows, list) or not isinstance(ddl_rows, list) or len(ddl_rows) != 1:
            return False
        columns = tuple(
            (str(_field(row, "column") or "").lower(), str(_field(row, "type") or "").lower())
            for row in column_rows if isinstance(row, Mapping)
        )
        ddl_row = ddl_rows[0]
        ddl = str(next(iter(ddl_row.values()), "")) if isinstance(ddl_row, Mapping) else ""
        compact = re.sub(r"\s+", " ", ddl).lower()
        location = f"s3://iceberg-warehouse/flight_recorder/{table}"
        if columns != expected_columns:
            return False
        if f"iceberg.flight_recorder.{table}" not in compact or location not in compact:
            return False
        if re.search(r"format_version\s*=\s*2", compact) is None:
            return False
        partition_pattern = rf"partitioning\s*=\s*array\s*\[\s*['\"]{re.escape(partition)}['\"]\s*\]"
        if re.search(partition_pattern, compact) is None:
            return False
    return True


def _valid_snapshots(check: Mapping[str, object]) -> bool:
    results = check.get("results")
    return (
        isinstance(results, list) and len(results) == len(TABLE_CONTRACTS)
        and all(
            isinstance(rows, list) and bool(rows)
            and all(isinstance(row, Mapping) and row.get("snapshot_id") is not None
                    and _parse_utc(row.get("committed_at")) is not None for row in rows)
            for rows in results
        )
    )


def _snapshot_identities(check: Mapping[str, object]) -> dict[str, object] | None:
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
        table, committed = row.get("table_name"), _parse_utc(row.get("committed_at"))
        if table not in {"normalized", "hourly"} or committed is None or row.get("snapshot_id") is None:
            return None
        identities[str(table)] = row.get("snapshot_id")
    return identities if set(identities) == {"normalized", "hourly"} else None


def _namespace_isolated(
    check: Mapping[str, object], baseline: Mapping[str, object] | None,
) -> bool:
    return baseline is not None and _snapshot_identities(check) == _snapshot_identities(baseline)


def _same_source(first: Mapping[str, object] | None, second: Mapping[str, object] | None) -> bool:
    if first is None or second is None:
        return False
    return {key: value for key, value in first.items() if key != "attempt"} == {
        key: value for key, value in second.items() if key != "attempt"
    }


def _valid_component_counts(
    check: Mapping[str, object], summary: Mapping[str, object], source: Mapping[str, object] | None,
) -> bool:
    results = check.get("results")
    rows = results[0] if isinstance(results, list) and len(results) == 1 else None
    if not isinstance(rows, list) or len(rows) != len(COMPONENTS) or source is None:
        return False
    retained: dict[str, Mapping[str, object]] = {}
    for row in rows:
        if not isinstance(row, Mapping) or row.get("source_component") not in COMPONENTS:
            return False
        component = str(row["source_component"])
        if component in retained or row.get("source_window_id") != source.get("source_hour_id"):
            return False
        values = tuple(row.get(name) for name in (
            "source_count", "accepted_count", "rejected_count", "deduplicated_count", "written_count",
        ))
        if any(type(value) is not int or value < 0 for value in values):
            return False
        source_count, accepted, rejected, deduplicated, written = values
        if source_count != accepted + rejected or deduplicated != written:
            return False
        retained[component] = row
    return (
        set(retained) == COMPONENTS
        and sum(int(row["source_count"]) for row in retained.values()) == summary.get("latest_source_count")
        and sum(int(row["accepted_count"]) for row in retained.values()) == summary.get("latest_accepted_count")
        and sum(int(row["rejected_count"]) for row in retained.values()) == summary.get("latest_rejected_count")
        and sum(int(row["written_count"]) for row in retained.values()) == summary.get("latest_final_event_count")
    )


def _valid_summary(summary: Mapping[str, object]) -> bool:
    return (
        summary.get("latest_source_count")
        == summary.get("latest_accepted_count", 0) + summary.get("latest_rejected_count", 0)
        and (
            summary.get("latest_source_kind") == "complete_hour"
            or summary.get("latest_source_count") == summary.get("latest_final_event_count")
        )
        and summary.get("event_count") == summary.get("hourly_event_count_sum")
        and summary.get("rejected_count") == summary.get("hourly_rejection_count_sum")
        and int(summary.get("receipt_count") or 0) >= 1
    )


def add_flight_recorder_checks(
    result: dict[str, Any],
    baseline_path: Path | None,
    *,
    root: Path,
    namespace_baseline_path: Path | None = None,
    run_check_fn: RunCheck = run_check,
) -> None:
    """Add exact source, Trino, isolation, and replay checks to one result."""
    rejection = _hour_rejection(result)
    if rejection is not None:
        result["trino"] = {}
        result["rejection"] = dict(rejection)
        result["missing"] = [] if _valid_hour_rejection(result) else ["flight_recorder_hour_rejection"]
        result["status"] = "rejected" if not result["missing"] else "incomplete"
        return
    trino = {name: run_check_fn(root, name) for name in TRINO_CHECKS}
    result["trino"] = trino
    missing = [item for item in result.get("missing", []) if not str(item).startswith("flight_recorder_")]
    summary = _one_row(trino["flight-recorder-summary"])
    if not _valid_summary(summary):
        missing.append("flight_recorder_trino_consistency")
    if not _valid_contracts(trino["flight-recorder-contract"]):
        missing.append("flight_recorder_table_contract")
    if not _valid_snapshots(trino["flight-recorder-snapshots"]):
        missing.append("flight_recorder_snapshots")
    identity = result.get("identity") if isinstance(result.get("identity"), Mapping) else {}
    receipt = _source_receipt(result)
    if not _valid_source_receipt(receipt, attempt=identity.get("attempt_name"), summary=summary):
        missing.append("flight_recorder_source_receipt")
    if receipt is not None and receipt.get("kind") == "flight_recorder_complete_hour" and not _valid_component_counts(
        trino["flight-recorder-components"], summary, receipt,
    ):
        missing.append("flight_recorder_component_counts")
    if baseline_path is None:
        namespace_baseline = (
            json.loads(namespace_baseline_path.read_text(encoding="utf-8"))
            if namespace_baseline_path is not None else None
        )
        if not isinstance(namespace_baseline, Mapping) or not _namespace_isolated(
            trino["flight-recorder-namespace-isolation"], namespace_baseline,
        ):
            missing.append("flight_recorder_namespace_isolation")
        elif namespace_baseline_path is not None:
            result["namespace_baseline"] = str(namespace_baseline_path)
        if summary.get("latest_spark_attempt") != identity.get("attempt_name"):
            missing.append("flight_recorder_receipt_identity")
    else:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        baseline_identity = baseline.get("identity") if isinstance(baseline, Mapping) else None
        if not isinstance(baseline_identity, Mapping) or baseline_identity.get("dag_id") != "airflow_flight_recorder":
            raise OperationError("baseline is not Flight Recorder evidence")
        if baseline.get("status") != "complete" or baseline.get("missing"):
            raise OperationError("baseline Flight Recorder evidence is not complete")
        if baseline_identity.get("run_id") == identity.get("run_id"):
            raise OperationError("replay evidence requires a new Workflow Run ID")
        if not _same_source(_source_receipt(baseline), receipt):
            missing.append("flight_recorder_replay_source_changed")
        if baseline.get("trino") != trino:
            missing.append("flight_recorder_replay_changed_state")
        result["replay_baseline"] = str(baseline_path)
    result["missing"] = sorted(set(missing))
    result["status"] = "complete" if not result["missing"] else "incomplete"
