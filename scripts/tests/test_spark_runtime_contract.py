"""Behavior tests for the immutable Spark runtime source contract."""

from __future__ import annotations

import subprocess
import importlib.util
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
VALIDATOR = REPO / "scripts" / "validate-spark-runtime-contract.py"
SPEC = importlib.util.spec_from_file_location("spark_runtime_contract", VALIDATOR)
assert SPEC and SPEC.loader
CONTRACT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTRACT)


class SparkRuntimeContractTests(unittest.TestCase):
    def test_contract_source_passes(self) -> None:
        result = subprocess.run(
            ["python3", str(VALIDATOR)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Spark runtime contract: PASS", result.stdout)

    def test_application_entrypoint_stays_outside_spark_work_directory(self) -> None:
        sources = (
            REPO / "images" / "spark-runtime" / "Dockerfile",
            REPO / "images" / "airflow-runtime" / "src" / "anton_airflow" / "lakehouse.py",
        )
        for source in sources:
            content = source.read_text(encoding="utf-8")
            with self.subTest(source=source.relative_to(REPO)):
                self.assertIn("/opt/spark/application/transform.py", content)
                self.assertNotIn("/opt/spark/work-dir/transform.py", content)

    def test_both_application_entrypoints_are_pinned_and_outside_work_directory(self) -> None:
        dockerfile = (REPO / "images/spark-runtime/Dockerfile").read_text(encoding="utf-8")
        application_spec = (
            REPO / "images/airflow-runtime/src/anton_airflow/lakehouse.py"
        ).read_text(encoding="utf-8")
        self.assertEqual(CONTRACT.entrypoint_failures(dockerfile, application_spec), [])
        for entrypoint in ("transform.py", "flight_recorder.py"):
            with self.subTest(entrypoint=entrypoint):
                self.assertTrue(CONTRACT.entrypoint_failures(
                    dockerfile.replace(f"/opt/spark/application/{entrypoint}", "/missing", 1),
                    application_spec,
                ))
                self.assertTrue(CONTRACT.entrypoint_failures(
                    dockerfile,
                    application_spec.replace(f"local:///opt/spark/application/{entrypoint}", "/missing", 1),
                ))
                self.assertNotIn(f"/opt/spark/work-dir/{entrypoint}", dockerfile + application_spec)


if __name__ == "__main__":
    unittest.main()
