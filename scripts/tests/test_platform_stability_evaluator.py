"""Behavior tests for the platform stability Prometheus proxy evaluator."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit


REPO = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO / "scripts" / "lib" / "platform_stability.py"
FIXTURE = REPO / "scripts" / "tests" / "fixtures" / "platform-stability-prometheus.json"
LIVE_EVIDENCE = (
    REPO
    / "context"
    / "notes"
    / "cluster-metric-evidence"
    / "2026-08-11T005110Z-m4.json"
)
LIVE_ATTRIBUTION_EVIDENCE = (
    REPO
    / "context"
    / "notes"
    / "cluster-metric-evidence"
    / "2026-08-11T013927Z-m4-restart-attribution.json"
)
LIVE_OOM_EVIDENCE = (
    REPO
    / "context"
    / "notes"
    / "cluster-metric-evidence"
    / "2026-08-11T142625Z-m4-oom-restart-estimator.json"
)

SPEC = importlib.util.spec_from_file_location("evaluate_platform_stability", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class FakeRunner:
    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.argvs: list[tuple[str, ...]] = []

    def __call__(self, argv: tuple[str, ...], timeout_seconds: float) -> subprocess.CompletedProcess[str]:
        self.argvs.append(tuple(argv))
        self._assert_safe_argv(argv)
        if timeout_seconds > MODULE.QUERY_TIMEOUT_SECONDS:
            raise AssertionError("query timeout exceeds the per-query cap")
        path = argv[10]
        query = MODULE.parse_query_path(path)
        if query is None:
            return subprocess.CompletedProcess(argv, 0, json.dumps(self.responses["buildinfo"]), "")
        key = next(key for key, spec in MODULE.QUERY_CATALOG.items() if spec.promql == query)
        response = self.responses["queries"].get(key)
        if response is None:
            response = {"data": {"result": [], "resultType": "vector"}, "status": "success"}
        return subprocess.CompletedProcess(argv, 0, json.dumps(response), "")

    def _assert_safe_argv(self, argv: tuple[str, ...]) -> None:
        self.assertEqual(
            argv[:8],
            (
                "mise",
                "exec",
                "--",
                "kubectl",
                "--kubeconfig",
                "/fixture/kubeconfig",
                "--context",
                "fixture-context",
            ),
        )
        self.assertEqual(argv[8:10], ("get", "--raw"))
        self.assertEqual(len(argv), 11)
        path = argv[10]
        self.assertTrue(path.startswith(MODULE.PROXY_PREFIX + "/api/v1/"))
        resource_path = urlsplit(path).path.lower()
        self.assertNotIn("/secrets", resource_path)
        self.assertNotIn("/pods", resource_path)
        self.assertNotIn("port-forward", resource_path)
        self.assertEqual(urlsplit(path).scheme, "")

    def assertEqual(self, actual: object, expected: object) -> None:
        if actual != expected:
            raise AssertionError(f"{actual!r} != {expected!r}")

    def assertTrue(self, value: bool) -> None:
        if not value:
            raise AssertionError("expected true")

    def assertNotIn(self, member: str, container: str) -> None:
        if member in container:
            raise AssertionError(f"{member!r} unexpectedly found in {container!r}")


class PlatformStabilityEvaluatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.responses = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.observed_at = datetime.fromisoformat("2026-08-10T23:44:45+00:00")

    def evaluate(self, responses: dict[str, object] | None = None) -> tuple[dict[str, object], FakeRunner]:
        runner = FakeRunner(responses if responses is not None else self.responses)
        prefix = (
            "mise",
            "exec",
            "--",
            "kubectl",
            "--kubeconfig",
            "/fixture/kubeconfig",
            "--context",
            "fixture-context",
        )
        return MODULE.evaluate(self.observed_at, runner, prefix_provider=lambda: prefix), runner

    def oom_measure(
        self,
        raw: dict[str, object],
        detail: dict[str, object],
        *,
        running_hours: float = 51036.0,
        running_state: str = "observed",
        continuity_state: str = "complete",
        continuity_query_state: str = "observed",
        coverage_reasons: set[str] | None = None,
    ) -> tuple[dict[str, object], set[str]]:
        reasons = coverage_reasons if coverage_reasons is not None else set()
        running_evidence: dict[str, object] = {"state": running_state}
        if running_state == "observed":
            running_evidence["samples"] = [{"labels": {}, "value": running_hours}]
        continuity = {
            "query": {"state": continuity_query_state},
            "state": continuity_state,
        }
        measure = MODULE._oom_attribution_measure(
            raw,
            detail,
            running_hours_evidence=running_evidence,
            scrape_continuity=continuity,
            coverage_reasons=reasons,
        )
        return measure, reasons

    @staticmethod
    def oom_detail_sample(
        reason: str,
        exact_value: str,
        *,
        node: str = "k8s-2",
        namespace: str = "observability",
        container: str = "platform-component",
    ) -> dict[str, object]:
        return {
            "exact_value": exact_value,
            "labels": {
                "container": container,
                "namespace": namespace,
                "node": node,
                "reason": reason,
            },
            "value": float(exact_value),
        }

    def test_report_is_stable_and_keeps_each_measure_separate(self) -> None:
        report, runner = self.evaluate()
        repeated, _ = self.evaluate()
        self.assertEqual(
            json.dumps(report, indent=2, sort_keys=True, allow_nan=False),
            json.dumps(repeated, indent=2, sort_keys=True, allow_nan=False),
        )
        self.assertEqual(report["coverage"]["state"], "partial")
        self.assertEqual(report["coverage"]["observer_instrumentation_state"], "complete")
        self.assertEqual(report["coverage"]["observer_instrumentation_reasons"], [])
        self.assertEqual(
            report["coverage"]["outcome_gaps"],
            [
                "api_thresholds_unapproved",
                "oom_event_counter_unavailable",
                "storage_threshold_unapproved",
            ],
        )
        continuity = report["coverage"]["scrape_continuity"]
        self.assertEqual(continuity["state"], "complete")
        self.assertEqual(continuity["expected_target_counts"], MODULE.EXPECTED_SCRAPE_TARGETS)
        self.assertEqual(len(continuity["sources"]), 4)
        self.assertEqual(
            set(report["measures"]),
            {"api_error", "api_latency", "memory", "oom", "package_throttle", "restarts", "storage"},
        )
        self.assertAlmostEqual(report["measures"]["restarts"]["total"]["samples"][0]["value"], 24.10707, places=5)
        self.assertAlmostEqual(report["measures"]["restarts"]["rate_per_1000_container_hours"], 0.472743, places=6)
        attribution = report["measures"]["restarts"]["attribution"]
        self.assertEqual(report["measures"]["restarts"]["node_attribution"], "time_local_1m_estimator")
        self.assertEqual(attribution["state"], "complete")
        self.assertEqual(attribution["node_total_sum"], 17.130266)
        self.assertEqual(attribution["unattributed_restart_increments"], 0.000001)
        for measure in ("api_error", "api_latency", "storage"):
            self.assertEqual(report["measures"][measure]["threshold_state"], "unapproved")
            self.assertIsNone(report["measures"][measure]["breach_minutes"])
        self.assertEqual(report["measures"]["oom"]["state"], "observed")
        self.assertEqual(report["measures"]["oom"]["authoritative_event_count_state"], "no_data")
        self.assertEqual(
            report["measures"]["oom"]["measurement_kind"],
            "time_local_1m_restart_reason_estimator",
        )
        self.assertEqual(report["measures"]["oom"]["total"], 2.0)
        self.assertEqual(report["measures"]["oom"]["rate_per_1000_container_hours"], 0.03922)
        self.assertEqual(report["measures"]["oom"]["attribution"]["state"], "complete")
        self.assertEqual(report["measures"]["oom"]["node_attribution"], "time_local_1m_estimator")
        self.assertEqual(report["measures"]["oom"]["component_attribution"], "time_local_1m_estimator")
        self.assertEqual(
            report["measures"]["oom"]["attribution"]["by_node"],
            [{"exact_value": "2", "labels": {"node": "k8s-3"}, "value": 2.0}],
        )
        self.assertEqual(report["measures"]["memory"]["multus"]["breach_minutes"][0]["value"], 120.0)
        api_latency = report["measures"]["api_latency"]
        self.assertEqual(api_latency["state"], "observed")
        historical = api_latency["historical_max_p99_seconds"]
        self.assertEqual(historical["state"], "observed")
        self.assertEqual(historical["samples"][0]["value"], 0.9838)
        self.assertEqual(
            historical["infos"],
            ["PromQL info: input to histogram_quantile needed to be fixed for monotonicity"],
        )
        self.assertEqual(historical["warnings"], ["fixture warning"])
        self.assertEqual(
            [reason for reason in report["coverage"]["reasons"] if reason.endswith("_query_error")],
            [],
        )
        self.assertGreaterEqual(len(runner.argvs), len(MODULE.QUERY_CATALOG))

    def test_historical_api_latency_uses_hourly_sampling(self) -> None:
        self.assertEqual(
            MODULE.QUERY_CATALOG["api_p99_historical_seconds"].promql,
            '''max_over_time((max(histogram_quantile(0.99, sum by (le,verb)(rate(apiserver_request_duration_seconds_bucket{verb!="WATCH"}[5m])))))[15d:1h])''',
        )

    def test_scrape_continuity_pins_required_target_counts(self) -> None:
        self.assertEqual(
            MODULE.EXPECTED_SCRAPE_TARGETS,
            {"apiserver": 3, "kube-state-metrics": 1, "kubelet": 9, "node-exporter": 3},
        )
        query = MODULE.QUERY_CATALOG["scrape_continuity"].promql
        for job, target_count in MODULE.EXPECTED_SCRAPE_TARGETS.items():
            self.assertIn(
                f'min_over_time(up{{job="{job}"}}[1m]) == 1) == bool {target_count}',
                query,
            )
            self.assertIn("[15d:1m]", query)

    def test_restart_attribution_uses_a_time_local_uid_join(self) -> None:
        raw_query = MODULE.QUERY_CATALOG["restart_attribution_total"].promql
        node_query = MODULE.QUERY_CATALOG["restart_attribution_by_node"].promql
        self.assertIn("increase(kube_pod_container_status_restarts_total", raw_query)
        self.assertEqual(MODULE.ATTRIBUTION_SUBQUERY_RANGE, "14d23h59m")
        self.assertEqual(MODULE.ATTRIBUTION_INTERVAL_COUNT, 21600)
        self.assertIn("[14d23h59m:1m]", raw_query)
        self.assertNotIn("[15d:1m]", raw_query)
        self.assertIn("on (namespace,pod,uid) group_left(node) kube_pod_info", node_query)
        self.assertIn("[14d23h59m:1m]", node_query)
        self.assertNotIn("[15d:1m]", node_query)

    def test_oom_detail_query_uses_time_local_uid_and_node_joins(self) -> None:
        query = MODULE.QUERY_CATALOG["oom_restart_attribution_detail"].promql
        self.assertIn("increase(kube_pod_container_status_restarts_total", query)
        self.assertIn(
            "on (namespace,pod,uid,container) group_left(reason) "
            "kube_pod_container_status_last_terminated_reason",
            query,
        )
        self.assertIn("on (namespace,pod,uid) group_left(node) kube_pod_info", query)
        self.assertIn("sum by (node,namespace,container,reason)", query)
        self.assertIn(") > 0", query)
        self.assertIn("[14d23h59m:1m]", query)
        self.assertNotIn("[15d:1m]", query)

    def test_oom_attribution_accepts_complete_reason_totals(self) -> None:
        raw = {
            "state": "observed",
            "samples": [{"labels": {}, "value": 17.130267, "exact_value": "17.130267"}],
        }
        detail = {
            "state": "observed",
            "samples": [
                self.oom_detail_sample("Error", "15.130267"),
                self.oom_detail_sample(
                    "OOMKilled",
                    "2",
                    node="k8s-3",
                    namespace="external-secrets",
                    container="external-secrets",
                ),
            ],
        }
        measure, coverage_reasons = self.oom_measure(raw, detail)
        self.assertEqual(measure["state"], "complete")
        self.assertEqual(measure["total"], 2.0)
        self.assertEqual(coverage_reasons, set())

    def test_oom_attribution_rejects_malformed_or_unconserved_evidence(self) -> None:
        raw = {
            "state": "observed",
            "samples": [{"labels": {}, "value": 17.0, "exact_value": "17"}],
        }
        malformed = {
            "state": "observed",
            "samples": [
                self.oom_detail_sample("OOMKilled", "2"),
                self.oom_detail_sample("OOMKilled", "15"),
            ],
        }
        measure, coverage_reasons = self.oom_measure(raw, malformed)
        self.assertEqual(measure["state"], "incomplete")
        self.assertIsNone(measure["total"])
        self.assertIn("oom_restart_attribution_incomplete", coverage_reasons)

        unconserved = deepcopy(malformed)
        unconserved["samples"][1] = self.oom_detail_sample("Error", "14")
        measure, coverage_reasons = self.oom_measure(raw, unconserved)
        self.assertEqual(measure["state"], "incomplete")
        self.assertEqual(measure["unattributed_restart_increments"], 1.0)
        self.assertIsNone(measure["total"])

    def test_oom_attribution_calculates_guarded_rate(self) -> None:
        raw = {
            "state": "observed",
            "samples": [{"labels": {}, "value": 17.0, "exact_value": "17"}],
        }
        detail = {
            "state": "observed",
            "samples": [
                self.oom_detail_sample("Error", "15"),
                self.oom_detail_sample("OOMKilled", "2", node="k8s-3"),
            ],
        }
        measure, _ = self.oom_measure(raw, detail)
        self.assertEqual(measure["rate_per_1000_container_hours"], 0.039188)

        missing_denominator, coverage_reasons = self.oom_measure(raw, detail, running_hours=0.0)
        self.assertEqual(missing_denominator["state"], "no_data")
        self.assertIsNone(missing_denominator["rate_per_1000_container_hours"])
        self.assertIsNone(missing_denominator["total"])
        self.assertIn("oom_restart_denominator_no_data", coverage_reasons)

    def test_oom_attribution_requires_complete_scrape_continuity(self) -> None:
        raw = {
            "state": "observed",
            "samples": [{"labels": {}, "value": 17.0, "exact_value": "17"}],
        }
        detail = {
            "state": "observed",
            "samples": [
                self.oom_detail_sample("Error", "15"),
                self.oom_detail_sample("OOMKilled", "2", node="k8s-3"),
            ],
        }
        measure, coverage_reasons = self.oom_measure(
            raw,
            detail,
            continuity_state="incomplete",
        )
        self.assertEqual(measure["state"], "incomplete")
        self.assertIsNone(measure["total"])
        self.assertIsNone(measure["rate_per_1000_container_hours"])
        self.assertIn("oom_scrape_continuity_incomplete", coverage_reasons)

    def test_oom_dependency_failures_remain_visible(self) -> None:
        for query_key in ("running_container_hours", "scrape_continuity"):
            with self.subTest(query_key=query_key):
                responses = deepcopy(self.responses)
                responses["queries"][query_key] = {"errorType": "bad_data", "status": "error"}
                report, _ = self.evaluate(responses)
                self.assertEqual(report["measures"]["oom"]["state"], "query_error")
                self.assertIn("query_error", " ".join(report["coverage"]["reasons"]))

    def test_oom_attribution_accepts_a_conserved_zero(self) -> None:
        raw = {
            "state": "observed",
            "samples": [{"labels": {}, "value": 0.0, "exact_value": "0"}],
        }
        detail = {"state": "no_data"}
        measure, coverage_reasons = self.oom_measure(raw, detail)
        self.assertEqual(measure["state"], "complete")
        self.assertEqual(measure["total"], 0.0)
        self.assertEqual(measure["rate_per_1000_container_hours"], 0.0)
        self.assertEqual(measure["reason_totals"], [])
        self.assertEqual(coverage_reasons, set())

    def test_oom_without_an_oom_reason_is_observed_zero(self) -> None:
        raw = {
            "state": "observed",
            "samples": [{"labels": {}, "value": 3.0, "exact_value": "3"}],
        }
        detail = {
            "state": "observed",
            "samples": [
                self.oom_detail_sample("Error", "3"),
            ],
        }
        measure, coverage_reasons = self.oom_measure(raw, detail)
        self.assertEqual(measure["state"], "complete")
        self.assertEqual(measure["total"], 0.0)
        self.assertEqual(measure["rate_per_1000_container_hours"], 0.0)
        self.assertEqual(coverage_reasons, set())

    def test_oom_empty_reason_data_remains_no_data_when_restarts_exist(self) -> None:
        raw = {
            "state": "observed",
            "samples": [{"labels": {}, "value": 3.0, "exact_value": "3"}],
        }
        measure, coverage_reasons = self.oom_measure(raw, {"state": "no_data"})
        self.assertEqual(measure["state"], "no_data")
        self.assertIsNone(measure["total"])
        self.assertIsNone(measure["rate_per_1000_container_hours"])
        self.assertIn("oom_restart_attribution_no_data", coverage_reasons)

    def test_restart_attribution_requires_labels_and_conservation(self) -> None:
        missing_label = deepcopy(self.responses)
        missing_label["queries"]["restart_attribution_by_node"]["data"]["result"][0]["metric"] = {}
        report, _ = self.evaluate(missing_label)
        self.assertEqual(report["measures"]["restarts"]["attribution"]["state"], "incomplete")
        self.assertIn("historical_restart_node_attribution_incomplete", report["coverage"]["reasons"])

        unmatched = deepcopy(self.responses)
        unmatched["queries"]["restart_attribution_by_node"]["data"]["result"][0]["value"][1] = "7"
        report, _ = self.evaluate(unmatched)
        self.assertEqual(report["measures"]["restarts"]["attribution"]["state"], "incomplete")
        self.assertIn("historical_restart_node_attribution_incomplete", report["coverage"]["reasons"])

        rounded_boundary = deepcopy(self.responses)
        rounded_boundary["queries"]["restart_attribution_total"]["data"]["result"][0]["value"][1] = "1.00000051"
        node_results = rounded_boundary["queries"]["restart_attribution_by_node"]["data"]["result"]
        node_results[0]["value"][1] = "1.00000201"
        node_results[1]["value"][1] = "0"
        node_results[2]["value"][1] = "0"
        report, _ = self.evaluate(rounded_boundary)
        attribution = report["measures"]["restarts"]["attribution"]
        self.assertEqual(attribution["unattributed_restart_increments"], 0.000002)
        self.assertEqual(attribution["state"], "incomplete")

    def test_retained_restart_attribution_matches_the_evaluator_contract(self) -> None:
        evidence = json.loads(LIVE_ATTRIBUTION_EVIDENCE.read_text(encoding="utf-8"))
        self.assertEqual(evidence["target_preflight"], "passed")
        self.assertEqual(evidence["raw_query"], MODULE.QUERY_CATALOG["restart_attribution_total"].promql)
        self.assertEqual(evidence["by_node_query"], MODULE.QUERY_CATALOG["restart_attribution_by_node"].promql)
        self.assertEqual(evidence["interval_count"], MODULE.ATTRIBUTION_INTERVAL_COUNT)
        self.assertEqual(evidence["unattributed_restart_increments"], 0.0)
        self.assertLessEqual(evidence["unattributed_restart_increments"], evidence["tolerance"])
        self.assertEqual({sample["node"] for sample in evidence["node_totals"]}, {"k8s-1", "k8s-2", "k8s-3"})
        node_total = sum(Decimal(sample["exact_value"]) for sample in evidence["node_totals"])
        residual = abs(Decimal(evidence["raw_total_exact"]) - node_total)
        self.assertEqual(node_total, Decimal(evidence["node_total_sum_exact"]))
        self.assertEqual(residual, Decimal(evidence["unattributed_restart_increments_exact"]))
        self.assertLessEqual(residual, Decimal(str(evidence["tolerance"])))
        self.assertEqual(evidence["instrumentation_reason_count_after"], 0)
        self.assertEqual(
            evidence["outcome_gaps"],
            ["api_thresholds_unapproved", "oom_no_data", "storage_threshold_unapproved"],
        )

    def test_retained_oom_estimator_matches_the_evaluator_contract(self) -> None:
        evidence = json.loads(LIVE_OOM_EVIDENCE.read_text(encoding="utf-8"))
        self.assertEqual(evidence["target_preflight"], "passed")
        self.assertEqual(evidence["experiment_id"], "M4-E5")
        self.assertEqual(evidence["raw_query"], MODULE.QUERY_CATALOG["restart_attribution_total"].promql)
        self.assertEqual(
            evidence["detail_query"],
            MODULE.QUERY_CATALOG["oom_restart_attribution_detail"].promql,
        )
        self.assertEqual(evidence["measurement_kind"], "time_local_1m_restart_reason_estimator")
        self.assertEqual(evidence["authoritative_event_count_state"], "no_data")
        self.assertEqual(evidence["oom_restart_increments"], 2.0)
        self.assertEqual(evidence["unattributed_restart_increments"], 0.0)
        self.assertLessEqual(evidence["unattributed_restart_increments"], evidence["tolerance"])
        self.assertEqual(evidence["by_node"], [{"node": "k8s-3", "value": 2.0}])
        self.assertEqual(
            evidence["by_component"],
            [{"container": "external-secrets", "namespace": "external-secrets", "value": 2.0}],
        )
        self.assertEqual(
            evidence["outcome_gaps"],
            [
                "api_thresholds_unapproved",
                "oom_event_counter_unavailable",
                "storage_threshold_unapproved",
            ],
        )

    def test_retained_scrape_evidence_matches_the_evaluator_contract(self) -> None:
        evidence = json.loads(LIVE_EVIDENCE.read_text(encoding="utf-8"))
        self.assertEqual(evidence["target_preflight"], "passed")
        self.assertEqual(evidence["query"], MODULE.QUERY_CATALOG["scrape_continuity"].promql)
        self.assertEqual(evidence["expected_target_counts"], MODULE.EXPECTED_SCRAPE_TARGETS)
        self.assertEqual(
            {sample["job"]: sample["value"] for sample in evidence["samples"]},
            {job: 1.0 for job in MODULE.EXPECTED_SCRAPE_TARGETS},
        )
        self.assertEqual(evidence["oom_state"], "no_data")
        self.assertTrue(all(state == "unapproved" for state in evidence["threshold_states"].values()))

    def test_scrape_continuity_requires_every_expected_job(self) -> None:
        responses = deepcopy(self.responses)
        responses["queries"]["scrape_continuity"]["data"]["result"].pop()
        report, _ = self.evaluate(responses)
        continuity = report["coverage"]["scrape_continuity"]
        self.assertEqual(continuity["state"], "incomplete")
        self.assertIn("scrape_continuity_incomplete", report["coverage"]["reasons"])

    def test_scrape_continuity_rejects_a_target_gap(self) -> None:
        responses = deepcopy(self.responses)
        responses["queries"]["scrape_continuity"]["data"]["result"][0]["value"][1] = "0"
        report, _ = self.evaluate(responses)
        self.assertEqual(report["coverage"]["scrape_continuity"]["state"], "incomplete")
        self.assertIn("scrape_continuity_incomplete", report["coverage"]["reasons"])

    def test_api_error_ratio_keeps_a_sub_one_request_per_second_denominator(self) -> None:
        self.assertEqual(
            MODULE.QUERY_CATALOG["api_5xx_max_ratio"].promql,
            '''max_over_time(((sum(rate(apiserver_request_total{code=~"5.."}[5m])) / sum(rate(apiserver_request_total[5m]))) and (sum(rate(apiserver_request_total[5m])) > 0))[15d:5m])''',
        )
        error_rate_per_second = 0.01
        request_rate_per_second = 0.5
        expected_ratio = error_rate_per_second / request_rate_per_second
        self.assertLess(request_rate_per_second, 1)
        self.assertEqual(expected_ratio, 0.02)

        responses = deepcopy(self.responses)
        responses["queries"]["api_5xx_max_ratio"]["data"]["result"][0]["value"][1] = str(expected_ratio)
        report, _ = self.evaluate(responses)
        self.assertEqual(report["measures"]["api_error"]["max_ratio"]["samples"][0]["value"], expected_ratio)

        zero_traffic = deepcopy(self.responses)
        zero_traffic["queries"]["api_5xx_max_ratio"]["data"]["result"] = []
        zero_traffic_report, _ = self.evaluate(zero_traffic)
        self.assertEqual(zero_traffic_report["measures"]["api_error"]["max_ratio"]["state"], "no_data")

    def test_empty_results_are_no_data_not_zero(self) -> None:
        responses = deepcopy(self.responses)
        responses["queries"]["cilium_memory_warning"]["data"]["result"] = []
        report, _ = self.evaluate(responses)
        warning = report["measures"]["memory"]["cilium_warning"]
        self.assertEqual(warning["state"], "no_data")
        self.assertIsNone(warning["breach_minutes"])
        self.assertIn("cilium-agent_no_data", report["coverage"]["reasons"])

    def test_zero_denominator_never_produces_a_rate(self) -> None:
        responses = deepcopy(self.responses)
        responses["queries"]["running_container_hours"]["data"]["result"][0]["value"][1] = "0"
        report, _ = self.evaluate(responses)
        self.assertEqual(report["measures"]["restarts"]["state"], "no_data")
        self.assertIsNone(report["measures"]["restarts"]["rate_per_1000_container_hours"])
        self.assertEqual(report["measures"]["oom"]["state"], "no_data")
        self.assertIsNone(report["measures"]["oom"]["rate_per_1000_container_hours"])

    def test_nonfinite_values_are_invalid_and_do_not_reach_json(self) -> None:
        responses = deepcopy(self.responses)
        responses["queries"]["storage_peak_percent"]["data"]["result"][0]["value"][1] = "+Inf"
        report, _ = self.evaluate(responses)
        storage = report["measures"]["storage"]
        self.assertEqual(storage["state"], "invalid_response")
        self.assertNotIn("samples", storage["peak_percent"])
        json.dumps(report, allow_nan=False)

    def test_missing_node_attribution_is_partial(self) -> None:
        responses = deepcopy(self.responses)
        responses["queries"]["multus_memory"]["data"]["result"][0]["metric"] = {}
        report, _ = self.evaluate(responses)
        self.assertIn("kube-multus_node_attribution_missing", report["coverage"]["reasons"])
        self.assertEqual(report["coverage"]["state"], "partial")

    def test_query_errors_remain_visible(self) -> None:
        responses = deepcopy(self.responses)
        responses["queries"]["api_5xx_total"] = {"errorType": "bad_data", "status": "error"}
        report, _ = self.evaluate(responses)
        self.assertEqual(report["measures"]["api_error"]["total_5xx"]["state"], "query_error")
        self.assertIn("api_error_total_query_error", report["coverage"]["reasons"])

    def test_all_calls_use_the_fixed_service_proxy(self) -> None:
        _, runner = self.evaluate()
        self.assertEqual(len(runner.argvs), len(MODULE.QUERY_CATALOG))
        for argv in runner.argvs:
            self.assertEqual(argv[8:10], ("get", "--raw"))
            self.assertTrue(argv[10].startswith(MODULE.PROXY_PREFIX + "/api/v1/query?"))

    def test_target_preflight_failure_prevents_prometheus_queries(self) -> None:
        runner = FakeRunner(self.responses)

        def fail_preflight() -> tuple[str, ...]:
            raise RuntimeError("Anton target preflight failed")

        with self.assertRaises(RuntimeError):
            MODULE.evaluate(self.observed_at, runner, prefix_provider=fail_preflight)
        self.assertEqual(runner.argvs, [])

    def test_observation_time_requires_an_offset(self) -> None:
        with self.assertRaises(Exception):
            MODULE.parse_observed_at("2026-08-10T23:44:45")

    def test_budget_exhaustion_skips_later_subprocess_calls(self) -> None:
        self.assertEqual(MODULE.QUERY_TIMEOUT_SECONDS, 30)
        self.assertEqual(MODULE.TOTAL_QUERY_BUDGET_SECONDS, 60)

        class FakeClock:
            def __init__(self) -> None:
                self.value = 100.0

            def __call__(self) -> float:
                return self.value

        class BudgetRunner(FakeRunner):
            def __init__(self, responses: dict[str, object], clock: FakeClock) -> None:
                super().__init__(responses)
                self.clock = clock

            def __call__(self, argv: tuple[str, ...], timeout_seconds: float) -> subprocess.CompletedProcess[str]:
                result = super().__call__(argv, timeout_seconds)
                self.clock.value += MODULE.TOTAL_QUERY_BUDGET_SECONDS
                return result

        clock = FakeClock()
        runner = BudgetRunner(self.responses, clock)
        prefix = (
            "mise",
            "exec",
            "--",
            "kubectl",
            "--kubeconfig",
            "/fixture/kubeconfig",
            "--context",
            "fixture-context",
        )
        report = MODULE.evaluate(
            self.observed_at,
            runner,
            clock,
            prefix_provider=lambda: prefix,
        )
        self.assertEqual(len(runner.argvs), 1)
        self.assertEqual(report["measures"]["restarts"]["total"]["state"], "observed")
        self.assertEqual(report["measures"]["restarts"]["state"], "budget_exhausted")
        self.assertEqual(report["measures"]["oom"]["state"], "budget_exhausted")
        self.assertEqual(report["measures"]["api_latency"]["state"], "budget_exhausted")
        self.assertIn("api_latency_current_budget_exhausted", report["coverage"]["reasons"])


if __name__ == "__main__":
    unittest.main()
