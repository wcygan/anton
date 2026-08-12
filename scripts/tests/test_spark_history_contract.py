"""Behavior test for the Spark history source contract."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


class SparkHistoryContractTests(unittest.TestCase):
    def test_spark_history_source_passes(self) -> None:
        result = subprocess.run(
            ["python3", "scripts/validate-spark-history-contract.py"],
            cwd=REPO,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Spark history contract: PASS", result.stdout)

    def test_retention_cleaner_uses_distinct_success_and_failure_bounds(self) -> None:
        now = 2_000_000_000

        def pod(name: str, phase: str, age: int) -> dict[str, object]:
            finished = datetime.fromtimestamp(now - age, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            return {
                "metadata": {"name": name},
                "status": {
                    "phase": phase,
                    "containerStatuses": [{"state": {"terminated": {"finishedAt": finished}}}],
                },
            }

        fixture = {
            "items": [
                pod("success-expired", "Succeeded", 3600),
                pod("success-fresh", "Succeeded", 3599),
                pod("failure-expired", "Failed", 86400),
                pod("failure-fresh", "Failed", 86399),
            ]
        }

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            deletes = root / "deletes.txt"
            kubectl = root / "kubectl"
            kubectl.write_text(
                "#!/bin/sh\n"
                "if [ \"$1\" = get ]; then printf '%s' \"$POD_FIXTURE\"; exit 0; fi\n"
                "if [ \"$1\" = delete ]; then printf '%s\\n' \"$3\" >>\"$DELETE_LOG\"; exit 0; fi\n"
                "exit 1\n",
                encoding="utf-8",
            )
            kubectl.chmod(0o755)
            script = root / "retain-spark-pods.sh"
            source = (
                REPO / "kubernetes/apps/lakehouse/spark-history-server/app/retain-spark-pods.sh"
            ).read_text(encoding="utf-8")
            script.write_text(source.replace("$${", "${"), encoding="utf-8")

            environment = {
                **os.environ,
                "PATH": f"{root}:{os.environ['PATH']}",
                "POD_FIXTURE": json.dumps(fixture),
                "DELETE_LOG": str(deletes),
                "NOW_EPOCH_SECONDS": str(now),
                "SUCCESS_RETENTION_SECONDS": "3600",
                "FAILURE_RETENTION_SECONDS": "86400",
            }
            result = subprocess.run(
                ["/bin/sh", str(script)],
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(deletes.read_text(encoding="utf-8").splitlines(), ["success-expired", "failure-expired"])


if __name__ == "__main__":
    unittest.main()
