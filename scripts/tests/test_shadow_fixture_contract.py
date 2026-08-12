"""Behavior test for the SparkApplication shadow fixture contract."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


class ShadowFixtureContractTests(unittest.TestCase):
    def test_shadow_fixture_source_passes(self) -> None:
        result = subprocess.run(
            ["python3", "scripts/validate-shadow-fixture-contract.py"], cwd=REPO, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Shadow fixture contract: PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
