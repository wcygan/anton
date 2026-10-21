"""Source-level contract for the staged Harbor PostgreSQL ingress policy."""

import json
from pathlib import Path
import subprocess
import unittest


REPO = Path(__file__).resolve().parents[2]
APP = REPO / "kubernetes/apps/registries/harbor-config/app"
CANDIDATE = APP / "staged/networkpolicy-harbor-postgres.yaml"
POLICY_NAME = "harbor-postgres-ingress-candidate"


def labels_match(selector, labels):
    if set(selector) != {"matchLabels"}:
        raise AssertionError("review unsupported selector semantics before extending the fixture")
    return all(labels.get(key) == value for key, value in selector["matchLabels"].items())


def allows(policy, namespace, labels, port, protocol="TCP"):
    for rule in policy["spec"].get("ingress", []):
        if not any(item.get("port") == port and item.get("protocol", "TCP") == protocol
                   for item in rule.get("ports", [])):
            continue
        for peer in rule.get("from", []):
            if set(peer) == {"podSelector"}:
                if namespace == "registries" and labels_match(peer["podSelector"], labels):
                    return True
            elif set(peer) == {"namespaceSelector", "podSelector"}:
                if (labels_match(peer["namespaceSelector"], {"kubernetes.io/metadata.name": namespace})
                        and labels_match(peer["podSelector"], labels)):
                    return True
            else:
                raise AssertionError("peer must bind namespace and pod identity")
    return False


def documents_from_yaml(path):
    encoded = subprocess.check_output(["yq", "eval-all", "-o=json", "[.]", str(path)], text=True)
    return json.loads(encoded)


class HarborPostgresNetworkPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.candidate = documents_from_yaml(CANDIDATE)[0]
        rendered = subprocess.check_output(["kubectl", "kustomize", str(APP)], text=True)
        cls.active = json.loads(subprocess.check_output(
            ["yq", "eval-all", "-o=json", "[.]", "-"], input=rendered, text=True))
        cls.policy = cls.candidate

    def test_candidate_remains_outside_active_flux_tree(self):
        active_policies = [doc for doc in self.active if doc.get("kind") == "NetworkPolicy"]
        self.assertNotIn(POLICY_NAME, [doc.get("metadata", {}).get("name") for doc in active_policies])
        self.assertIn("harbor-postgres", [doc.get("metadata", {}).get("name") for doc in self.active
                                          if doc.get("kind") == "Cluster"])
        self.assertEqual(self.policy["spec"]["policyTypes"], ["Ingress"])
        self.assertNotIn("egress", self.policy["spec"])

    def test_selects_only_harbor_postgres_instances(self):
        selector = self.policy["spec"]["podSelector"]
        postgres = {"cnpg.io/cluster": "harbor-postgres", "cnpg.io/podRole": "instance"}
        self.assertTrue(labels_match(selector, postgres))
        self.assertFalse(labels_match(selector, {**postgres, "cnpg.io/cluster": "other"}))
        self.assertFalse(labels_match(selector, {"cnpg.io/cluster": "harbor-postgres"}))

    def test_required_client_matrix_is_exact(self):
        harbor = {"app.kubernetes.io/instance": "harbor"}
        operator = {"app.kubernetes.io/instance": "cloudnative-pg",
                    "app.kubernetes.io/name": "cloudnative-pg"}
        prometheus = {"app.kubernetes.io/instance": "kube-prometheus-stack-prometheus",
                      "app.kubernetes.io/name": "prometheus"}
        postgres = {"cnpg.io/cluster": "harbor-postgres", "cnpg.io/podRole": "instance"}
        self.assertTrue(allows(self.policy, "registries", harbor, 5432))
        self.assertTrue(allows(self.policy, "registries", postgres, 5432))
        self.assertTrue(allows(self.policy, "databases", operator, 8000))
        self.assertTrue(allows(self.policy, "observability", prometheus, 9187))

    def test_wrong_namespace_identity_port_and_protocol_are_rejected(self):
        harbor = {"app.kubernetes.io/instance": "harbor"}
        operator = {"app.kubernetes.io/instance": "cloudnative-pg",
                    "app.kubernetes.io/name": "cloudnative-pg"}
        prometheus = {"app.kubernetes.io/instance": "kube-prometheus-stack-prometheus",
                      "app.kubernetes.io/name": "prometheus"}
        self.assertFalse(allows(self.policy, "default", harbor, 5432))
        self.assertFalse(allows(self.policy, "databases", harbor, 5432))
        self.assertFalse(allows(self.policy, "registries", harbor, 8000))
        self.assertFalse(allows(self.policy, "databases", operator, 5432))
        self.assertFalse(allows(self.policy, "default", prometheus, 9187))
        self.assertFalse(allows(self.policy, "observability", prometheus, 5432))
        self.assertFalse(allows(self.policy, "registries", harbor, 5432, "UDP"))
        self.assertFalse(allows(self.policy, "registries", {}, 5432))


if __name__ == "__main__":
    unittest.main()
