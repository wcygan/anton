import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "durability_build", ROOT / "images/seaweedfs-durability/build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class PolicyCopyBudgetTests(unittest.TestCase):
    def setUp(self):
        self.pod = {
            "initContainers": [{"name": "weed-tool", "resources": {
                "limits": {"memory": "384Mi"}}}],
            "volumes": [{"name": "tools", "emptyDir": {"sizeLimit": "384Mi"}}],
        }
        self.binary_bytes = 212 * 1024**2

    def test_accepts_the_qualified_copy_budget(self):
        result = build.policy_copy_budget(self.binary_bytes, self.pod)
        self.assertEqual(result, {"binary_bytes": self.binary_bytes,
                                  "init_memory_limit_bytes": 384 * 1024**2,
                                  "tools_volume_limit_bytes": 384 * 1024**2})

    def test_rejects_the_oom_killed_init_budget(self):
        self.pod["initContainers"][0]["resources"]["limits"]["memory"] = "32Mi"
        with self.assertRaisesRegex(ValueError, "init memory"):
            build.policy_copy_budget(self.binary_bytes, self.pod)

    def test_rejects_an_undersized_tools_volume(self):
        self.pod["volumes"][0]["emptyDir"]["sizeLimit"] = "192Mi"
        with self.assertRaisesRegex(ValueError, "tools volume"):
            build.policy_copy_budget(self.binary_bytes, self.pod)

    def test_accepts_gibibytes_and_rejects_ambiguous_units(self):
        self.pod["volumes"][0]["emptyDir"]["sizeLimit"] = "1Gi"
        self.assertEqual(build.policy_copy_budget(self.binary_bytes, self.pod)
                         ["tools_volume_limit_bytes"], 1024**3)
        self.pod["volumes"][0]["emptyDir"]["sizeLimit"] = "unknown"
        with self.assertRaisesRegex(ValueError, "unsupported"):
            build.policy_copy_budget(self.binary_bytes, self.pod)


if __name__ == "__main__":
    unittest.main()
