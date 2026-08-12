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


if __name__ == "__main__":
    unittest.main()
