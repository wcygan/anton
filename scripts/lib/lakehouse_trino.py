"""Run fixed read-only Trino checks for the Anton lakehouse."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import subprocess
from typing import Mapping, Protocol, Sequence, TypeAlias

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
UTC_TIMESTAMP_FIELDS = frozenset({
    "committed_at",
    "completed_at",
    "event_timestamp",
    "hour",
    "window_end",
    "window_start",
})
DDL_FIELDS = frozenset({"create table", "create_table"})

CanonicalRow: TypeAlias = tuple[tuple[str, object], ...]
ComparisonKey: TypeAlias = tuple[
    tuple[str, tuple[tuple[CanonicalRow, ...], ...]],
    ...,
]


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
    comparison_key: ComparisonKey


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


def _utc_timestamp(value: object) -> str:
    if not isinstance(value, str):
        raise TrinoReadError("Trino timestamp fact is not text")
    candidate = value.strip()
    if candidate.upper().endswith(" UTC"):
        candidate = f"{candidate[:-4].rstrip()}+00:00"
    elif candidate.endswith("Z"):
        candidate = f"{candidate[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as error:
        raise TrinoReadError(f"Trino timestamp fact is invalid: {value}") from error
    if parsed.tzinfo is None:
        raise TrinoReadError(f"Trino timestamp fact has no time zone: {value}")
    return parsed.astimezone(timezone.utc).isoformat()


def _quoted_sql_end(value: str, start: int) -> int:
    quote = value[start]
    index = start + 1
    while index < len(value):
        if value[index] != quote:
            index += 1
            continue
        if index + 1 < len(value) and value[index + 1] == quote:
            index += 2
            continue
        return index + 1
    raise TrinoReadError("Trino table contract DDL has an unterminated quote")


def _normalize_sql_tokens(value: str) -> str:
    if "\x00" in value:
        raise TrinoReadError("Trino table contract DDL has an invalid character")
    literals: list[str] = []
    masked: list[str] = []
    index = 0
    while index < len(value):
        if value[index] not in {"'", '"'}:
            masked.append(value[index])
            index += 1
            continue
        end = _quoted_sql_end(value, index)
        marker = f"\x00{len(literals)}\x00"
        literals.append(value[index:end])
        masked.append(marker)
        index = end
    compact = re.sub(r"\s+", " ", "".join(masked)).strip().lower()
    compact = re.sub(r"\s*([(),=\[\]])\s*", r"\1", compact)
    for literal_index, literal in enumerate(literals):
        compact = compact.replace(f"\x00{literal_index}\x00", literal)
    return compact


def _split_with_properties(value: str) -> tuple[str, ...]:
    items: list[str] = []
    start = 0
    round_depth = 0
    square_depth = 0
    brace_depth = 0
    index = 0
    while index < len(value):
        character = value[index]
        if character in {"'", '"'}:
            index = _quoted_sql_end(value, index)
            continue
        if character == "(":
            round_depth += 1
        elif character == ")":
            round_depth -= 1
        elif character == "[":
            square_depth += 1
        elif character == "]":
            square_depth -= 1
        elif character == "{":
            brace_depth += 1
        elif character == "}":
            brace_depth -= 1
        elif character == "," and not any((round_depth, square_depth, brace_depth)):
            items.append(value[start:index])
            start = index + 1
        if min(round_depth, square_depth, brace_depth) < 0:
            raise TrinoReadError("Trino table contract WITH properties are invalid")
        index += 1
    if any((round_depth, square_depth, brace_depth)):
        raise TrinoReadError("Trino table contract WITH properties are invalid")
    items.append(value[start:])
    if any(not item or "=" not in item for item in items):
        raise TrinoReadError("Trino table contract WITH properties are invalid")
    return tuple(items)


def _canonicalize_with_properties(value: str) -> str:
    depth = 0
    with_start: int | None = None
    index = 0
    while index < len(value):
        character = value[index]
        if character in {"'", '"'}:
            index = _quoted_sql_end(value, index)
            continue
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth < 0:
                raise TrinoReadError("Trino table contract DDL parentheses are invalid")
        elif (
            depth == 0
            and value.startswith("with(", index)
            and (index == 0 or not (value[index - 1].isalnum() or value[index - 1] == "_"))
        ):
            with_start = index
            break
        index += 1
    if depth != 0:
        raise TrinoReadError("Trino table contract DDL parentheses are invalid")
    if with_start is None:
        return value

    open_index = with_start + len("with")
    depth = 1
    index = open_index + 1
    while index < len(value) and depth:
        if value[index] in {"'", '"'}:
            index = _quoted_sql_end(value, index)
            continue
        if value[index] == "(":
            depth += 1
        elif value[index] == ")":
            depth -= 1
        index += 1
    if depth:
        raise TrinoReadError("Trino table contract DDL parentheses are invalid")
    close_index = index - 1
    properties = _split_with_properties(value[open_index + 1:close_index])
    ordered = ",".join(sorted(properties))
    return f"{value[:open_index + 1]}{ordered}{value[close_index:]}"


def _normalized_ddl(value: object) -> str:
    if not isinstance(value, str):
        raise TrinoReadError("Trino table contract DDL is not text")
    return _canonicalize_with_properties(_normalize_sql_tokens(value))


def _typed_value(
    value: object,
    *,
    field: str | None = None,
    ddl: bool = False,
) -> object:
    if ddl or field in DDL_FIELDS:
        return ("ddl", _normalized_ddl(value))
    if field in UTC_TIMESTAMP_FIELDS:
        return ("utc_timestamp", _utc_timestamp(value))
    if value is None:
        return ("null",)
    if isinstance(value, bool):
        return ("boolean", value)
    if type(value) is int:
        return ("integer", value)
    if type(value) is float:
        if not math.isfinite(value):
            raise TrinoReadError("Trino numeric fact is not finite")
        return ("number", repr(value))
    if isinstance(value, str):
        normalized = re.sub(r"\s+", " ", value).strip().lower() if field in {
            "column", "type",
        } else value
        return ("text", normalized)
    if isinstance(value, Mapping):
        return ("object", _canonical_row(value))
    if isinstance(value, list):
        return ("array", tuple(_typed_value(item) for item in value))
    raise TrinoReadError(f"Trino fact has unsupported type: {type(value).__name__}")


def _canonical_row(row: Mapping[str, object], *, ddl: bool = False) -> CanonicalRow:
    normalized: dict[str, object] = {}
    for raw_key, value in row.items():
        if not isinstance(raw_key, str):
            raise TrinoReadError("Trino fact field name is invalid")
        key = re.sub(r"\s+", " ", raw_key).strip().lower()
        if not key or key in normalized:
            raise TrinoReadError("Trino fact field name is invalid")
        normalized[key] = _typed_value(
            value,
            field=key,
            ddl=ddl and len(row) == 1,
        )
    return tuple(sorted(normalized.items()))


def _comparison_key(
    checks: Mapping[str, Mapping[str, object]],
) -> ComparisonKey:
    normalized: list[tuple[str, tuple[tuple[CanonicalRow, ...], ...]]] = []
    for name in FLIGHT_RECORDER_CHECKS:
        query_results: list[tuple[CanonicalRow, ...]] = []
        for index, rows in enumerate(_check_results(checks[name], name)):
            ddl = name == "flight-recorder-contract" and index % 2 == 1
            canonical_rows = []
            for row in rows:
                if not isinstance(row, Mapping):
                    raise TrinoReadError(f"Trino check has invalid row: {name}")
                canonical_rows.append(_canonical_row(row, ddl=ddl))
            query_results.append(tuple(sorted(canonical_rows, key=repr)))
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
            _utc_timestamp(row["committed_at"]),
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
