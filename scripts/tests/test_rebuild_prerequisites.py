import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "check-rebuild-prerequisites.py"


class RebuildPrerequisitesCli(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        self.contract_path = Path(self.temp.name) / "contract.json"
        self.contract = {
            "schema": 1,
            "stages": ["storage-network", "harbor", "private-apps"],
            "stage_details": {"storage-network": {"owner": "repo", "origin": "source", "order": 1},
                              "harbor": {"owner": "repo", "origin": "source", "order": 2},
                              "private-apps": {"owner": "repo", "origin": "source", "order": 3}},
            "required_paths": ["source/required.yaml"],
            "scan_roots": ["source"],
            "stage_paths": {
                "storage-network": ["source/network/"],
                "harbor": ["source/harbor/"],
                "private-apps": ["source/apps/"]
            },
            "private_registry_host": "registry.lan",
            "harbor_stage": "harbor",
            "unverified_inputs": []
        }
        (self.root / "source").mkdir()
        (self.root / "source/required.yaml").write_text("source\n")
        self.write_contract()

    def write_contract(self):
        self.contract_path.write_text(json.dumps(self.contract))

    def run_audit(self):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.root),
             "--contract", str(self.contract_path)],
            text=True, capture_output=True, check=False
        )

    def test_missing_declared_input_fails(self):
        (self.root / "source/required.yaml").unlink()
        result = self.run_audit()
        self.assertEqual(result.returncode, 1)
        self.assertIn("FAIL    source/required.yaml", result.stdout)

    def test_independent_private_image_is_unknown(self):
        manifest = self.root / "source/apps/workload.yaml"
        manifest.parent.mkdir(parents=True)
        manifest.write_text("image: registry.lan/library/app:1@sha256:abc\n")
        result = self.run_audit()
        self.assertEqual(result.returncode, 2)
        self.assertIn("UNKNOWN source/apps/workload.yaml:1", result.stdout)
        self.assertIn("availability is not independently verified", result.stdout)

    def test_harbor_image_before_harbor_is_unverified_cold_start_cycle(self):
        manifest = self.root / "source/network/storage-vxlan.yaml"
        manifest.parent.mkdir(parents=True)
        manifest.write_text("image: registry.lan/library/storage-vxlan:1@sha256:abc\n")
        result = self.run_audit()
        self.assertEqual(result.returncode, 2)
        self.assertIn("UNKNOWN source/network/storage-vxlan.yaml:1", result.stdout)
        self.assertIn("potential cold-start cycle", result.stdout)
        self.assertIn("cache survival/seeding for a rebuild is unverified", result.stdout)

    def test_complete_source_contract_passes(self):
        result = self.run_audit()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Totals: PASS=4, UNKNOWN=0, FAIL=0", result.stdout)


if __name__ == "__main__":
    unittest.main()
