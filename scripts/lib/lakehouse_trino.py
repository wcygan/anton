"""Run fixed read-only Trino checks for the Anton lakehouse."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Protocol, Sequence

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
  latest.source_window_id AS latest_source_window_id,
  latest.raw_sha256 AS latest_raw_sha256,
  latest.spark_attempt AS latest_spark_attempt,
  latest.source_count AS latest_source_count,
  latest.accepted_count AS latest_accepted_count,
  latest.rejected_count AS latest_rejected_count,
  latest.final_event_count AS latest_final_event_count
FROM (VALUES 1) AS guard(value)
LEFT JOIN (
  SELECT source_window_id, raw_sha256, spark_attempt, source_count,
    accepted_count, rejected_count, final_event_count
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


class TrinoReadError(RuntimeError):
    """A fixed Trino read check failed."""


class Runner(Protocol):
    """Run one command and return its captured result."""

    def __call__(
        self,
        argv: Sequence[str],
        timeout_seconds: float,
    ) -> subprocess.CompletedProcess[str]: ...


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
