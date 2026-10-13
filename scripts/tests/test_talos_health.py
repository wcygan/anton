"""Exercise health target selection without contacting a cluster."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]


class TalosHealthTests(unittest.TestCase):
    def run_health(self, nodes):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scripts = root / "scripts"
            (scripts / "lib").mkdir(parents=True)
            shutil.copy(REPO / "scripts/talos-health.sh", scripts)
            shutil.copy(REPO / "scripts/lib/common.sh", scripts / "lib")
            (scripts / "cluster-targets.py").write_text(
                'print("k8s-1=100.64.0.1,k8s-2=100.64.0.2,k8s-3=100.64.0.3")\n'
            )
            fixture = root / "nodes.json"
            fixture.write_text(json.dumps(nodes))
            calls = root / "calls"
            binaries = root / "bin"
            binaries.mkdir()
            for name, body in {
                "yq": 'cat "$NODES_FIXTURE"',
                "kubectl": 'echo "all nodes Ready"',
                "mise": 'printf "%s\\n" "$*" >> "$CALLS"; echo "Server:"; echo "Version: test"',
            }.items():
                path = binaries / name
                path.write_text("#!/bin/sh\n" + body + "\n")
                path.chmod(0o755)
            env = dict(os.environ, PATH=f"{binaries}:{os.environ['PATH']}",
                       KUBECONFIG="unused", TALOSCONFIG="unused",
                       NODES_FIXTURE=str(fixture), CALLS=str(calls))
            result = subprocess.run(["bash", str(scripts / "talos-health.sh")],
                                    env=env, capture_output=True, text=True)
            return result, calls.read_text() if calls.exists() else ""

    def nodes(self):
        return [dict(hostname=f"k8s-{i}", controlPlane=True,
                     ipAddress=f"192.168.1.{97+i}") for i in (1, 2, 3)]

    def test_health_uses_management_while_client_uses_tailscale(self):
        result, calls = self.run_health(list(reversed(self.nodes())))
        self.assertEqual(result.returncode, 0, result.stderr)
        health = [line for line in calls.splitlines() if " health " in line]
        self.assertEqual(len(health), 1)
        self.assertIn("--endpoints 100.64.0.1 --nodes 100.64.0.1", health[0])
        self.assertIn("--control-plane-nodes 192.168.1.98,192.168.1.99,192.168.1.100", health[0])

    def test_invalid_inventory_fails_before_talos_calls(self):
        for invalid in ("missing", "unexpected", "duplicate", "storage", "worker"):
            with self.subTest(invalid=invalid):
                nodes = self.nodes()
                if invalid == "missing":
                    nodes.pop()
                elif invalid == "unexpected":
                    nodes[0]["hostname"] = "other-cluster"
                elif invalid == "duplicate":
                    nodes[0]["ipAddress"] = nodes[1]["ipAddress"]
                elif invalid == "storage":
                    nodes[0]["ipAddress"] = "10.100.0.0"
                else:
                    nodes[0]["controlPlane"] = False
                result, calls = self.run_health(nodes)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls, "")


if __name__ == "__main__":
    unittest.main()
