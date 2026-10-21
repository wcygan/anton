import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "kubernetes/apps/storage/seaweedfs-config/app/ensure-durability.py"
spec = importlib.util.spec_from_file_location("durability_policy", SCRIPT)
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class DurabilityPolicyTests(unittest.TestCase):
    def setUp(self):
        self.config = {"locations": [
            {"locationPrefix": p, "fsync": True, "replication": "001"}
            for p in policy.PREFIXES
        ]}

    def test_reads_last_complete_configuration(self):
        output = json.dumps({"locations": []}) + "\n\n" + json.dumps(self.config)
        policy.verify(policy.read_config(output))

    def test_missing_policy_is_rejected(self):
        self.config["locations"].pop()
        with self.assertRaises(ValueError):
            policy.verify(self.config)

    def test_duplicate_policy_is_rejected(self):
        self.config["locations"].append(copy.deepcopy(self.config["locations"][0]))
        with self.assertRaises(ValueError):
            policy.verify(self.config)

    def test_weak_or_read_only_policies_are_rejected(self):
        for key, value in [("fsync", False), ("fsync", "true"),
                           ("replication", "000"), ("replication", 1), ("readOnly", True)]:
            with self.subTest(key=key, value=value):
                changed = copy.deepcopy(self.config)
                changed["locations"][0][key] = value
                with self.assertRaises(ValueError):
                    policy.verify(changed)

    def test_missing_readback_is_rejected(self):
        for text in ["", "{}", '{"locations":null}', "not JSON"]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                policy.read_config(text)

    def test_check_only_cli_cannot_apply(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / "weed"
            fake.write_text(
                "#!/usr/bin/env python3\nimport sys\n"
                "assert '-apply' not in sys.stdin.read()\n"
                "print(" + repr(json.dumps(self.config)) + ")\n"
            )
            fake.chmod(0o700)
            result = subprocess.run(
                ["python3", str(SCRIPT), "--weed", str(fake), "--master", "master:9333",
                 "--filers", "filer0:8888,filer1:8888", "--check-only"],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            actual = json.loads(result.stdout)
            self.assertEqual(actual["verified_filers"], ["filer0:8888", "filer1:8888"])
            self.assertTrue(actual["fsync"])
            self.assertTrue(actual["check_only"])


if __name__ == "__main__":
    unittest.main()
