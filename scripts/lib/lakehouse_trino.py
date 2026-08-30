"""Run fixed read-only Trino checks for the Anton lakehouse."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
from typing import Mapping, Protocol, Sequence

from cluster_target_contract import anton_kubectl_prefix


QUERIES = {
    "summary": (
        """SELECT
  (SELECT count(*) FROM iceberg.logs.normalized) AS normalized_count,
  (SELECT count(*) FROM iceberg.logs.hourly) AS hourly_count,
  (SELECT coalesce(sum(event_count), 0) FROM iceberg.logs.hourly) AS hourly_event_count_sum""",
    ),
    "contract": (
        "SHOW CREATE TABLE iceberg.logs.normalized",
        "SHOW CREATE TABLE iceberg.logs.hourly",
    ),
    "snapshots": (
        """SELECT 'normalized' AS table_name, snapshot_id, committed_at
FROM iceberg.logs."normalized$snapshots"
UNION ALL
SELECT 'hourly' AS table_name, snapshot_id, committed_at
FROM iceberg.logs."hourly$snapshots"
ORDER BY committed_at DESC
LIMIT 20""",
    ),
    "flight-recorder-summary": (
        """SELECT
  (SELECT count(*) FROM iceberg.flight_recorder.events) AS event_count,
  (SELECT count_if(rejected) FROM iceberg.flight_recorder.events) AS rejected_count,
  (SELECT count(*) FROM iceberg.flight_recorder.hourly) AS hourly_row_count,
  (SELECT coalesce(sum(event_count), 0) FROM iceberg.flight_recorder.hourly) AS hourly_event_count_sum,
  (SELECT coalesce(sum(rejection_count), 0) FROM iceberg.flight_recorder.hourly) AS hourly_rejection_count_sum,
  (SELECT count(*) FROM iceberg.flight_recorder.run_receipts) AS receipt_count,
  (SELECT count(*) FROM iceberg.flight_recorder.component_counts) AS component_receipt_count,
  latest.source_window_id AS latest_source_window_id,
  latest.raw_sha256 AS latest_raw_sha256,
  latest.spark_attempt AS latest_spark_attempt,
  latest.source_count AS latest_source_count,
  latest.accepted_count AS latest_accepted_count,
  latest.rejected_count AS latest_rejected_count,
  latest.final_event_count AS latest_final_event_count,
  latest.source_kind AS latest_source_kind,
  latest.complete_manifest_sha256 AS latest_complete_manifest_sha256
FROM (VALUES 1) AS guard(value)
LEFT JOIN (
  SELECT source_window_id, raw_sha256, spark_attempt, source_count,
    accepted_count, rejected_count, final_event_count,
    source_kind, complete_manifest_sha256
  FROM iceberg.flight_recorder.run_receipts
  ORDER BY completed_at DESC
  LIMIT 1
) AS latest ON true""",
    ),
    "flight-recorder-contract": (
        "SHOW COLUMNS FROM iceberg.flight_recorder.events",
        "SHOW CREATE TABLE iceberg.flight_recorder.events",
        "SHOW COLUMNS FROM iceberg.flight_recorder.hourly",
        "SHOW CREATE TABLE iceberg.flight_recorder.hourly",
        "SHOW COLUMNS FROM iceberg.flight_recorder.run_receipts",
        "SHOW CREATE TABLE iceberg.flight_recorder.run_receipts",
        "SHOW COLUMNS FROM iceberg.flight_recorder.component_counts",
        "SHOW CREATE TABLE iceberg.flight_recorder.component_counts",
    ),
    "flight-recorder-snapshots": (
        """SELECT snapshot_id, committed_at
FROM iceberg.flight_recorder."events$snapshots"
ORDER BY committed_at DESC
LIMIT 20""",
        """SELECT snapshot_id, committed_at
FROM iceberg.flight_recorder."hourly$snapshots"
ORDER BY committed_at DESC
LIMIT 20""",
        """SELECT snapshot_id, committed_at
FROM iceberg.flight_recorder."run_receipts$snapshots"
ORDER BY committed_at DESC
LIMIT 20""",
        """SELECT snapshot_id, committed_at
FROM iceberg.flight_recorder."component_counts$snapshots"
ORDER BY committed_at DESC
LIMIT 20""",
    ),
    "flight-recorder-components": (
        """SELECT source_window_id, source_component, source_count, accepted_count,
  rejected_count, deduplicated_count, written_count
FROM iceberg.flight_recorder.component_counts
WHERE source_window_id = (
  SELECT source_window_id FROM iceberg.flight_recorder.run_receipts
  ORDER BY completed_at DESC LIMIT 1
)
ORDER BY source_component""",
    ),
    "flight-recorder-namespace-isolation": (
        """SELECT * FROM (
SELECT 'normalized' AS table_name, snapshot_id, committed_at
FROM iceberg.logs."normalized$snapshots" ORDER BY committed_at DESC LIMIT 1
)
UNION ALL
SELECT * FROM (
SELECT 'hourly' AS table_name, snapshot_id, committed_at
FROM iceberg.logs."hourly$snapshots" ORDER BY committed_at DESC LIMIT 1
)""",
    ),
}

FLIGHT_RECORDER_CHECKS = (
    "flight-recorder-summary",
    "flight-recorder-contract",
    "flight-recorder-snapshots",
    "flight-recorder-components",
    "flight-recorder-namespace-isolation",
)


class TrinoReadError(RuntimeError):
    """A fixed Trino read check failed."""


class Runner(Protocol):
    """Run one command and return its captured result."""

    def __call__(
        self,
        argv: Sequence[str],
        timeout_seconds: float,
    ) -> subprocess.CompletedProcess[str]: ...


@dataclass(frozen=True, slots=True)
class FlightRecorderTrinoFacts:
    """Normalized facts and retained proof from fixed Trino reads."""

    raw_checks: Mapping[str, Mapping[str, object]]
    summary: Mapping[str, object]
    table_contract: tuple[tuple[object, ...], ...]
    table_snapshots: tuple[tuple[object, ...], ...]
    component_counts: tuple[Mapping[str, object], ...]
    namespace_snapshots: tuple[tuple[str, object, str], ...]
    comparison_key: tuple[tuple[str, tuple[tuple[str, ...], ...]], ...]


def subprocess_runner(
    argv: Sequence[str],
    timeout_seconds: float,
) -> subprocess.CompletedProcess[str]:
    """Run one command without a shell."""
    return subprocess.run(
        tuple(argv),
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )


def _run(
    runner: Runner,
    argv: Sequence[str],
    *,
    timeout_seconds: float,
) -> subprocess.CompletedProcess[str]:
    try:
        result = runner(tuple(argv), timeout_seconds)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise TrinoReadError(f"command failed to run: {argv[0]}") from error
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise TrinoReadError(message[-1000:])
    return result


def commands_for(root: Path, check: str) -> tuple[tuple[str, ...], ...]:
    """Build one exact read-only Trino command for an approved coordinator exec."""
    try:
        queries = QUERIES[check]
    except KeyError as error:
        raise TrinoReadError(f"unsupported Trino check: {check}") from error
    for query in queries:
        first_word = query.split(maxsplit=1)[0].upper()
        if first_word not in {"SELECT", "SHOW", "DESCRIBE"} or ";" in query:
            raise TrinoReadError(f"Trino check is not read-only: {check}")
    prefix = anton_kubectl_prefix(root)
    return tuple(
        (*prefix, "-n", "iceberg-demo", "exec", "deploy/trino-coordinator", "--", "/usr/bin/trino", "--server", "http://localhost:8080", "--user", "validation", "--output-format", "JSON", "--execute", query)
        for query in queries
    )


def run_check(
    root: Path,
    check: str,
    *,
    runner: Runner = subprocess_runner,
) -> dict[str, object]:
    """Run one fixed check and return parsed Trino JSON rows."""
    results: list[list[object]] = []
    for command in commands_for(root, check):
        completed = _run(runner, command, timeout_seconds=60)
        try:
            rows = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            lines = [line for line in completed.stdout.splitlines() if line.strip()]
            try:
                rows = [json.loads(line) for line in lines]
            except json.JSONDecodeError as line_error:
                detail = completed.stdout.strip()[-500:] or "no output"
                raise TrinoReadError(f"Trino returned invalid JSON: {detail}") from line_error
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list):
            raise TrinoReadError("Trino returned a non-tabular JSON result")
        results.append(rows)
    return {"check": check, "results": results}


def _check_results(check: Mapping[str, object], name: str) -> list[list[object]]:
    if check.get("check") != name:
        raise TrinoReadError(f"Trino check identity is invalid: {name}")
    results = check.get("results")
    if not isinstance(results, list) or any(not isinstance(rows, list) for rows in results):
        raise TrinoReadError(f"Trino check has invalid rows: {name}")
    return results


def _comparison_key(
    checks: Mapping[str, Mapping[str, object]],
) -> tuple[tuple[str, tuple[tuple[str, ...], ...]], ...]:
    normalized = []
    for name in FLIGHT_RECORDER_CHECKS:
        query_results = []
        for rows in _check_results(checks[name], name):
            query_results.append(tuple(sorted(
                json.dumps(row, sort_keys=True, separators=(",", ":"))
                for row in rows
            )))
        normalized.append((name, tuple(query_results)))
    return tuple(normalized)


def flight_recorder_facts_from_checks(
    checks: Mapping[str, Mapping[str, object]],
) -> FlightRecorderTrinoFacts:
    """Normalize all fixed Flight Recorder checks into semantic facts."""
    missing = [name for name in FLIGHT_RECORDER_CHECKS if name not in checks]
    if missing:
        raise TrinoReadError(f"Flight Recorder Trino facts are missing: {', '.join(missing)}")
    unexpected = sorted(set(checks) - set(FLIGHT_RECORDER_CHECKS))
    if unexpected:
        raise TrinoReadError(
            f"Flight Recorder Trino facts are unexpected: {', '.join(unexpected)}",
        )

    retained = {
        name: deepcopy(dict(checks[name]))
        for name in FLIGHT_RECORDER_CHECKS
    }
    summary_results = _check_results(retained["flight-recorder-summary"], "flight-recorder-summary")
    if (
        len(summary_results) != 1
        or len(summary_results[0]) != 1
        or not isinstance(summary_results[0][0], Mapping)
    ):
        raise TrinoReadError("Flight Recorder summary must contain one row")

    contract_results = _check_results(
        retained["flight-recorder-contract"], "flight-recorder-contract",
    )
    snapshot_results = _check_results(
        retained["flight-recorder-snapshots"], "flight-recorder-snapshots",
    )
    component_results = _check_results(
        retained["flight-recorder-components"], "flight-recorder-components",
    )
    namespace_results = _check_results(
        retained["flight-recorder-namespace-isolation"],
        "flight-recorder-namespace-isolation",
    )
    if len(component_results) != 1 or any(
        not isinstance(row, Mapping) for row in component_results[0]
    ):
        raise TrinoReadError("Flight Recorder component facts are invalid")
    if len(namespace_results) != 1:
        raise TrinoReadError("Flight Recorder namespace facts are invalid")
    namespace: list[tuple[str, object, str]] = []
    namespace_tables: set[str] = set()
    for row in namespace_results[0]:
        table = row.get("table_name") if isinstance(row, Mapping) else None
        if (
            not isinstance(row, Mapping)
            or not isinstance(table, str)
            or table not in {"normalized", "hourly"}
            or table in namespace_tables
            or row.get("snapshot_id") is None
            or not isinstance(row.get("committed_at"), str)
        ):
            raise TrinoReadError("Flight Recorder namespace facts are invalid")
        namespace_tables.add(table)
        namespace.append((
            table,
            row.get("snapshot_id"),
            str(row["committed_at"]),
        ))
    if namespace_tables != {"normalized", "hourly"}:
        raise TrinoReadError("Flight Recorder namespace facts are invalid")

    return FlightRecorderTrinoFacts(
        raw_checks=retained,
        summary=deepcopy(dict(summary_results[0][0])),
        table_contract=tuple(tuple(deepcopy(rows)) for rows in contract_results),
        table_snapshots=tuple(tuple(deepcopy(rows)) for rows in snapshot_results),
        component_counts=tuple(deepcopy(dict(row)) for row in component_results[0]),
        namespace_snapshots=tuple(sorted(namespace, key=lambda row: row[0])),
        comparison_key=_comparison_key(retained),
    )


def read_flight_recorder_facts(
    root: Path,
    *,
    runner: Runner = subprocess_runner,
) -> FlightRecorderTrinoFacts:
    """Read and normalize the fixed Flight Recorder Trino facts."""
    checks = {
        name: run_check(root, name, runner=runner)
        for name in FLIGHT_RECORDER_CHECKS
    }
    return flight_recorder_facts_from_checks(checks)
