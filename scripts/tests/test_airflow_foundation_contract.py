"""Tests for the ticket 04 Airflow foundation contract."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


class AirflowFoundationContractTests(unittest.TestCase):
    def test_repository_contract_passes(self) -> None:
        result = subprocess.run(
            ["python3", "scripts/validate-airflow-foundation-contract.py"],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Airflow Kubernetes foundation contract: PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
