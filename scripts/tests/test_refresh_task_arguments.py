"""Exercise Task interpolation with an inert script, never a cluster command."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


class RefreshTaskArgumentTests(unittest.TestCase):
    def test_untrusted_values_arrive_as_literal_arguments(self):
        definition = json.loads(subprocess.check_output(
            ["yq", "-o=json", '.tasks."external-secrets:force-refresh"', str(REPO / "Taskfile.yaml")],
            text=True,
        ))
        # Only remove environment prerequisites; retain the real command,
        # parameter requirements, prompt, and variable-to-environment mapping.
        definition.pop("preconditions")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            stub = root / "scripts/force-external-secret-refresh.sh"
            stub.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > captured.txt\n')
            stub.chmod(0o700)
            taskfile = root / "Taskfile.yaml"
            taskfile.write_text(json.dumps({"version": "3", "tasks": {"refresh": definition}}))
            for value in ('$(touch injected)', '`touch injected`', '"; touch injected; #', 'valid-name'):
                for variable in ("NAMESPACE", "NAME"):
                    with self.subTest(value=value, variable=variable):
                        values = {"NAMESPACE": "example", "NAME": "credentials"}
                        values[variable] = value
                        result = subprocess.run(
                            ["task", "--yes", "--taskfile", str(taskfile), "refresh",
                             *[f"{key}={item}" for key, item in values.items()]],
                            cwd=root, text=True, capture_output=True, timeout=10,
                        )
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertFalse((root / "injected").exists())
                        self.assertEqual((root / "captured.txt").read_text().splitlines(), list(values.values()))


if __name__ == "__main__":
    unittest.main()
