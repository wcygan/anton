"""Prove both agent hook adapters execute the shared Flux contract."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
VALID_MANIFEST = REPO / "kubernetes" / "apps" / "observability" / "loki" / "app" / "helmrelease.yaml"


class FluxHookAdapterTests(unittest.TestCase):
    def test_codex_adapter(self) -> None:
        patch = (
            "*** Begin Patch\n"
            "*** Update File: kubernetes/apps/observability/loki/app/helmrelease.yaml\n"
            "@@\n-kind: HelmRelease\n+kind: HelmRelease\n"
            "*** End Patch\n"
        )
        payload = {"tool_name": "apply_patch", "tool_input": {"command": patch}, "cwd": str(REPO)}
        result = subprocess.run(
            ["python3", str(REPO / ".codex" / "hooks" / "anton_policy.py"), "post"],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_claude_adapter(self) -> None:
        payload = {"tool_name": "Edit", "tool_input": {"file_path": str(VALID_MANIFEST)}}
        result = subprocess.run(
            ["python3", str(REPO / ".claude" / "hooks" / "check_3_file_pattern.py")],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
