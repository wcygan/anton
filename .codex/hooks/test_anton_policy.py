#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Fixture tests for .codex/hooks/anton_policy.py."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / ".codex" / "hooks" / "anton_policy.py"


def run_hook(mode: str, payload: dict, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        ["python3", str(HOOK), mode],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=merged_env,
        timeout=10,
    )


class AntonPolicyTests(unittest.TestCase):
    def bash(self, command: str, cwd: str | None = None) -> dict:
        return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd or str(REPO)}

    def patch(self, body: str, cwd: str) -> dict:
        return {"tool_name": "apply_patch", "tool_input": {"command": body}, "cwd": cwd}

    def test_blocks_destructive_talos_reset(self) -> None:
        result = run_hook("pre", self.bash("task talos:reset"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("task talos:reset", result.stderr)

    def test_allows_read_only_secret_listing(self) -> None:
        result = run_hook("pre", self.bash("kubectl get secret app-secret -n default"))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_blocks_secret_yaml_dump(self) -> None:
        result = run_hook("pre", self.bash("kubectl get secret app-secret -n default -o yaml"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("Secret output", result.stderr)

    def test_blocks_tailnet_literal_in_patch(self) -> None:
        host = "realtail" + ".ts.net"
        patch = f"*** Begin Patch\n*** Add File: docs/example.md\n+hello {host}\n*** End Patch\n"
        with tempfile.TemporaryDirectory() as tmp:
            result = run_hook("pre", self.patch(patch, tmp), env={"ANTON_TAILNET_NAME": "realtail"})
        self.assertEqual(result.returncode, 2)
        self.assertIn("tailnet", result.stderr)

    def test_blocks_existing_encrypted_sops_patch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            secret = root / "kubernetes" / "apps" / "x" / "secret.sops.yaml"
            secret.parent.mkdir(parents=True)
            secret.write_text("data:\n  password: ENC[AES256,data]\nsops: {}\n")
            patch = "*** Begin Patch\n*** Update File: kubernetes/apps/x/secret.sops.yaml\n@@\n-data: {}\n+data: {}\n*** End Patch\n"
            result = run_hook("pre", self.patch(patch, tmp))
        self.assertEqual(result.returncode, 2)
        self.assertIn("SOPS-encrypted", result.stderr)

    def test_blocks_invalid_plan_status_after_patch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / "context" / "plans" / "0001-test.md"
            plan.parent.mkdir(parents=True)
            plan.write_text("---\nstatus: Almost\n---\n\n# test\n")
            patch = "*** Begin Patch\n*** Update File: context/plans/0001-test.md\n@@\n-status: Almost\n+status: Almost\n*** End Patch\n"
            result = run_hook("post", self.patch(patch, tmp))
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid status", result.stderr)

    def test_blocks_incomplete_flux_app_after_patch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "kubernetes" / "apps" / "default" / "demo" / "app"
            app.mkdir(parents=True)
            (app / "helmrelease.yaml").write_text("apiVersion: helm.toolkit.fluxcd.io/v2\nkind: HelmRelease\n")
            patch = "*** Begin Patch\n*** Update File: kubernetes/apps/default/demo/app/helmrelease.yaml\n@@\n-kind: HelmRelease\n+kind: HelmRelease\n*** End Patch\n"
            result = run_hook("post", self.patch(patch, tmp))
        self.assertEqual(result.returncode, 2)
        self.assertIn("missing required scaffold", result.stderr)

    def test_allows_namespace_kustomization_updates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            namespace = root / "kubernetes" / "apps" / "default"
            namespace.mkdir(parents=True)
            kust = namespace / "kustomization.yaml"
            kust.write_text("---\nresources:\n  - ./namespace.yaml\n")
            patch = "*** Begin Patch\n*** Update File: kubernetes/apps/default/kustomization.yaml\n@@\n resources:\n   - ./namespace.yaml\n+  - ./demo/ks.yaml\n*** End Patch\n"
            result = run_hook("post", self.patch(patch, tmp))
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
