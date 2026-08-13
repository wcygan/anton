"""Behavior tests for the immutable Spark runtime source contract."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
VALIDATOR = REPO / "scripts" / "validate-spark-runtime-contract.py"


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
            REPO / "kubernetes" / "apps" / "lakehouse" / "shadow-fixture" / "app" / "sparkapplication.yaml",
        )
        for source in sources:
            content = source.read_text(encoding="utf-8")
            with self.subTest(source=source.relative_to(REPO)):
                self.assertIn("/opt/spark/application/transform.py", content)
                self.assertNotIn("/opt/spark/work-dir/transform.py", content)


if __name__ == "__main__":
    unittest.main()
