"""Tests for the executable Kubernetes logging contract."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "lib"))

from kubernetes_log_contract import (  # noqa: E402
    load_fixtures,
    normalize_severity,
    validate_loki,
    validate_otel,
    validate_query_catalog,
    validate_repository,
    validate_runbook,
)


class KubernetesLogContractTests(unittest.TestCase):
    def test_golden_normalization_records(self) -> None:
        fixtures = load_fixtures(REPO / "scripts" / "tests" / "fixtures" / "kubernetes-log-records.json")
        for fixture in fixtures:
            with self.subTest(fixture["name"]):
                self.assertEqual(
                    normalize_severity(fixture.get("severity_text"), str(fixture.get("body", ""))),
                    fixture["expected"],
                )

    def test_rejects_stale_debug_retention(self) -> None:
        source = REPO / "kubernetes" / "apps" / "observability" / "loki" / "app" / "helmrelease.yaml"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "loki.yaml"
            path.write_text(source.read_text().replace('period: 6h', 'period: 24h', 1), encoding="utf-8")
            self.assertTrue(validate_loki(path))

    def test_rejects_changed_otel_normalization_condition(self) -> None:
        source = REPO / "kubernetes" / "apps" / "observability" / "otel-collector" / "app" / "helmrelease.yaml"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "otel.yaml"
            path.write_text(
                source.read_text().replace(
                    'set(log.severity_text, "error") where log.severity_text == nil and log.body != nil',
                    'set(log.severity_text, "error") where log.severity_text != nil and log.body != nil',
                    1,
                ),
                encoding="utf-8",
            )
            self.assertTrue(validate_otel(path))

    def test_rejects_unknown_otel_normalization_statement(self) -> None:
        source = REPO / "kubernetes" / "apps" / "observability" / "otel-collector" / "app" / "helmrelease.yaml"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "otel.yaml"
            path.write_text(
                source.read_text().replace(
                    '                - delete_key(resource.attributes, "severity")',
                    '                - delete_key(resource.attributes, "severity")\n'
                    '                - keep_keys(log.attributes, [])',
                    1,
                ),
                encoding="utf-8",
            )
            self.assertTrue(validate_otel(path))

    def test_rejects_duplicate_otel_normalization_processor(self) -> None:
        source = REPO / "kubernetes" / "apps" / "observability" / "otel-collector" / "app" / "helmrelease.yaml"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "otel.yaml"
            path.write_text(
                source.read_text()
                + "\n        transform/severity:\n"
                + "          log_statements:\n"
                + "            - context: log\n"
                + "              statements:\n"
                + "                - keep_keys(log.attributes, [])\n",
                encoding="utf-8",
            )
            self.assertTrue(validate_otel(path))

    def test_rejects_non_indexed_query_selector(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "queries.md"
            path.write_text('{k8s_pod_name="loki-0"}\n', encoding="utf-8")
            self.assertTrue(validate_query_catalog(path))

    def test_rejects_loki_before_storage_rollout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runbook.md"
            path.write_text(
                "scripts/validate-log-contract.py --show\n"
                "mise exec -- task contracts:validate\n"
                "seaweedfs-buckets-ensure\n"
                "## Rollout and ClickStack teardown\n"
                "Reconcile the Loki app, then seaweedfs-config.\n",
                encoding="utf-8",
            )
            self.assertTrue(validate_runbook(path))

    def test_current_repository(self) -> None:
        self.assertEqual(validate_repository(REPO), [])


if __name__ == "__main__":
    unittest.main()
