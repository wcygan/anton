"""Parity tests for Claude and Codex safety-policy adapters."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
CLAUDE = REPO / ".claude" / "hooks"
CODEX = REPO / ".codex" / "hooks" / "anton_policy.py"


def run_hook(
    path: Path,
    payload: dict,
    *args: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        ["python3", str(path), *args],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=merged_env,
        timeout=10,
    )


class AgentPolicyAdapterTests(unittest.TestCase):
    def assert_command_blocked_by_both(self, command: str) -> None:
        payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(REPO)}
        claude = run_hook(CLAUDE / "guard_destructive.py", payload)
        codex = run_hook(CODEX, payload, "pre")
        self.assertEqual(claude.returncode, 2, claude.stderr)
        self.assertEqual(codex.returncode, 2, codex.stderr)

    def assert_command_allowed_by_both(self, command: str) -> None:
        payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(REPO)}
        claude = run_hook(CLAUDE / "guard_destructive.py", payload)
        codex = run_hook(CODEX, payload, "pre")
        self.assertEqual(claude.returncode, 0, claude.stderr)
        self.assertEqual(codex.returncode, 0, codex.stderr)

    def test_talos_apply_requires_approval_for_both_adapters(self) -> None:
        self.assert_command_blocked_by_both("talosctl apply-config --mode=auto -f machine.yaml")

    def test_direct_wrapper_does_not_bypass_approval(self) -> None:
        for command in (
            "env FOO=bar talosctl apply-config --mode=auto -f machine.yaml",
            "env -i talosctl apply-config --mode=auto -f machine.yaml",
            "command talosctl apply-config --mode=auto -f machine.yaml",
            "mise exec -- talosctl apply-config --mode=auto -f machine.yaml",
        ):
            with self.subTest(command=command):
                self.assert_command_blocked_by_both(command)

    def test_indirect_shell_does_not_bypass_approval(self) -> None:
        self.assert_command_blocked_by_both(
            "bash -lc 'talosctl apply-config --mode=auto -f machine.yaml'"
        )

    def test_absolute_binary_path_does_not_bypass_approval(self) -> None:
        self.assert_command_blocked_by_both(
            "/usr/local/bin/talosctl apply-config --mode=auto -f machine.yaml"
        )

    def test_global_flags_do_not_hide_protected_cluster_verbs(self) -> None:
        for command in (
            "kubectl --as admin delete namespace demo",
            "kubectl --token token delete namespace demo",
            "kubectl --request-timeout 5s delete namespace demo",
            "flux --timeout 5s suspend ks demo",
            "talosctl --timeout 5s reset",
        ):
            with self.subTest(command=command):
                self.assert_command_blocked_by_both(command)

    def test_protected_words_as_read_operands_remain_allowed(self) -> None:
        for command in (
            "flux get ks suspend",
            "flux get source git uninstall",
            "kubectl get pod delete namespace",
            "talosctl get reset",
            "rm -rf /tmp/demo",
            "rm -rf ${HOMEDIR}",
            "timeout -sKILL 10 rm -rf /tmp/demo",
        ):
            with self.subTest(command=command):
                self.assert_command_allowed_by_both(command)

    def test_wrappers_do_not_hide_non_cluster_destructive_commands(self) -> None:
        for command in (
            "bash -lc 'task talos:reset'",
            "sudo task talos:reset",
            "/usr/bin/env task talos:reset",
            "bash -lc 'helmfile destroy'",
            "sudo helmfile destroy",
            "/usr/bin/env helmfile destroy",
            "bash -lc 'rm -rf /'",
            "sudo rm -rf /",
            "rm -rf -- /",
            "`task talos:reset`",
            "eval 'helmfile destroy'",
            "exec rm -rf /",
            "nohup rm -rf /",
            "timeout 10 rm -rf /",
            "nice rm -rf /",
            "time rm -rf /",
            "env -S'rm -rf /'",
            "env -vS'rm -rf /'",
            "timeout -sKILL 10 rm -rf /",
            "timeout -k1 10 rm -rf /",
            "timeout -v 10 rm -rf /",
            "timeout -f 10 rm -rf /",
            "timeout -p 10 rm -rf /",
            "{ rm -rf /; }",
            "if true; then rm -rf /; fi",
            "for item in one; do rm -rf /; done",
            "case one in one) rm -rf /;; esac",
            "rm -rf ${HOME}",
            "rm -rf ${HOME}/",
            "rm -rf //",
            "rm -rf /.",
            "rm -rf /tmp/..",
            "rm -rf /Users/../Users/example",
        ):
            with self.subTest(command=command):
                self.assert_command_blocked_by_both(command)

    def test_scoped_flux_suspend_requires_approval_for_both_adapters(self) -> None:
        self.assert_command_blocked_by_both("flux suspend ks demo -nfoo")

    def test_secret_output_is_blocked_by_both_adapters(self) -> None:
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "kubectl get secret demo -o yaml"},
            "cwd": str(REPO),
        }
        claude = run_hook(CLAUDE / "guard_secret_leak.py", payload)
        codex = run_hook(CODEX, payload, "pre")
        self.assertEqual(claude.returncode, 2, claude.stderr)
        self.assertEqual(codex.returncode, 2, codex.stderr)

    def test_absolute_kubectl_secret_output_is_blocked_by_both_adapters(self) -> None:
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "/usr/local/bin/kubectl get secret demo -o yaml"},
            "cwd": str(REPO),
        }
        claude = run_hook(CLAUDE / "guard_secret_leak.py", payload)
        codex = run_hook(CODEX, payload, "pre")
        self.assertEqual(claude.returncode, 2, claude.stderr)
        self.assertEqual(codex.returncode, 2, codex.stderr)

    def test_secret_structured_output_forms_are_blocked_by_both_adapters(self) -> None:
        for command in (
            "kubectl get secret demo -o=jsonpath='{.data}'",
            "kubectl get secrets.v1/demo --output json",
            "kubectl get secrets,configmaps -oyaml",
            "`kubectl get secret demo -o yaml`",
        ):
            with self.subTest(command=command):
                payload = {
                    "tool_name": "Bash",
                    "tool_input": {"command": command},
                    "cwd": str(REPO),
                }
                claude = run_hook(CLAUDE / "guard_secret_leak.py", payload)
                codex = run_hook(CODEX, payload, "pre")
                self.assertEqual(claude.returncode, 2, claude.stderr)
                self.assertEqual(codex.returncode, 2, codex.stderr)

    def test_global_flags_do_not_hide_secret_output(self) -> None:
        command = "kubectl --as admin --request-timeout 5s get secret demo -o yaml"
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "cwd": str(REPO),
        }
        claude = run_hook(CLAUDE / "guard_secret_leak.py", payload)
        codex = run_hook(CODEX, payload, "pre")
        self.assertEqual(claude.returncode, 2, claude.stderr)
        self.assertEqual(codex.returncode, 2, codex.stderr)

    def test_protected_credential_set_is_shared(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "github-push-token.txt"
            claude_payload = {"tool_name": "Edit", "tool_input": {"file_path": str(path)}}
            codex_patch = (
                "*** Begin Patch\n"
                "*** Update File: github-push-token.txt\n"
                "@@\n-old\n+new\n"
                "*** End Patch\n"
            )
            codex_payload = {
                "tool_name": "apply_patch",
                "tool_input": {"command": codex_patch},
                "cwd": str(root),
            }
            claude = run_hook(CLAUDE / "guard_sops.py", claude_payload)
            codex = run_hook(CODEX, codex_payload, "pre")
            self.assertEqual(claude.returncode, 2, claude.stderr)
            self.assertEqual(codex.returncode, 2, codex.stderr)

    def test_encrypted_sops_edit_is_blocked_by_both_adapters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "secret.sops.yaml"
            path.write_text("value: ENC[AES256_GCM,data:test]\nsops:\n", encoding="utf-8")
            claude_payload = {"tool_name": "Edit", "tool_input": {"file_path": str(path)}}
            codex_patch = (
                "*** Begin Patch\n"
                "*** Update File: secret.sops.yaml\n"
                "@@\n-old\n+new\n"
                "*** End Patch\n"
            )
            codex_payload = {
                "tool_name": "apply_patch",
                "tool_input": {"command": codex_patch},
                "cwd": str(root),
            }
            claude = run_hook(CLAUDE / "guard_sops.py", claude_payload)
            codex = run_hook(CODEX, codex_payload, "pre")
            self.assertEqual(claude.returncode, 2, claude.stderr)
            self.assertEqual(codex.returncode, 2, codex.stderr)

    def test_tailnet_literal_is_blocked_by_both_adapters(self) -> None:
        host = "real-tailnet" + ".ts.net"
        env = {"ANTON_TAILNET_NAME": "real-tailnet"}
        claude_payload = {"tool_name": "Edit", "tool_input": {"new_string": host}}
        codex_patch = f"*** Begin Patch\n*** Add File: docs/example.md\n+{host}\n*** End Patch\n"
        codex_payload = {
            "tool_name": "apply_patch",
            "tool_input": {"command": codex_patch},
            "cwd": str(REPO),
        }
        claude = run_hook(CLAUDE / "guard_tailnet.py", claude_payload, env=env)
        codex = run_hook(CODEX, codex_payload, "pre", env=env)
        self.assertEqual(claude.returncode, 2, claude.stderr)
        self.assertEqual(codex.returncode, 2, codex.stderr)

    @unittest.skipUnless(shutil.which("yq"), "yq is required for YAML adapter parity")
    def test_invalid_yaml_is_blocked_by_both_adapters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "kubernetes" / "apps" / "broken.yaml"
            path.parent.mkdir(parents=True)
            path.write_text("key: [\n", encoding="utf-8")
            claude_payload = {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(path)},
                "cwd": str(root),
            }
            codex_patch = (
                "*** Begin Patch\n"
                "*** Update File: kubernetes/apps/broken.yaml\n"
                "@@\n-key: []\n+key: [\n"
                "*** End Patch\n"
            )
            codex_payload = {
                "tool_name": "apply_patch",
                "tool_input": {"command": codex_patch},
                "cwd": str(root),
            }
            claude = run_hook(CLAUDE / "validate_yaml.py", claude_payload)
            codex = run_hook(CODEX, codex_payload, "post")
            self.assertEqual(claude.returncode, 2, claude.stderr)
            self.assertEqual(codex.returncode, 2, codex.stderr)

    def test_invalid_plan_status_is_blocked_by_both_adapters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "context" / "plans" / "0001-example.md"
            path.parent.mkdir(parents=True)
            path.write_text("---\nstatus: mystery\n---\n", encoding="utf-8")
            claude_payload = {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(path)},
                "cwd": str(root),
            }
            codex_patch = (
                "*** Begin Patch\n"
                "*** Update File: context/plans/0001-example.md\n"
                "@@\n-status: draft\n+status: mystery\n"
                "*** End Patch\n"
            )
            codex_payload = {
                "tool_name": "apply_patch",
                "tool_input": {"command": codex_patch},
                "cwd": str(root),
            }
            claude = run_hook(CLAUDE / "validate_plan_status.py", claude_payload)
            codex = run_hook(CODEX, codex_payload, "post")
            self.assertEqual(claude.returncode, 2, claude.stderr)
            self.assertEqual(codex.returncode, 2, codex.stderr)


if __name__ == "__main__":
    unittest.main()
