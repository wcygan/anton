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
TABLE_CONTRACTS = {
    "events": (
        (("fingerprint", "varchar"), ("event_timestamp", "timestamp(6)"),
         ("event_date", "date"), ("source_window_id", "varchar"),
         ("source_timestamp_ns", "varchar"), ("namespace", "varchar"),
         ("workload_kind", "varchar"), ("workload_name", "varchar"),
         ("pod_name", "varchar"), ("container_name", "varchar"),
         ("severity", "varchar"), ("redacted_preview", "varchar"),
         ("rejected", "boolean"), ("rejection_reason", "varchar")),
        "event_date",
    ),
    "hourly": (
        (("hour", "timestamp(6)"), ("namespace", "varchar"),
         ("workload_kind", "varchar"), ("workload_name", "varchar"),
         ("severity", "varchar"), ("event_count", "bigint"),
         ("rejection_count", "bigint")),
        "day(hour)",
    ),
    "run_receipts": (
        (("source_window_id", "varchar"), ("raw_sha256", "varchar"),
         ("manifest_uri", "varchar"), ("raw_uri", "varchar"),
         ("source_count", "bigint"), ("accepted_count", "bigint"),
         ("rejected_count", "bigint"), ("final_event_count", "bigint"),
         ("spark_attempt", "varchar"), ("window_start", "timestamp(6)"),
         ("window_end", "timestamp(6)"), ("completed_at", "timestamp(6)"),
         ("completion_date", "date")),
        "completion_date",
    ),
}
TRINO_CHECKS = (
    "flight-recorder-summary",
    "flight-recorder-contract",
    "flight-recorder-snapshots",
    "flight-recorder-namespace-isolation",
)
WORKFLOW_QUERY = '{k8s_namespace_name="airflow"}'
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
    receipts = source.get("source_receipts") if isinstance(source, Mapping) else None
    if not isinstance(receipts, list) or len(receipts) != 1 or not isinstance(receipts[0], Mapping):
        return None
    return receipts[0]


def _valid_source_receipt(
    receipt: Mapping[str, object] | None,
    *,
    attempt: object,
    summary: Mapping[str, object],
) -> bool:
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
    if not isinstance(results, list) or len(results) != 6:
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
        isinstance(results, list) and len(results) == 3
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


def add_flight_recorder_checks(
    result: dict[str, Any],
    baseline_path: Path | None,
    *,
    root: Path,
    namespace_baseline_path: Path | None = None,
    run_check_fn: RunCheck = run_check,
) -> None:
    """Add exact source, Trino, isolation, and replay checks to one result."""
    trino = {name: run_check_fn(root, name) for name in TRINO_CHECKS}
    result["trino"] = trino
    missing = [item for item in result.get("missing", []) if not str(item).startswith("flight_recorder_")]
    summary = _one_row(trino["flight-recorder-summary"])
    consistent = (
        summary.get("latest_source_count")
        == summary.get("latest_accepted_count", 0) + summary.get("latest_rejected_count", 0)
        and summary.get("latest_source_count") == summary.get("latest_final_event_count")
        and summary.get("event_count") == summary.get("hourly_event_count_sum")
        and summary.get("rejected_count") == summary.get("hourly_rejection_count_sum")
        and int(summary.get("receipt_count") or 0) >= 1
    )
    if not consistent:
        missing.append("flight_recorder_trino_consistency")
    if not _valid_contracts(trino["flight-recorder-contract"]):
        missing.append("flight_recorder_table_contract")
    if not _valid_snapshots(trino["flight-recorder-snapshots"]):
        missing.append("flight_recorder_snapshots")
    identity = result.get("identity") if isinstance(result.get("identity"), Mapping) else {}
    receipt = _source_receipt(result)
    if not _valid_source_receipt(receipt, attempt=identity.get("attempt_name"), summary=summary):
        missing.append("flight_recorder_source_receipt")
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
