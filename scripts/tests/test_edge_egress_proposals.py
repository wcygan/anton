"""Connectivity cases for draft policies; no claim of live Cilium enforcement."""

import ipaddress
import json
from pathlib import Path
import subprocess
import unittest


REPO = Path(__file__).resolve().parents[2]
PROPOSALS = REPO / ".codex-security/proposals"


def labels_match(selector, labels):
    if set(selector) != {"matchLabels"} or not selector["matchLabels"]:
        raise AssertionError("review any new or broad selector semantics")
    return all(labels.get(k) == v for k, v in selector["matchLabels"].items())


def allows(policy, namespace, labels, port, protocol="TCP", address=None):
    for rule in policy["spec"]["egress"]:
        if not any(p["port"] == port and p.get("protocol", "TCP") == protocol
                   for p in rule["ports"]):
            continue
        for peer in rule["to"]:
            if "ipBlock" in peer:
                if set(peer) != {"ipBlock"} or set(peer["ipBlock"]) != {"cidr"}:
                    raise AssertionError("review changed IP block semantics")
                if address and ipaddress.ip_address(address) in ipaddress.ip_network(peer["ipBlock"]["cidr"]):
                    return True
                continue
            if "podSelector" not in peer or set(peer) - {"podSelector", "namespaceSelector"}:
                raise AssertionError("pod identity is required")
            correct_ns = (labels_match(peer["namespaceSelector"], {"kubernetes.io/metadata.name": namespace})
                          if "namespaceSelector" in peer else namespace == policy["metadata"]["namespace"])
            if correct_ns and labels_match(peer["podSelector"], labels):
                return True
    return False


class EdgeEgressProposalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policies = {}
        for name in ("cloudflare-tunnel", "envoy-external"):
            cls.policies[name] = json.loads(subprocess.check_output(
                ["yq", "-o=json", str(PROPOSALS / f"{name}-egress.yaml")], text=True))

    def test_proposals_are_egress_only_and_not_wired_into_flux(self):
        for name, policy in self.policies.items():
            self.assertEqual(policy["spec"]["policyTypes"], ["Egress"])
            self.assertEqual(policy["metadata"]["namespace"], "network")
            self.assertFalse(labels_match(policy["spec"]["podSelector"], {}))
            app = "cloudflare-tunnel" if name == "cloudflare-tunnel" else "envoy-gateway"
            rendered = subprocess.check_output(
                ["kubectl", "kustomize", str(REPO / "kubernetes/apps/network" / app / "app")], text=True)
            self.assertNotIn(policy["metadata"]["name"], rendered)

    def test_both_allow_only_coredns_for_dns(self):
        for policy in self.policies.values():
            for protocol in ("TCP", "UDP"):
                self.assertTrue(allows(policy, "kube-system", {"k8s-app": "kube-dns"}, 53, protocol))
                self.assertFalse(allows(policy, "default", {"k8s-app": "kube-dns"}, 53, protocol))
                self.assertFalse(allows(policy, "kube-system", {"app": "headlamp"}, 53, protocol))

    def test_cloudflared_allows_external_envoy_listener_only(self):
        policy = self.policies["cloudflare-tunnel"]
        labels = {"app.kubernetes.io/component": "proxy", "app.kubernetes.io/name": "envoy",
                  "gateway.envoyproxy.io/owning-gateway-name": "envoy-external",
                  "gateway.envoyproxy.io/owning-gateway-namespace": "network"}
        self.assertTrue(allows(policy, "network", labels, 10443))
        self.assertFalse(allows(policy, "network", labels, 443))
        self.assertFalse(allows(policy, "default", labels, 10443))
        self.assertFalse(allows(policy, "network", {**labels, "gateway.envoyproxy.io/owning-gateway-name": "envoy-internal"}, 10443))

    def test_cloudflare_endpoints_do_not_allow_arbitrary_internet_or_private_ips(self):
        policy = self.policies["cloudflare-tunnel"]
        blocks = [peer["ipBlock"]["cidr"] for rule in policy["spec"]["egress"]
                  for peer in rule["to"] if "ipBlock" in peer]
        self.assertEqual(len(set(blocks)), 20)
        for block in blocks:
            network = ipaddress.ip_network(block)
            self.assertEqual(network.prefixlen, 32)
            self.assertTrue(network.network_address.is_global)
            address = str(network.network_address)
            self.assertTrue(allows(policy, "", {}, 7844, address=address))
            self.assertFalse(allows(policy, "", {}, 7844, "UDP", address))
            self.assertFalse(allows(policy, "", {}, 443, address=address))
        for address in ("203.0.113.7", "10.0.0.1", "192.168.1.1", "169.254.169.254"):
            self.assertFalse(allows(policy, "", {}, 7844, address=address))

    def test_envoy_retains_each_public_backend_on_its_pod_port(self):
        policy = self.policies["envoy-external"]
        cases = [
            ("bakery-site", {"app.kubernetes.io/controller": "server", "app.kubernetes.io/instance": "bakery-server", "app.kubernetes.io/name": "bakery-server"}, 8000),
            ("food-site", {"app.kubernetes.io/controller": "server", "app.kubernetes.io/instance": "food-site-server", "app.kubernetes.io/name": "food-site-server"}, 8000),
            ("default", {"app.kubernetes.io/name": "homepage"}, 3000),
            ("cs2plant", {"app.kubernetes.io/name": "cs2plant", "app.kubernetes.io/component": "web"}, 3000),
            ("default", {"app.kubernetes.io/controller": "echo", "app.kubernetes.io/instance": "echo", "app.kubernetes.io/name": "echo"}, 80),
            ("flux-system", {"app": "notification-controller", "app.kubernetes.io/component": "notification-controller", "app.kubernetes.io/part-of": "flux"}, 9292),
        ]
        for ns, labels, port in cases:
            with self.subTest(namespace=ns, port=port):
                self.assertTrue(allows(policy, ns, labels, port))
                self.assertFalse(allows(policy, "unrelated", labels, port))
                self.assertFalse(allows(policy, ns, labels, port, "UDP"))
                self.assertFalse(allows(policy, ns, labels, 6443))

    def test_envoy_control_plane_exception_is_only_xds(self):
        policy = self.policies["envoy-external"]
        labels = {"app.kubernetes.io/instance": "envoy-gateway",
                  "app.kubernetes.io/name": "gateway-helm", "control-plane": "envoy-gateway"}
        self.assertTrue(allows(policy, "network", labels, 18000))
        self.assertFalse(allows(policy, "default", labels, 18000))
        self.assertFalse(allows(policy, "network", labels, 9443))

    def test_private_admin_and_unrelated_destinations_are_blocked(self):
        for policy in self.policies.values():
            for ns, labels, port in (
                ("kube-system", {"app.kubernetes.io/name": "headlamp", "app.kubernetes.io/instance": "headlamp"}, 4466),
                ("default", {}, 6443),
                ("databases", {"app": "postgres"}, 5432),
                ("observability", {"app": "grafana"}, 3000),
                ("network", {"gateway.envoyproxy.io/owning-gateway-name": "envoy-internal"}, 10443),
            ):
                with self.subTest(policy=policy["metadata"]["name"], namespace=ns):
                    self.assertFalse(allows(policy, ns, labels, port))
