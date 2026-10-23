"""Source contract: Prometheus scrapes every etcd member, and etcd rules use real metrics.

Talos runs etcd as a host service, so kube-prometheus-stack scrapes the node
addresses listed in its HelmRelease. Nothing else ties that list to the nodes,
the port to the Talos metrics listener, or the alert expressions to the metric
names etcd serves. Until 2026-10-23 etcd was not scraped at all, so a rule
reading etcd_server_proposals_failed_total could never fire.
"""

import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit
import unittest


REPO = Path(__file__).resolve().parents[2]
KPS = REPO / "kubernetes/apps/observability/kube-prometheus-stack/app"
TALCONFIG = REPO / "talos/talconfig.yaml"
CONTROLLER_PATCH = REPO / "talos/patches/controller/cluster.yaml"
FAMILIES = REPO / "scripts/tests/fixtures/etcd-metric-families.txt"
# Families etcd serves itself; the API server's etcd client metrics use other prefixes.
SERVER_METRIC = re.compile(r"\b((?:etcd_(?:server|mvcc|disk|network|debugging|cluster)_|grpc_server_)[a-zA-Z0-9_]*)\s*[{\[]")
HISTOGRAM_SERIES = re.compile(r"_(?:bucket|sum|count)$")


def yaml_documents(path, query="."):
    output = subprocess.check_output(["yq", "-o=json", "-I=0", query, str(path)], text=True)
    return [json.loads(line) for line in output.splitlines() if line.strip() not in ("", "null")]


def kps_values():
    return yaml_documents(KPS / "helmrelease.yaml")[0]["spec"]["values"]


def rule_expressions():
    for path in sorted((REPO / "kubernetes").rglob("*.yaml")):
        if "kind: PrometheusRule" not in path.read_text():
            continue
        for document in yaml_documents(path, 'select(.kind == "PrometheusRule")'):
            for group in document["spec"]["groups"]:
                for rule in group["rules"]:
                    yield path.relative_to(REPO), rule.get("alert") or rule.get("record"), rule["expr"]


class EtcdMonitoringTests(unittest.TestCase):
    def setUp(self):
        self.etcd = kps_values()["kubeEtcd"]

    def test_scrape_targets_are_the_control_plane_nodes(self):
        talconfig = yaml_documents(TALCONFIG)[0]
        control_plane = sorted(node["ipAddress"] for node in talconfig["nodes"] if node.get("controlPlane"))
        self.assertTrue(self.etcd["enabled"])
        self.assertEqual(sorted(self.etcd["endpoints"]), control_plane)

    def test_scrape_port_is_the_talos_metrics_listener(self):
        cluster = yaml_documents(CONTROLLER_PATCH, 'select(has("cluster"))')[0]["cluster"]
        listeners = [urlsplit(url) for url in cluster["etcd"]["extraArgs"]["listen-metrics-urls"].split(",")]
        self.assertTrue(listeners)
        for listener in listeners:
            self.assertEqual(listener.scheme, "http")
            self.assertEqual(listener.port, self.etcd["service"]["targetPort"])

    def test_no_credentials_are_sent_to_the_plain_http_listener(self):
        monitor = self.etcd["serviceMonitor"]
        # The chart's default authorization sends Prometheus's service-account token.
        self.assertIn("authorization", monitor)
        self.assertIsNone(monitor["authorization"])
        self.assertNotEqual(monitor.get("scheme", "http"), "https")

    def test_curated_rules_replace_the_chart_etcd_rules(self):
        self.assertIs(kps_values()["defaultRules"]["rules"]["etcd"], False)
        resources = yaml_documents(KPS / "kustomization.yaml")[0]["resources"]
        self.assertIn("./prometheusrule-etcd.yaml", resources)

    def test_etcd_rules_select_the_kube_etcd_job(self):
        rules = KPS.relative_to(REPO) / "prometheusrule-etcd.yaml"
        selectors = [(name, match.group(0)) for path, name, expr in rule_expressions() if path == rules
                     for match in re.finditer(r"\b(?:etcd_|up\b)[a-zA-Z0-9_]*\{[^}]*\}", expr)]
        self.assertTrue(selectors)
        for name, selector in selectors:
            with self.subTest(alert=name, selector=selector):
                self.assertIn('job="kube-etcd"', selector)

    def test_rules_use_only_metrics_etcd_serves(self):
        families = dict(line.split() for line in FAMILIES.read_text().splitlines() if line and not line.startswith("#"))
        used = [(path, name, metric) for path, name, expr in rule_expressions() for metric in SERVER_METRIC.findall(expr)]
        self.assertTrue(used)
        for path, name, metric in used:
            with self.subTest(file=str(path), rule=name, metric=metric):
                base = HISTOGRAM_SERIES.sub("", metric)
                if metric != base and families.get(base) == "histogram":
                    continue
                self.assertIn(metric, families)


if __name__ == "__main__":
    unittest.main()
