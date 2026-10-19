import importlib.util
from pathlib import Path
import unittest


CHECKER_PATH = Path(__file__).resolve().parents[1] / "check-harbor-resource-contract.py"
SPEC = importlib.util.spec_from_file_location("harbor_resource_contract", CHECKER_PATH)
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


def deployment(resources_by_container):
    return {
        "spec": {
            "template": {
                "spec": {
                    "containers": [
                        {"name": name, "resources": resources}
                        for name, resources in resources_by_container.items()
                    ]
                }
            }
        }
    }


class HarborResourceContractTests(unittest.TestCase):
    def test_accepts_expected_resources_on_both_rendered_containers(self):
        rendered = deployment(
            {
                "registry": {
                    "requests": {"cpu": "100m", "memory": "256Mi"},
                    "limits": {"memory": "512Mi"},
                },
                "registryctl": {"requests": {"cpu": "10m", "memory": "64Mi"}},
            }
        )

        self.assertEqual(CHECKER.resource_failures(rendered), [])

    def test_reports_missing_rendered_requests(self):
        rendered = deployment({"registry": {}, "registryctl": {}})

        self.assertEqual(
            CHECKER.resource_failures(rendered),
            [
                "registry requests.cpu: expected 100m, got None",
                "registry requests.memory: expected 256Mi, got None",
                "registry limits.memory: expected 512Mi, got None",
                "registryctl requests.cpu: expected 10m, got None",
                "registryctl requests.memory: expected 64Mi, got None",
            ],
        )


if __name__ == "__main__":
    unittest.main()
