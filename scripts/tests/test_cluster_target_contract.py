"""Tests for target resolution and mutation preflight."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "lib"))

from cluster_target_contract import (  # noqa: E402
    classify_command,
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

    def test_redacted_evidence_hides_addresses(self) -> None:
        result = resolve_talos_targets(REPO, source="fallback", environ={})
        evidence = result.evidence()
        self.assertTrue(all(node["address"] == "<redacted>" for node in evidence["nodes"]))

    def test_address_list_preserves_resolved_node_order(self) -> None:
        result = resolve_talos_targets(REPO, source="fallback", environ={})
        self.assertEqual(result.addresses().split(","), [node.address for node in result.nodes])

    def test_classifies_wrapped_commands(self) -> None:
        reads = classify_command("mise exec -- kubectl get pods -A")
        mutation = classify_command("mise exec -- kubectl -n observability port-forward svc/loki 3100:3100")
        piped_mutation = classify_command("printf manifest | kubectl apply -f -")
        local = classify_command("talosctl config context anton")
        self.assertEqual(reads[0].classification, "read")
        self.assertEqual(mutation[0].classification, "cluster-mutation")
        self.assertEqual(piped_mutation[0].classification, "cluster-mutation")
        self.assertEqual(local[0].classification, "local-mutation")

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
        runner = Runner(
            {
                ("tailscale", "status", "--json"): live_status,
                ("kubectl", "config", "current-context"): expected,
            }
        )
        self.assertEqual(preflight_command("kubectl exec pod -- true", REPO, environ={}, runner=runner), [])


if __name__ == "__main__":
    unittest.main()
