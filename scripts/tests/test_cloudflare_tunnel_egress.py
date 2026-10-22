"""Evaluate allowed/blocked destinations in source, not live Cilium behavior."""

import json
from pathlib import Path
import subprocess
import unittest

from scripts.tests.test_edge_egress_proposals import allows, labels_match


REPO = Path(__file__).resolve().parents[2]
APP = REPO / "kubernetes/apps/network/cloudflare-tunnel/app"


class CloudflareTunnelEgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = json.loads(subprocess.check_output(
            ["yq", "-o=json", str(APP / "networkpolicy.yaml")], text=True))
        # Flux supplies the namespace through spec.targetNamespace.
        cls.policy["metadata"]["namespace"] = "network"
        cls.envoy = {
            "app.kubernetes.io/component": "proxy",
            "app.kubernetes.io/name": "envoy",
            "gateway.envoyproxy.io/owning-gateway-name": "envoy-external",
            "gateway.envoyproxy.io/owning-gateway-namespace": "network",
        }

    def test_render_selects_cloudflared_and_changes_only_egress(self):
        rendered = subprocess.check_output(["kubectl", "kustomize", str(APP)], text=True)
        documents = json.loads(subprocess.check_output(
            ["yq", "eval-all", "-o=json", "[.]", "-"], input=rendered, text=True))
        policies = [doc for doc in documents if doc.get("kind") == "NetworkPolicy"]
        self.assertEqual([self.policy["spec"]], [doc["spec"] for doc in policies])
        self.assertEqual(self.policy["spec"]["policyTypes"], ["Egress"])
        self.assertNotIn("ingress", self.policy["spec"])
        selector = self.policy["spec"]["podSelector"]
        cloudflared = {"app.kubernetes.io/controller": "cloudflare-tunnel",
                      "app.kubernetes.io/instance": "cloudflare-tunnel",
                      "app.kubernetes.io/name": "cloudflare-tunnel"}
        self.assertTrue(labels_match(selector, cloudflared))
        self.assertFalse(labels_match(selector, self.envoy))
        self.assertFalse(labels_match(selector, {}))

    def test_dns_requires_coredns_identity_and_port(self):
        for protocol in ("TCP", "UDP"):
            self.assertTrue(allows(self.policy, "kube-system", {"k8s-app": "kube-dns"}, 53, protocol))
            self.assertFalse(allows(self.policy, "default", {"k8s-app": "kube-dns"}, 53, protocol))
            self.assertFalse(allows(self.policy, "kube-system", {}, 53, protocol))
        self.assertFalse(allows(self.policy, "kube-system", {"k8s-app": "kube-dns"}, 443))

    def test_origin_is_external_envoy_on_its_pod_port(self):
        self.assertTrue(allows(self.policy, "network", self.envoy, 10443))
        for port, protocol in ((443, "TCP"), (10080, "TCP"), (10443, "UDP"), (19001, "TCP")):
            self.assertFalse(allows(self.policy, "network", self.envoy, port, protocol))
        self.assertFalse(allows(self.policy, "default", self.envoy, 10443))
        internal = {**self.envoy, "gateway.envoyproxy.io/owning-gateway-name": "envoy-internal"}
        self.assertFalse(allows(self.policy, "network", internal, 10443))

    def test_public_ipv4_preserves_tunnel_and_optional_https(self):
        for address in ("198.41.192.167", "198.41.200.23", "1.1.1.1"):
            for port in (7844, 443):
                self.assertTrue(allows(self.policy, "", {}, port, address=address))
                self.assertFalse(allows(self.policy, "", {}, port, "UDP", address))
            for port in (22, 53, 80, 6443, 8333):
                self.assertFalse(allows(self.policy, "", {}, port, address=address))

    def test_private_and_special_addresses_cannot_use_internet_exception(self):
        addresses = ("0.0.0.1", "10.42.1.1", "10.43.0.1", "100.64.0.1",
                     "127.0.0.1", "169.254.169.254", "172.16.0.1", "172.31.255.254",
                     "192.0.0.1", "192.0.2.1", "192.168.1.106", "198.18.0.1",
                     "198.51.100.1", "203.0.113.1", "224.0.0.1", "255.255.255.255",
                     "::1", "fd00::1", "2606:4700::1111")
        for address in addresses:
            for port in (443, 7844, 6443, 8333):
                with self.subTest(address=address, port=port):
                    self.assertFalse(allows(self.policy, "", {}, port, address=address))

    def test_unrelated_private_services_have_no_pod_exception(self):
        for namespace, labels, port in (
            ("storage", {"app": "seaweedfs"}, 8333),
            ("databases", {"app": "postgres"}, 5432),
            ("observability", {"app": "grafana"}, 3000),
            ("default", {}, 443),
            ("network", {}, 7844),
        ):
            self.assertFalse(allows(self.policy, namespace, labels, port))

    def test_envoy_monitor_renders_and_selects_the_allowed_origin(self):
        monitoring_app = REPO / "kubernetes/apps/observability/kube-prometheus-stack/app"
        rendered = subprocess.check_output(["kubectl", "kustomize", str(monitoring_app)], text=True)
        documents = json.loads(subprocess.check_output(
            ["yq", "eval-all", "-o=json", "[.]", "-"], input=rendered, text=True))
        monitors = [doc for doc in documents if doc.get("kind") == "PodMonitor"
                    and doc["metadata"]["name"] == "envoy-external"]
        self.assertEqual(len(monitors), 1)
        monitor = monitors[0]["spec"]
        self.assertEqual(monitor["namespaceSelector"]["matchNames"], ["network"])
        self.assertTrue(labels_match(monitor["selector"], self.envoy))
        internal = {**self.envoy, "gateway.envoyproxy.io/owning-gateway-name": "envoy-internal"}
        self.assertFalse(labels_match(monitor["selector"], internal))
        self.assertEqual(monitor["podMetricsEndpoints"],
                         [{"port": "metrics", "path": "/stats/prometheus", "interval": "30s"}])
