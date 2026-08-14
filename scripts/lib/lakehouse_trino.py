"""Run fixed read-only Trino checks for the Anton lakehouse."""

from __future__ import annotations

import json
from pathlib import Path

from airflow_lakehouse_operations import OperationError, Runner, _run, subprocess_runner
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
}


def commands_for(root: Path, check: str) -> tuple[tuple[str, ...], ...]:
    """Build one exact read-only Trino command for an approved coordinator exec."""
    try:
        queries = QUERIES[check]
    except KeyError as error:
        raise OperationError(f"unsupported Trino check: {check}") from error
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
                raise OperationError(f"Trino returned invalid JSON: {detail}") from line_error
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list):
            raise OperationError("Trino returned a non-tabular JSON result")
        results.append(rows)
    return {"check": check, "results": results}
