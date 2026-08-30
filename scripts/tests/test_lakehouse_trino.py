"""Tests for fixed read-only Trino evidence commands."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[2]
LIB = REPO / "scripts" / "lib"
sys.path.insert(0, str(LIB))

from lakehouse_trino import (  # noqa: E402
    QUERIES,
    TrinoReadError,
    commands_for,
    flight_recorder_facts_from_checks,
    run_check,
)


def _flight_recorder_checks() -> dict[str, dict[str, object]]:
    return {
        "flight-recorder-summary": {
            "check": "flight-recorder-summary",
            "results": [[{"latest_source_count": 4}]],
        },
        "flight-recorder-contract": {
            "check": "flight-recorder-contract",
            "results": [[{"Column": "first"}, {"Column": "second"}]],
        },
        "flight-recorder-snapshots": {
            "check": "flight-recorder-snapshots",
            "results": [[{"snapshot_id": 10}, {"snapshot_id": 20}]],
        },
        "flight-recorder-components": {
            "check": "flight-recorder-components",
            "results": [[
                {"source_component": "workflow", "source_count": 1},
                {"source_component": "trino", "source_count": 1},
            ]],
        },
        "flight-recorder-namespace-isolation": {
            "check": "flight-recorder-namespace-isolation",
            "results": [[
                {
                    "table_name": "normalized",
                    "snapshot_id": 30,
                    "committed_at": "2026-08-14T10:59:00Z",
                },
                {
                    "table_name": "hourly",
                    "snapshot_id": 40,
                    "committed_at": "2026-08-14T10:59:00Z",
                },
            ]],
        },
    }


class LakehouseTrinoTests(unittest.TestCase):
    def test_flight_recorder_facts_ignore_row_order(self) -> None:
        first = _flight_recorder_checks()
        second = _flight_recorder_checks()
        second["flight-recorder-components"]["results"][0].reverse()  # type: ignore[index]

        first_facts = flight_recorder_facts_from_checks(first)
        second_facts = flight_recorder_facts_from_checks(second)

        self.assertEqual(first_facts.comparison_key, second_facts.comparison_key)
        self.assertEqual(
            (
                ("hourly", 40, "2026-08-14T10:59:00+00:00"),
                ("normalized", 30, "2026-08-14T10:59:00+00:00"),
            ),
            first_facts.namespace_snapshots,
        )
        second["flight-recorder-components"]["results"][0][0]["source_count"] = 2  # type: ignore[index]
        changed_facts = flight_recorder_facts_from_checks(second)
        self.assertNotEqual(first_facts.comparison_key, changed_facts.comparison_key)

    def test_flight_recorder_facts_normalize_timestamps_and_ddl_formatting(self) -> None:
        first = _flight_recorder_checks()
        first["flight-recorder-contract"]["results"] = [[{
            "Create Table": """CREATE TABLE iceberg.flight_recorder.events (
              fingerprint varchar
            ) WITH (
              format_version = 2,
              location = 's3://iceberg-warehouse/flight_recorder/events'
            )""",
        }]]
        first["flight-recorder-snapshots"]["results"] = [[{
            "snapshot_id": 10,
            "committed_at": "2026-08-14T12:05:00Z",
        }]]
        second = deepcopy(first)
        second["flight-recorder-contract"]["results"][0][0]["Create Table"] = (
            "create table iceberg.flight_recorder.events(fingerprint varchar) "
            "with(format_version=2,location='s3://iceberg-warehouse/flight_recorder/events')"
        )
        second["flight-recorder-snapshots"]["results"][0][0]["committed_at"] = (
            "2026-08-14 12:05:00.000 UTC"
        )
        for row in second["flight-recorder-namespace-isolation"]["results"][0]:
            row["committed_at"] = "2026-08-14 10:59:00.000 UTC"

        first_facts = flight_recorder_facts_from_checks(first)
        second_facts = flight_recorder_facts_from_checks(second)

        self.assertEqual(first_facts.comparison_key, second_facts.comparison_key)
        changed = deepcopy(second)
        changed["flight-recorder-contract"]["results"][0][0]["Create Table"] = (
            str(changed["flight-recorder-contract"]["results"][0][0]["Create Table"])
            .replace("format_version=2", "format_version=1")
        )
        changed_facts = flight_recorder_facts_from_checks(changed)
        self.assertNotEqual(first_facts.comparison_key, changed_facts.comparison_key)

    def test_flight_recorder_facts_ignore_with_property_order(self) -> None:
        first = _flight_recorder_checks()
        first["flight-recorder-contract"]["results"] = [[{
            "Create Table": (
                "CREATE TABLE iceberg.flight_recorder.events (fingerprint varchar) WITH ("
                "format_version = 2, "
                "location = 's3://iceberg-warehouse/flight_recorder/events', "
                "partitioning = ARRAY['event_date'])"
            ),
        }]]
        second = deepcopy(first)
        second["flight-recorder-contract"]["results"][0][0]["Create Table"] = (
            "create table iceberg.flight_recorder.events(fingerprint varchar) with("
            "partitioning=array['event_date'],"
            "location='s3://iceberg-warehouse/flight_recorder/events',"
            "format_version=2)"
        )

        first_facts = flight_recorder_facts_from_checks(first)
        second_facts = flight_recorder_facts_from_checks(second)

        self.assertEqual(first_facts.comparison_key, second_facts.comparison_key)

    def test_flight_recorder_facts_preserve_quoted_path_case(self) -> None:
        first = _flight_recorder_checks()
        first["flight-recorder-contract"]["results"] = [[{
            "Create Table": (
                "CREATE TABLE iceberg.flight_recorder.events (fingerprint varchar) WITH ("
                "format_version = 2, "
                "location = 's3://iceberg-warehouse/flight_recorder/events')"
            ),
        }]]
        changed = deepcopy(first)
        changed["flight-recorder-contract"]["results"][0][0]["Create Table"] = (
            str(changed["flight-recorder-contract"]["results"][0][0]["Create Table"])
            .replace("/events'", "/Events'")
        )

        first_facts = flight_recorder_facts_from_checks(first)
        changed_facts = flight_recorder_facts_from_checks(changed)

        self.assertNotEqual(first_facts.comparison_key, changed_facts.comparison_key)

    def test_flight_recorder_facts_require_every_fixed_check(self) -> None:
        checks = _flight_recorder_checks()
        del checks["flight-recorder-components"]

        with self.assertRaisesRegex(TrinoReadError, "facts are missing"):
            flight_recorder_facts_from_checks(checks)

    def test_flight_recorder_facts_reject_duplicate_namespace_rows(self) -> None:
        checks = _flight_recorder_checks()
        rows = checks["flight-recorder-namespace-isolation"]["results"][0]  # type: ignore[index]
        rows[1]["table_name"] = "normalized"  # type: ignore[index]
        rows[1]["snapshot_id"] = {"invalid": True}  # type: ignore[index]

        with self.assertRaisesRegex(TrinoReadError, "namespace facts are invalid"):
            flight_recorder_facts_from_checks(checks)

    def test_commands_use_the_fixed_coordinator_and_read_only_queries(self) -> None:
        prefix = ("mise", "exec", "--", "kubectl", "--kubeconfig", "kubeconfig")
        with patch("lakehouse_trino.anton_kubectl_prefix", return_value=prefix):
            for check, queries in QUERIES.items():
                for command, query in zip(commands_for(REPO, check), queries, strict=True):
                    self.assertEqual(command[: len(prefix)], prefix)
                    self.assertIn("deploy/trino-coordinator", command)
                    self.assertEqual(command[-1], query)
                    self.assertRegex(query.lstrip().upper(), r"^(SELECT|SHOW|DESCRIBE)\b")
                    self.assertNotIn(";", query)

    def test_unknown_check_fails_closed(self) -> None:
        with self.assertRaisesRegex(TrinoReadError, "unsupported Trino check"):
            commands_for(REPO, "arbitrary-sql")

    def test_fixed_query_registry_rejects_write_statements(self) -> None:
        with patch.dict(QUERIES, {"unsafe": ("DELETE FROM important_table",)}):
            with self.assertRaisesRegex(TrinoReadError, "not read-only"):
                commands_for(REPO, "unsafe")

    def test_task_surface_owns_trino_checks(self) -> None:
        result = subprocess.run(
            ["mise", "exec", "--", "task", "--list"],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("trino:summary:", result.stdout)
        self.assertIn("trino:contract:", result.stdout)
        self.assertIn("trino:snapshots:", result.stdout)
        self.assertIn("trino:flight-recorder-summary:", result.stdout)
        self.assertIn("trino:flight-recorder-contract:", result.stdout)
        self.assertIn("trino:flight-recorder-snapshots:", result.stdout)
        self.assertIn("trino:flight-recorder-namespace-isolation:", result.stdout)
        self.assertIn("trino:flight-recorder-components:", result.stdout)
        self.assertNotIn("airflow:trino-summary:", result.stdout)

    def test_flight_recorder_queries_cover_counts_contracts_and_snapshots(self) -> None:
        summary = QUERIES["flight-recorder-summary"][0]
        for field in (
            "event_count", "rejected_count", "hourly_row_count",
            "hourly_event_count_sum", "hourly_rejection_count_sum", "receipt_count",
            "latest_source_window_id", "latest_raw_sha256", "latest_spark_attempt",
            "latest_source_count", "latest_accepted_count", "latest_rejected_count",
            "latest_final_event_count",
            "component_receipt_count", "latest_source_kind", "latest_complete_manifest_sha256",
        ):
            self.assertIn(field, summary)
        self.assertNotIn("redacted_preview", summary)

        contract = "\n".join(QUERIES["flight-recorder-contract"])
        snapshots = QUERIES["flight-recorder-snapshots"]
        for table in ("events", "hourly", "run_receipts", "component_counts"):
            name = f"iceberg.flight_recorder.{table}"
            self.assertIn(f"SHOW COLUMNS FROM {name}", contract)
            self.assertIn(f"SHOW CREATE TABLE {name}", contract)
            self.assertTrue(any(f'"{table}$snapshots"' in query for query in snapshots))
        self.assertTrue(all(
            "ORDER BY committed_at DESC" in query and "LIMIT 20" in query
            for query in snapshots
        ))
        isolation = QUERIES["flight-recorder-namespace-isolation"][0]
        self.assertIn('iceberg.logs."normalized$snapshots"', isolation)
        self.assertIn('iceberg.logs."hourly$snapshots"', isolation)
        components = QUERIES["flight-recorder-components"][0]
        for field in (
            "source_component", "source_count", "accepted_count", "rejected_count",
            "deduplicated_count", "written_count",
        ):
            self.assertIn(field, components)

    def test_single_row_object_normalizes_to_a_json_list(self) -> None:
        prefix = ("kubectl",)
        completed = subprocess.CompletedProcess([], 0, '{"row": 1}', "")
        with patch("lakehouse_trino.anton_kubectl_prefix", return_value=prefix):
            result = run_check(REPO, "summary", runner=lambda _argv, _timeout: completed)
        self.assertEqual(result, {"check": "summary", "results": [[{"row": 1}]]})

    def test_non_tabular_result_fails_closed(self) -> None:
        prefix = ("kubectl",)
        completed = subprocess.CompletedProcess([], 0, '"not a result"', "")
        with patch("lakehouse_trino.anton_kubectl_prefix", return_value=prefix):
            with self.assertRaisesRegex(TrinoReadError, "non-tabular JSON"):
                run_check(REPO, "summary", runner=lambda _argv, _timeout: completed)

    def test_json_lines_normalize_to_rows(self) -> None:
        prefix = ("kubectl",)
        completed = subprocess.CompletedProcess([], 0, '{"table":"normalized"}\n{"table":"hourly"}\n', "")
        with patch("lakehouse_trino.anton_kubectl_prefix", return_value=prefix):
            result = run_check(REPO, "snapshots", runner=lambda _argv, _timeout: completed)
        self.assertEqual(
            result,
            {
                "check": "snapshots",
                "results": [[{"table": "normalized"}, {"table": "hourly"}]],
            },
        )

    def test_result_records_only_the_selected_check_and_rows(self) -> None:
        prefix = ("kubectl",)
        completed = subprocess.CompletedProcess([], 0, '[{"normalized_count":5}]', "")
        with patch("lakehouse_trino.anton_kubectl_prefix", return_value=prefix):
            result = run_check(REPO, "summary", runner=lambda _argv, _timeout: completed)
        self.assertEqual(
            result,
            {"check": "summary", "results": [[{"normalized_count": 5}]]},
        )
