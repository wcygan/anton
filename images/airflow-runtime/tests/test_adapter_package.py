"""Tests for the ticket 04 Airflow image package boundary."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from importlib.metadata import version
from pathlib import Path

import airflow

from anton_airflow.spark import PACKAGE_VERSION, foundation_marker


class AdapterPackageTests(unittest.TestCase):
    def test_runtime_versions_are_exact(self) -> None:
        self.assertEqual(airflow.__version__, "3.2.2")
        self.assertEqual(sys.version_info[:2], (3, 12))
        self.assertEqual(version("apache-airflow-providers-cncf-kubernetes"), "10.21.0")

    def test_foundation_marker_reports_package_identity(self) -> None:
        marker = foundation_marker(run_id="manual__ticket04", pod_name="worker-1")
        self.assertEqual(marker["adapter_package"], PACKAGE_VERSION)
        self.assertEqual(marker["run_id"], "manual__ticket04")
        self.assertEqual(marker["pod_name"], "worker-1")

    def test_foundation_dag_is_manual_and_bounded(self) -> None:
        dag_path = Path("/opt/airflow/dags/airflow_kubernetes_foundation.py")
        spec = importlib.util.spec_from_file_location("airflow_kubernetes_foundation", dag_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        foundation_dag = module.foundation_dag
        self.assertEqual(foundation_dag.dag_id, "airflow_kubernetes_foundation")
        self.assertIsNone(foundation_dag.schedule)
        self.assertEqual(foundation_dag.max_active_runs, 1)
        self.assertEqual(foundation_dag.task_ids, ["prove_kubernetes_task_pod"])


if __name__ == "__main__":
    unittest.main()
