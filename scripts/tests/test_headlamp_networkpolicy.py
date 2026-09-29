"""Source-level allowed/blocked traffic cases; not live Cilium enforcement."""

import json
from pathlib import Path
import subprocess
import unittest


REPO = Path(__file__).resolve().parents[2]
APP = REPO / "kubernetes/apps/kube-system/headlamp/app"


def matches(selector, labels):
    # Fail the fixture if a selector changes to a form this check cannot model.
    if set(selector) != {"matchLabels"}:
        raise AssertionError("review new selector semantics before extending the fixture")
    return all(labels.get(key) == value for key, value in selector["matchLabels"].items())


class HeadlampNetworkPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        documents = json.loads(subprocess.check_output(
            ["yq", "eval-all", "-o=json", "[.]", str(APP / "networkpolicy.yaml")], text=True
        ))
        cls.policy = documents[0]
        cls.proxy = {
            "tailscale.com/managed": "true",
            "tailscale.com/parent-resource": "headlamp",
            "tailscale.com/parent-resource-ns": "kube-system",
            "tailscale.com/parent-resource-type": "ingress",
        }

    def allows(self, namespace, labels, port="http", protocol="TCP"):
        for rule in self.policy["spec"]["ingress"]:
            if not any(item.get("port") == port and item.get("protocol", "TCP") == protocol
                       for item in rule.get("ports", [])):
                continue
            for peer in rule.get("from", []):
                # A peer missing either selector would broaden access.
                if set(peer) != {"namespaceSelector", "podSelector"}:
                    raise AssertionError("ingress peer must bind namespace AND pod identity")
                if matches(peer["namespaceSelector"], {"kubernetes.io/metadata.name": namespace}) and matches(peer["podSelector"], labels):
                    return True
        return False

    def test_policy_is_wired_into_flux_app(self):
        rendered = subprocess.check_output(["kubectl", "kustomize", str(APP)], text=True)
        documents = json.loads(subprocess.check_output(
            ["yq", "eval-all", "-o=json", "[.]", "-"], input=rendered, text=True
        ))
        self.assertIn(self.policy, documents)
        self.assertEqual(self.policy["spec"]["policyTypes"], ["Ingress"])
        selector = self.policy["spec"]["podSelector"]
        self.assertTrue(matches(selector, {"app.kubernetes.io/name": "headlamp", "app.kubernetes.io/instance": "headlamp"}))
        self.assertFalse(matches(selector, {"app.kubernetes.io/name": "coredns"}))

    def test_dedicated_proxy_is_allowed_only_on_http_tcp(self):
        self.assertTrue(self.allows("tailscale", self.proxy))
        self.assertFalse(self.allows("tailscale", self.proxy, protocol="UDP"))
        self.assertFalse(self.allows("tailscale", self.proxy, port="metrics"))

    def test_edge_and_unrelated_pods_are_blocked(self):
        for labels in (
            {"app.kubernetes.io/name": "cloudflare-tunnel"},
            {"gateway.envoyproxy.io/owning-gateway-name": "envoy-external"},
            {},
            self.proxy,  # Matching labels in the wrong namespace still fail.
        ):
            with self.subTest(labels=labels):
                self.assertFalse(self.allows("network", labels))

    def test_other_tailscale_parents_and_incomplete_identity_are_blocked(self):
        for key, value in (
            ("tailscale.com/managed", "false"),
            ("tailscale.com/parent-resource", "grafana"),
            ("tailscale.com/parent-resource-ns", "default"),
            ("tailscale.com/parent-resource-type", "svc"),
        ):
            labels = {**self.proxy, key: value}
            with self.subTest(key=key):
                self.assertFalse(self.allows("tailscale", labels))
                labels.pop(key)
                self.assertFalse(self.allows("tailscale", labels))
