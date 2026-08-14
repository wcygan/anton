"""Tests for fixed read-only Trino evidence commands."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[2]
LIB = REPO / "scripts" / "lib"
sys.path.insert(0, str(LIB))

from airflow_lakehouse_operations import OperationError  # noqa: E402
from lakehouse_trino import QUERIES, commands_for, run_check  # noqa: E402


class LakehouseTrinoTests(unittest.TestCase):
    def test_commands_use_the_fixed_coordinator_and_read_only_queries(self) -> None:
        prefix = ("mise", "exec", "--", "kubectl", "--kubeconfig", "kubeconfig")
        with patch("lakehouse_trino.anton_kubectl_prefix", return_value=prefix):
            for check, queries in QUERIES.items():
                for command, query in zip(commands_for(REPO, check), queries, strict=True):
                    self.assertEqual(command[: len(prefix)], prefix)
                    self.assertIn("deploy/trino-coordinator", command)
                    self.assertEqual(command[-1], query)
                    self.assertNotRegex(query.upper(), r"\b(DELETE|DROP|INSERT|MERGE|ALTER)\b")

    def test_unknown_check_fails_closed(self) -> None:
        with self.assertRaisesRegex(OperationError, "unsupported Trino check"):
            commands_for(REPO, "arbitrary-sql")

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
            with self.assertRaisesRegex(OperationError, "non-tabular JSON"):
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
