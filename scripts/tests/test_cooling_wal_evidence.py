from __future__ import annotations

import importlib.util
import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "collect-cooling-wal-evidence.py"
SPEC = importlib.util.spec_from_file_location("cooling_wal_evidence", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def response(labels: dict[str, str], values: list[list[object]]) -> str:
    return json.dumps({"status": "success", "data": {"resultType": "matrix", "result": [{"metric": labels, "values": values}]}})


class CoolingWalEvidenceTests(unittest.TestCase):
    def test_series_summary_reports_evaluation_points_zero_fraction_and_delta(self) -> None:
        start = datetime(2026, 10, 19, 0, 0, tzinfo=UTC)
        end = datetime(2026, 10, 19, 0, 1, tzinfo=UTC)
        fan = MODULE.summarize_series({"status": "success", "data": {"resultType": "matrix", "result": [{"metric": {"nodename": "k8s-2", "sensor": "fan1"}, "values": [[179, "0"], [209, "1200"]]}]}}, start, end, 30, metric_name="fan1_rpm")
        self.assertEqual("observed", fan["state"])
        self.assertEqual(3, fan["coverage"]["expected_query_evaluation_points_per_series"])
        self.assertIn("does not prove raw scrape continuity", fan["coverage"]["basis"])
        self.assertEqual(2, fan["series"][0]["query_evaluation_points"])
        self.assertEqual(0.6667, fan["series"][0]["evaluation_point_fraction"])
        self.assertEqual(0.5, fan["series"][0]["zero_fraction"])
        throttle = MODULE.summarize_series({"status": "success", "data": {"resultType": "matrix", "result": [{"metric": {"nodename": "k8s-2"}, "values": [[179, "4"], [209, "9"]]}]}}, start, end, 30, metric_name="package_throttles")
        self.assertEqual(5.0, throttle["series"][0]["counter_delta"])
        reset = MODULE.summarize_series({"status": "success", "data": {"resultType": "matrix", "result": [{"metric": {"nodename": "k8s-2"}, "values": [[179, "9"], [209, "2"]]}]}}, start, end, 30, metric_name="package_throttles")
        self.assertTrue(reset["series"][0]["counter_reset_observed"])
        self.assertIsNone(reset["series"][0]["counter_delta"])

    def test_missing_metric_is_unknown_and_invalid_payload_is_not_zero(self) -> None:
        start = datetime(2026, 10, 19, 0, 0, tzinfo=UTC)
        end = datetime(2026, 10, 19, 0, 1, tzinfo=UTC)
        missing = MODULE.summarize_series({"status": "success", "data": {"resultType": "matrix", "result": []}}, start, end, 30)
        invalid = MODULE.summarize_series({"status": "success", "data": []}, start, end, 30)
        self.assertEqual("no_data", missing["state"])
        self.assertEqual([], missing["series"])
        self.assertEqual("invalid_response", invalid["state"])

    def test_collect_emits_cooling_metrics_and_links_existing_wal_work(self) -> None:
        start = datetime(2026, 10, 19, 0, 0, tzinfo=UTC)
        end = datetime(2026, 10, 19, 0, 1, tzinfo=UTC)
        matrix = response({"nodename": "k8s-2", "sensor": "fan1"}, [[179, "0"], [209, "0"]])

        def runner(argv, timeout):
            return type("Result", (), {"returncode": 0, "stdout": matrix})()

        report = MODULE.collect(start, end, 30, prefix=("kubectl",), runner=runner)
        self.assertEqual(1.0, report["metrics"]["fan1_rpm"]["series"][0]["zero_fraction"])
        self.assertIn("does not prove raw scrape continuity", report["interpretation"]["coverage_basis"])
        self.assertEqual("context/plans/0026-investigate-loki-wal-replay.md", report["loki_wal_followup"]["plan"])
        self.assertEqual("unknown", report["loki_wal_followup"]["historical_loss_quantity"])

    def test_cli_fails_closed_before_collection_when_target_preflight_fails(self) -> None:
        with patch.object(MODULE, "anton_kubectl_prefix", side_effect=MODULE.TargetPreflightError("wrong context")), patch("sys.stderr") as stderr:
            self.assertEqual(1, MODULE.main(["--window", "1"]))
            self.assertIn("blocked by target preflight", "".join(str(part) for part in stderr.write.call_args_list))

    def test_cli_success_emits_unknown_metric_states_from_fixture(self) -> None:
        fixture_report = {"schema_version": 1, "metrics": {"fan1_rpm": {"state": "no_data", "series": []}, "nvme_temp2_celsius": {"state": "query_error", "series": []}}, "interpretation": {"source_is_read_only": True}}
        output = io.StringIO()
        with patch.object(MODULE, "anton_kubectl_prefix", return_value=("kubectl",)), patch.object(MODULE, "collect", return_value=fixture_report), redirect_stdout(output):
            self.assertEqual(0, MODULE.main(["--window", "1", "--observed-at", "2026-10-19T01:00:00Z"]))
        report = json.loads(output.getvalue())
        self.assertEqual("no_data", report["metrics"]["fan1_rpm"]["state"])
        self.assertEqual("query_error", report["metrics"]["nvme_temp2_celsius"]["state"])
        self.assertTrue(report["interpretation"]["source_is_read_only"])


if __name__ == "__main__":
    unittest.main()
