"""Tests for target resolution and mutation preflight."""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "lib"))

from cluster_target_contract import (  # noqa: E402
    TargetPreflightError,
    anton_kubectl_prefix,
    classify_command,
    expected_talos_cluster,
    expected_talos_context,
    preflight_command,
    resolve_talos_targets,
)


def status(nodes: dict[str, str], suffix: str = "example.invalid") -> str:
    peers = {
        name: {"HostName": name, "DNSName": f"{name}.{suffix}.", "TailscaleIPs": [address]}
        for name, address in nodes.items()
    }
    return json.dumps({"MagicDNSSuffix": suffix, "Peer": peers})


class Runner:
    def __init__(self, outputs: dict[tuple[str, ...], str | None]):
        self.outputs = outputs

    def __call__(self, command: list[str]) -> str | None:
        return self.outputs.get(tuple(command))


class ClusterTargetContractTests(unittest.TestCase):
    @staticmethod
    def _talos_lan_addresses() -> list[str]:
        source = (REPO / "talos" / "talconfig.yaml").read_text(encoding="utf-8")
        return re.findall(r'(?m)^\s+ipAddress:\s*["\']?([^"\'\s]+)', source)

    def test_committed_talos_context_matches_generated_config(self) -> None:
        source = (REPO / "talos" / "talconfig.yaml").read_text(encoding="utf-8")
        cluster = re.search(r"(?m)^clusterName:\s*(\S+)", source)
        self.assertIsNotNone(cluster)
        self.assertEqual(expected_talos_context(REPO, environ={}), cluster.group(1))
        self.assertEqual(expected_talos_cluster(REPO), cluster.group(1))

    def test_uses_complete_live_tailscale_inventory(self) -> None:
        live = {"k8s-1": "100.64.0.1", "k8s-2": "100.64.0.2", "k8s-3": "100.64.0.3"}
        runner = Runner({("tailscale", "status", "--json"): status(live)})
        result = resolve_talos_targets(REPO, environ={}, runner=runner)
        self.assertEqual(result.source, "live")
        self.assertEqual({node.name: node.address for node in result.nodes}, live)

    def test_falls_back_as_one_complete_set(self) -> None:
        partial = {"k8s-1": "100.64.0.1"}
        runner = Runner({("tailscale", "status", "--json"): status(partial)})
        result = resolve_talos_targets(REPO, environ={}, runner=runner)
        self.assertEqual(result.source, "fallback")
        self.assertEqual(result.fallback_reason, "live node set incomplete")
        self.assertEqual(len(result.nodes), 3)

    def test_uses_macos_tailscale_application_when_cli_is_not_on_path(self) -> None:
        live = {"k8s-1": "100.64.0.1", "k8s-2": "100.64.0.2", "k8s-3": "100.64.0.3"}
        runner = Runner(
            {
                ("tailscale", "status", "--json"): None,
                (
                    "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
                    "status",
                    "--json",
                ): status(live),
            }
        )
        result = resolve_talos_targets(REPO, environ={}, runner=runner)
        self.assertEqual(result.source, "live")

    def test_redacted_evidence_hides_addresses(self) -> None:
        result = resolve_talos_targets(REPO, source="fallback", environ={})
        evidence = result.evidence()
        self.assertTrue(all(node["address"] == "<redacted>" for node in evidence["nodes"]))

    def test_address_list_preserves_resolved_node_order(self) -> None:
        result = resolve_talos_targets(REPO, source="fallback", environ={})
        self.assertEqual(result.addresses().split(","), [node.address for node in result.nodes])

    def test_anton_kubectl_prefix_binds_verified_context_and_endpoint(self) -> None:
        canonical = str(REPO / "kubeconfig")
        expected = "expected-context"
        expected_endpoint = "https://expected.invalid"
        endpoint_query = ("config", "view", "--minify", "-o", "jsonpath={.clusters[0].cluster.server}")
        runner = Runner(
            {
                (
                    "mise",
                    "exec",
                    "--",
                    "kubectl",
                    "--kubeconfig",
                    canonical,
                    "config",
                    "current-context",
                ): expected,
                (
                    "mise",
                    "exec",
                    "--",
                    "kubectl",
                    "--kubeconfig",
                    canonical,
                    "--context",
                    expected,
                    *endpoint_query,
                ): expected_endpoint,
            }
        )
        prefix = anton_kubectl_prefix(
            REPO,
            environ={"ANTON_KUBE_CONTEXT": expected, "ANTON_KUBE_ENDPOINT": expected_endpoint},
            runner=runner,
        )
        self.assertEqual(
            prefix,
            (
                "mise",
                "exec",
                "--",
                "kubectl",
                "--kubeconfig",
                canonical,
                "--context",
                expected,
            ),
        )

    def test_anton_kubectl_prefix_fails_closed_without_context(self) -> None:
        runner = Runner({})
        with self.assertRaisesRegex(TargetPreflightError, "cannot resolve Kubernetes context") as caught:
            anton_kubectl_prefix(
                REPO,
                environ={"ANTON_KUBE_CONTEXT": "expected-context"},
                runner=runner,
            )
        self.assertNotIn("expected-context", str(caught.exception))

    def test_anton_kubectl_prefix_rejects_wrong_context_without_identity(self) -> None:
        canonical = str(REPO / "kubeconfig")
        runner = Runner(
            {
                (
                    "mise",
                    "exec",
                    "--",
                    "kubectl",
                    "--kubeconfig",
                    canonical,
                    "config",
                    "current-context",
                ): "wrong-context",
            }
        )
        with self.assertRaisesRegex(TargetPreflightError, "context is not the Anton target") as caught:
            anton_kubectl_prefix(
                REPO,
                environ={
                    "ANTON_KUBE_CONTEXT": "expected-context",
                    "ANTON_KUBE_ENDPOINT": "https://expected.invalid",
                },
                runner=runner,
            )
        self.assertNotIn("wrong-context", str(caught.exception))
        self.assertNotIn("expected-context", str(caught.exception))

    def test_anton_kubectl_prefix_rejects_wrong_endpoint_without_identity(self) -> None:
        canonical = str(REPO / "kubeconfig")
        expected = "expected-context"
        endpoint_query = ("config", "view", "--minify", "-o", "jsonpath={.clusters[0].cluster.server}")
        runner = Runner(
            {
                (
                    "mise",
                    "exec",
                    "--",
                    "kubectl",
                    "--kubeconfig",
                    canonical,
                    "config",
                    "current-context",
                ): expected,
                (
                    "mise",
                    "exec",
                    "--",
                    "kubectl",
                    "--kubeconfig",
                    canonical,
                    "--context",
                    expected,
                    *endpoint_query,
                ): "https://wrong.invalid",
            }
        )
        with self.assertRaisesRegex(TargetPreflightError, "endpoint is not the Anton target") as caught:
            anton_kubectl_prefix(
                REPO,
                environ={
                    "ANTON_KUBE_CONTEXT": expected,
                    "ANTON_KUBE_ENDPOINT": "https://expected.invalid",
                },
                runner=runner,
            )
        self.assertNotIn("wrong.invalid", str(caught.exception))
        self.assertNotIn("expected.invalid", str(caught.exception))

    def test_anton_kubectl_prefix_rejects_self_referential_operator_kubeconfig(self) -> None:
        canonical = str(REPO / "kubeconfig")
        untrusted_context = "tailscale-operator.untrusted.invalid"
        endpoint_query = ("config", "view", "--minify", "-o", "jsonpath={.clusters[0].cluster.server}")
        runner = Runner(
            {
                ("tailscale", "status", "--json"): None,
                (
                    "mise",
                    "exec",
                    "--",
                    "kubectl",
                    "--kubeconfig",
                    canonical,
                    "config",
                    "current-context",
                ): untrusted_context,
                (
                    "mise",
                    "exec",
                    "--",
                    "kubectl",
                    "--kubeconfig",
                    canonical,
                    "--context",
                    untrusted_context,
                    *endpoint_query,
                ): "https://untrusted.invalid:6443",
            }
        )
        with self.assertRaisesRegex(TargetPreflightError, "context is not the Anton target") as caught:
            anton_kubectl_prefix(REPO, environ={}, runner=runner)
        self.assertNotIn("untrusted", str(caught.exception))

    def test_classifies_wrapped_commands(self) -> None:
        reads = classify_command("mise exec -- kubectl get pods -A")
        mutation = classify_command("mise exec -- kubectl -n observability port-forward svc/loki 3100:3100")
        piped_mutation = classify_command("printf manifest | kubectl apply -f -")
        local = classify_command("talosctl config context kubernetes")
        self.assertEqual(reads[0].classification, "read")
        self.assertEqual(mutation[0].classification, "cluster-mutation")
        self.assertEqual(piped_mutation[0].classification, "cluster-mutation")
        self.assertEqual(local[0].classification, "local-mutation")

    def test_classifies_safe_execution_wrappers(self) -> None:
        env_wrapped = classify_command("env FOO=bar kubectl apply -f app.yaml")
        absolute_env_wrapped = classify_command("/usr/bin/env FOO=bar kubectl apply -f app.yaml")
        command_wrapped = classify_command("command kubectl apply -f app.yaml")
        self.assertEqual(env_wrapped[0].classification, "cluster-mutation")
        self.assertEqual(absolute_env_wrapped[0].classification, "cluster-mutation")
        self.assertEqual(command_wrapped[0].classification, "cluster-mutation")

        command_path = classify_command("command -p kubectl apply -f app.yaml")
        self.assertEqual(command_path[0].classification, "ambiguous-mutation")
        violations = preflight_command(
            "command -p kubectl apply -f app.yaml",
            REPO,
            environ={"ANTON_KUBE_CONTEXT": "expected-context"},
            runner=Runner({}),
        )
        self.assertEqual(len(violations), 1)
        self.assertIn("environment", violations[0].message)

    def test_classifies_common_execution_wrappers(self) -> None:
        for command in (
            "exec kubectl apply -f app.yaml",
            "nohup kubectl apply -f app.yaml",
            "timeout 10 kubectl apply -f app.yaml",
            "nice kubectl apply -f app.yaml",
            "time kubectl apply -f app.yaml",
            "timeout -sKILL 10 kubectl apply -f app.yaml",
            "timeout -k1 10 kubectl apply -f app.yaml",
            "timeout -v 10 kubectl apply -f app.yaml",
            "timeout -f 10 kubectl apply -f app.yaml",
            "timeout -p 10 kubectl apply -f app.yaml",
        ):
            with self.subTest(command=command):
                operations = classify_command(command)
                self.assertEqual(len(operations), 1)
                self.assertEqual(operations[0].classification, "cluster-mutation")

    def test_preflight_rejects_explicit_wrong_context(self) -> None:
        runner = Runner({("kubectl", "config", "current-context"): "expected-context"})
        violations = preflight_command(
            "kubectl --context definitely-wrong delete pod demo",
            REPO,
            environ={"ANTON_KUBE_CONTEXT": "expected-context"},
            runner=runner,
        )
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].actual, "definitely-wrong")

        repeated_kube = classify_command(
            "kubectl --kubeconfig first --kubeconfig=last "
            "--context expected-context --context definitely-wrong "
            "--server https://first.invalid --server=https://last.invalid apply -f app.yaml"
        )[0]
        self.assertEqual(repeated_kube.config_path, "last")
        self.assertEqual(repeated_kube.context, "definitely-wrong")
        self.assertEqual(repeated_kube.server, "https://last.invalid")
        repeated_violations = preflight_command(
            "kubectl --context expected-context --context definitely-wrong apply -f app.yaml",
            REPO,
            environ={
                "ANTON_KUBE_CONTEXT": "expected-context",
                "ANTON_KUBE_ENDPOINT": "https://expected.invalid",
            },
            runner=runner,
        )
        self.assertEqual(len(repeated_violations), 1)
        self.assertEqual(repeated_violations[0].actual, "definitely-wrong")

        repeated_talos = classify_command(
            "talosctl --talosconfig first --talosconfig=last "
            "--context kubernetes --context wrong "
            "--cluster first --cluster=last "
            "--nodes node-a --nodes=node-b,node-c "
            "--endpoints endpoint-a --endpoints=endpoint-b,endpoint-c reboot"
        )[0]
        self.assertEqual(repeated_talos.config_path, "last")
        self.assertEqual(repeated_talos.context, "wrong")
        self.assertEqual(repeated_talos.cluster, "last")
        self.assertEqual(repeated_talos.nodes, ("node-a", "node-b", "node-c"))
        self.assertEqual(
            repeated_talos.endpoints,
            ("endpoint-a", "endpoint-b", "endpoint-c"),
        )
        talos_violations = preflight_command(
            "talosctl --context kubernetes --context wrong reboot",
            REPO,
            environ={},
            runner=Runner({}),
        )
        self.assertEqual(len(talos_violations), 1)
        self.assertEqual(talos_violations[0].actual, "wrong")

    def test_kuberc_flag_value_does_not_hide_mutation_verb(self) -> None:
        operations = classify_command("kubectl --kuberc get apply -f app.yaml")
        self.assertEqual(operations[0].subcommand, "apply")
        self.assertEqual(operations[0].classification, "cluster-mutation")

    def test_preflight_rejects_indirect_mutations(self) -> None:
        for command in (
            "sudo kubectl apply -f app.yaml",
            "bash -c 'kubectl apply -f app.yaml'",
            "bash -lc 'kubectl apply -f app.yaml'",
            "zsh -ic 'kubectl apply -f app.yaml'",
            "sudo sh -c 'kubectl apply -f app.yaml'",
            "$(kubectl apply -f app.yaml)",
            "`kubectl apply -f app.yaml`",
            "echo `kubectl apply -f app.yaml`",
            "echo \"`kubectl apply -f app.yaml`\"",
            "echo \"$(kubectl apply -f app.yaml)\"",
            "eval 'kubectl apply -f app.yaml'",
            "cd /tmp && mise exec -- kubectl apply -f app.yaml",
            "{ kubectl apply -f app.yaml; }",
            "if true; then kubectl apply -f app.yaml; fi",
            "for item in one; do kubectl apply -f app.yaml; done",
            "case one in one) kubectl apply -f app.yaml;; esac",
        ):
            with self.subTest(command=command):
                violations = preflight_command(
                    command,
                    REPO,
                    environ={"ANTON_KUBE_CONTEXT": "expected-context"},
                    runner=Runner({("kubectl", "config", "current-context"): "expected-context"}),
                )
                self.assertEqual(len(violations), 1)
                self.assertIn("indirect", violations[0].message)

    def test_preflight_rejects_environment_that_hides_target_config(self) -> None:
        runner = Runner({("kubectl", "config", "current-context"): "expected-context"})
        for command in (
            "env -i kubectl apply -f app.yaml",
            "env -u KUBECONFIG kubectl apply -f app.yaml",
            "env -u KUBECONFIG -i kubectl apply -f app.yaml",
            "env -C /tmp kubectl apply -f app.yaml",
            "env --chdir=/tmp kubectl apply -f app.yaml",
            "env -S'kubectl apply -f app.yaml'",
            "env -vS'kubectl apply -f app.yaml'",
            "MISE_CONFIG_FILE=/tmp/other.toml mise exec -- kubectl apply -f app.yaml",
            "HOME=/tmp kubectl apply -f app.yaml",
            "env HOME=/tmp kubectl apply -f app.yaml",
            "HOME=/tmp; kubectl apply -f app.yaml",
            "FOO=x HOME=/tmp; kubectl apply -f app.yaml",
            "PATH=/tmp kubectl apply -f app.yaml",
        ):
            with self.subTest(command=command):
                violations = preflight_command(
                    command,
                    REPO,
                    environ={"ANTON_KUBE_CONTEXT": "expected-context"},
                    runner=runner,
                )
                self.assertEqual(len(violations), 1)
                self.assertRegex(violations[0].message, r"environment|indirect")

    def test_preflight_uses_explicit_executable_for_target_query(self) -> None:
        runner = Runner({("kubectl", "config", "current-context"): "expected-context"})
        violations = preflight_command(
            "/tmp/kubectl apply -f app.yaml",
            REPO,
            environ={"ANTON_KUBE_CONTEXT": "expected-context"},
            runner=runner,
        )
        self.assertEqual(len(violations), 1)
        self.assertIn("cannot resolve", violations[0].message)

        wrapped = preflight_command(
            "mise exec -- /tmp/kubectl apply -f app.yaml",
            REPO,
            environ={"ANTON_KUBE_CONTEXT": "expected-context"},
            runner=runner,
        )
        self.assertEqual(len(wrapped), 1)
        self.assertIn("cannot resolve", wrapped[0].message)

    def test_mise_options_are_preserved_for_context_query(self) -> None:
        endpoint_query = ("config", "view", "--minify", "-o", "jsonpath={.clusters[0].cluster.server}")
        runner = Runner(
            {
                (
                    "mise",
                    "--cd",
                    "/tmp",
                    "exec",
                    "--",
                    "kubectl",
                    "config",
                    "current-context",
                ): "expected-context",
                (
                    "mise",
                    "--cd",
                    "/tmp",
                    "exec",
                    "--",
                    "kubectl",
                    "--context",
                    "expected-context",
                    *endpoint_query,
                ): "https://expected.invalid",
            }
        )
        self.assertEqual(
            preflight_command(
                "mise --cd /tmp exec -- kubectl apply -f app.yaml",
                REPO,
                environ={
                    "ANTON_KUBE_CONTEXT": "expected-context",
                    "ANTON_KUBE_ENDPOINT": "https://expected.invalid",
                },
                runner=runner,
            ),
            [],
        )

    def test_mise_wrapper_is_preserved_for_talos_context_query(self) -> None:
        endpoints = ",".join(self._talos_lan_addresses())
        runner = Runner(
            {
                (
                    "mise",
                    "exec",
                    "--",
                    "talosctl",
                    "config",
                    "info",
                ): f"Current context: kubernetes\nNodes: not defined\nEndpoints: {endpoints}\n",
                ("tailscale", "status", "--json"): None,
            }
        )
        self.assertEqual(
            preflight_command(
                "mise exec -- talosctl reboot",
                REPO,
                environ={},
                runner=runner,
            ),
            [],
        )

    def test_talos_config_ignores_not_defined_node_sentinel(self) -> None:
        lan_addresses = self._talos_lan_addresses()
        info = (
            "Current context: kubernetes\n"
            "Nodes: not defined\n"
            f"Endpoints: {','.join(lan_addresses)}\n"
        )
        runner = Runner(
            {
                (
                    "talosctl",
                    "--talosconfig",
                    "./talos/clusterconfig/talosconfig",
                    "config",
                    "info",
                ): info,
                ("tailscale", "status", "--json"): None,
            }
        )
        self.assertEqual(
            preflight_command(
                "TALOSCONFIG=./talos/clusterconfig/talosconfig talosctl reboot",
                REPO,
                environ={},
                runner=runner,
            ),
            [],
        )

    def test_indirect_read_remains_read_only(self) -> None:
        operations = classify_command("sudo kubectl get pods -A")
        self.assertEqual(operations[0].classification, "read")
        self.assertEqual(preflight_command("sudo kubectl get pods -A", REPO, environ={}), [])

    def test_preflight_honors_command_scoped_kubeconfig(self) -> None:
        runner = Runner(
            {
                ("kubectl", "--kubeconfig", "/tmp/wrong", "config", "current-context"): "wrong-context",
            }
        )
        violations = preflight_command(
            "KUBECONFIG=/tmp/wrong kubectl delete pod demo",
            REPO,
            environ={"ANTON_KUBE_CONTEXT": "expected-context"},
            runner=runner,
        )
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].actual, "wrong-context")

    def test_preflight_honors_explicit_kubeconfig_flag(self) -> None:
        runner = Runner(
            {
                ("kubectl", "--kubeconfig", "/tmp/wrong", "config", "current-context"): "wrong-context",
            }
        )
        violations = preflight_command(
            "kubectl --kubeconfig=/tmp/wrong delete pod demo",
            REPO,
            environ={"ANTON_KUBE_CONTEXT": "expected-context"},
            runner=runner,
        )
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].actual, "wrong-context")

    def test_preflight_rejects_kube_server_override(self) -> None:
        runner = Runner(
            {
                ("kubectl", "config", "current-context"): "expected-context",
            }
        )
        violations = preflight_command(
            "kubectl --server https://wrong.invalid apply -f app.yaml",
            REPO,
            environ={
                "ANTON_KUBE_CONTEXT": "expected-context",
                "ANTON_KUBE_ENDPOINT": "https://expected.invalid",
            },
            runner=runner,
        )
        self.assertEqual(len(violations), 1)
        self.assertIn("endpoint", violations[0].message)

    def test_preflight_verifies_kubeconfig_cluster_identity(self) -> None:
        endpoint_query = ("config", "view", "--minify", "-o", "jsonpath={.clusters[0].cluster.server}")
        runner = Runner(
            {
                ("kubectl", "--kubeconfig", "/tmp/other", "config", "current-context"): "expected-context",
                (
                    "kubectl",
                    "--kubeconfig",
                    "/tmp/other",
                    "--context",
                    "expected-context",
                    *endpoint_query,
                ): "https://wrong.invalid",
            }
        )
        violations = preflight_command(
            "KUBECONFIG=/tmp/other kubectl apply -f app.yaml",
            REPO,
            environ={
                "ANTON_KUBE_CONTEXT": "expected-context",
                "ANTON_KUBE_ENDPOINT": "https://expected.invalid",
            },
            runner=runner,
        )
        self.assertEqual(len(violations), 1)
        self.assertIn("endpoint", violations[0].message)

    def test_preflight_honors_talos_context_and_config(self) -> None:
        cases = (
            ("talosctl --context wrong-context reboot", Runner({})),
            (
                "TALOSCONFIG=/tmp/wrong talosctl reboot",
                Runner(
                    {
                        ("talosctl", "--talosconfig", "/tmp/wrong", "config", "info"): "context: wrong-context",
                    }
                ),
            ),
        )
        for command, runner in cases:
            with self.subTest(command=command):
                violations = preflight_command(
                    command,
                    REPO,
                    environ={"ANTON_TALOS_CONTEXT": "expected-context"},
                    runner=runner,
                )
                self.assertEqual(len(violations), 1)
                self.assertEqual(violations[0].actual, "wrong-context")

    def test_preflight_rejects_talos_target_outside_inventory(self) -> None:
        runner = Runner(
            {
                ("tailscale", "status", "--json"): None,
                ("talosctl", "config", "info"): "Current context: kubernetes\n",
            }
        )
        violations = preflight_command(
            "talosctl --nodes 203.0.113.99 reboot",
            REPO,
            environ={},
            runner=runner,
        )
        self.assertEqual(len(violations), 1)
        self.assertIn("target", violations[0].message)

        implicit = preflight_command("talosctl reboot", REPO, environ={}, runner=runner)
        self.assertEqual(len(implicit), 1)
        self.assertIn("target", implicit[0].message)

    def test_preflight_rejects_wrong_talos_proxy_cluster(self) -> None:
        runner = Runner(
            {
                ("talosctl", "config", "info"): "Current context: kubernetes\n",
            }
        )
        violations = preflight_command(
            "talosctl --cluster other reboot",
            REPO,
            environ={},
            runner=runner,
        )
        self.assertEqual(len(violations), 1)
        self.assertIn("proxy cluster", violations[0].message)

    def test_ignores_cluster_binary_names_inside_quoted_search_patterns(self) -> None:
        operations = classify_command("rg -n 'kubectl|talosctl|flux' AGENTS.md | head")
        self.assertEqual(operations, ())

    def test_preflight_fails_closed_when_context_is_missing(self) -> None:
        runner = Runner({("tailscale", "status", "--json"): None, ("kubectl", "config", "current-context"): None})
        violations = preflight_command("kubectl apply -f app.yaml", REPO, environ={}, runner=runner)
        self.assertEqual(len(violations), 1)
        self.assertIn("cannot resolve", violations[0].message)

    def test_preflight_accepts_expected_live_context(self) -> None:
        live_status = status({"k8s-1": "100.64.0.1", "k8s-2": "100.64.0.2", "k8s-3": "100.64.0.3"})
        expected = "tailscale-operator.example.invalid"
        endpoint_query = ("config", "view", "--minify", "-o", "jsonpath={.clusters[0].cluster.server}")
        runner = Runner(
            {
                ("tailscale", "status", "--json"): live_status,
                ("kubectl", "config", "current-context"): expected,
                ("kubectl", "--context", expected, *endpoint_query): f"https://{expected}",
            }
        )
        self.assertEqual(preflight_command("kubectl exec pod -- true", REPO, environ={}, runner=runner), [])

        canonical_config = str(REPO / "kubeconfig")
        canonical_runner = Runner(
            {
                (
                    "mise",
                    "exec",
                    "--",
                    "kubectl",
                    "--kubeconfig",
                    canonical_config,
                    "config",
                    "current-context",
                ): expected,
                (
                    "mise",
                    "exec",
                    "--",
                    "kubectl",
                    "--kubeconfig",
                    canonical_config,
                    *endpoint_query,
                ): f"https://{expected}",
                ("tailscale", "status", "--json"): live_status,
                ("kubectl", "config", "current-context"): expected,
                ("kubectl", "--context", expected, *endpoint_query): f"https://{expected}",
            }
        )
        self.assertEqual(
            preflight_command("kubectl apply -f app.yaml", REPO, environ={}, runner=canonical_runner),
            [],
        )

        wrong_endpoint = Runner(
            {
                ("tailscale", "status", "--json"): live_status,
                ("kubectl", "config", "current-context"): expected,
                ("kubectl", "--context", expected, *endpoint_query): "https://203.0.113.99",
            }
        )
        violations = preflight_command(
            "kubectl apply -f app.yaml",
            REPO,
            environ={},
            runner=wrong_endpoint,
        )
        self.assertEqual(len(violations), 1)
        self.assertIn("endpoint", violations[0].message)


if __name__ == "__main__":
    unittest.main()
