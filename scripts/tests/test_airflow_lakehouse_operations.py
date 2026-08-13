"""Tests for guarded Airflow Spark lakehouse operations."""

from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import threading
import unittest


REPO = Path(__file__).resolve().parents[2]
LIB = REPO / "scripts" / "lib"
sys.path.insert(0, str(LIB))

from airflow_lakehouse_operations import (  # noqa: E402
    APPROVAL_TOKEN,
    KubectlClient,
    OperationError,
    _resource_summary,
    _retained_artifact_passed,
    airflow_loki_query,
    application_outcome,
    attempt_name,
    build_trigger_command,
    evaluate_gate_preflight,
    pod_loki_query,
    require_live_approval,
    validate_evidence_run_id,
    validate_run_request,
)
from airflow_lakehouse_recovery import (  # noqa: E402
    SCENARIOS,
    _arm_action,
    _cancellation_probe_code,
    _duplicate_probe_code,
    _expired_lease_probe_code,
    _release_probe_code,
    _retry_probe_code,
    build_recovery_plan,
)


def _load_identity_module():
    path = REPO / "images" / "airflow-runtime" / "src" / "anton_airflow" / "spark" / "identity.py"
    spec = importlib.util.spec_from_file_location("deployed_spark_identity", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _ready_snapshot() -> dict:
    digest = "sha256:" + "a" * 64
    flux_names = {
        "airflow",
        "spark-operator",
        "shadow-fixture",
        "spark-history-server",
        "trino",
        "loki",
        "otel-collector",
    }
    return {
        "observed_at": "2026-08-13T12:00:00+00:00",
        "repo": {"branch": "main", "head": "abc", "origin_main": "abc", "dirty": False},
        "source": {
            "airflow_image_digest": digest,
            "spark_image_digest": "sha256:" + "b" * 64,
            "spark_api_version": "spark.apache.org/v1",
            "trino_catalogs_read_only": True,
            "reader_identities": True,
        },
        "runtime": {
            "api_resources": ["sparkapplications.spark.apache.org"],
            "airflow_images": [f"registry/airflow-runtime@{digest}"],
            "airflow_components_ready": {
                "api-server": True,
                "scheduler": True,
                "dag-processor": True,
                "triggerer": True,
            },
            "trino_ready_pods": 2,
            "trino_reader_external_secret_ready": True,
            "active_spark_applications": [],
            "lease_exists": False,
            "lease_holder": None,
            "services": [
                "observability/loki",
                "lakehouse/spark-history-server",
                "iceberg-demo/trino",
            ],
            "flux_ready": {name: True for name in flux_names},
            "flux_revisions": {name: "main@sha1:abc" for name in flux_names},
        },
    }


class AirflowLakehouseOperationsTests(unittest.TestCase):
    def test_attempt_name_matches_deployed_identity(self) -> None:
        deployed = _load_identity_module()
        run_id = "manual__2026-08-13T12:00:00+00:00"
        self.assertEqual(
            attempt_name(run_id=run_id, try_number=2),
            deployed.attempt_name(
                dag_id="airflow_spark_lakehouse",
                run_id=run_id,
                task_id="run_shadow_spark_attempt",
                map_index=-1,
                try_number=2,
            ),
        )

    def test_manual_run_rejects_future_logical_date(self) -> None:
        with self.assertRaisesRegex(OperationError, "cannot be in the future"):
            validate_run_request(
                "manual__future",
                logical_date="2026-08-14T00:00:00Z",
                now=datetime(2026, 8, 13, tzinfo=timezone.utc),
            )

    def test_manual_run_accepts_omitted_dates(self) -> None:
        result = validate_run_request(
            "manual__bounded",
            now=datetime(2026, 8, 13, tzinfo=timezone.utc),
        )
        self.assertIsNone(result["logical_date"])
        self.assertIsNone(result["source_window_end"])

    def test_evidence_lookup_accepts_scheduled_run_identity(self) -> None:
        validate_evidence_run_id("scheduled__2026-08-13T23:00:00+00:00")
        with self.assertRaisesRegex(OperationError, "bounded safe characters"):
            validate_evidence_run_id('scheduled__unsafe"query')

    def test_trigger_command_uses_exact_scheduler_and_no_default_logical_date(self) -> None:
        command = build_trigger_command(
            ("mise", "exec", "--", "kubectl", "--context", "verified"),
            scheduler_pod="airflow-scheduler-exact",
            run_id="manual__bounded",
        )
        self.assertIn("airflow-scheduler-exact", command)
        self.assertNotIn("-l", command)
        self.assertEqual(command[-1], "airflow_spark_lakehouse")

    def test_live_execution_requires_both_controls(self) -> None:
        require_live_approval(False, None)
        with self.assertRaisesRegex(OperationError, "approval-token"):
            require_live_approval(True, None)
        require_live_approval(True, APPROVAL_TOKEN)

    def test_ready_preflight_passes(self) -> None:
        result = evaluate_gate_preflight(_ready_snapshot())
        self.assertTrue(result["ready"])
        self.assertEqual([], result["blockers"])
        self.assertEqual("shadow", result["candidate"]["target"])

    def test_preflight_fails_closed_on_active_attempt(self) -> None:
        snapshot = _ready_snapshot()
        snapshot["runtime"]["active_spark_applications"] = ["lh-active"]
        result = evaluate_gate_preflight(snapshot)
        self.assertFalse(result["ready"])
        self.assertIn("no-active-spark-attempt", {item["id"] for item in result["blockers"]})

    def test_preflight_fails_closed_on_empty_lease_object(self) -> None:
        snapshot = _ready_snapshot()
        snapshot["runtime"]["lease_exists"] = True
        result = evaluate_gate_preflight(snapshot)
        self.assertFalse(result["ready"])
        self.assertIn("no-shadow-lease", {item["id"] for item in result["blockers"]})

    def test_preflight_fails_closed_on_stale_flux_revision(self) -> None:
        snapshot = _ready_snapshot()
        snapshot["runtime"]["flux_revisions"]["airflow"] = "main@sha1:old"
        result = evaluate_gate_preflight(snapshot)
        self.assertFalse(result["ready"])
        self.assertIn("flux-current", {item["id"] for item in result["blockers"]})

    def test_loki_queries_use_run_text_and_promoted_pod_metadata(self) -> None:
        self.assertIn('raw-run-id', airflow_loki_query("raw-run-id"))
        query = pod_loki_query("driver-pod")
        self.assertIn('| k8s_pod_name="driver-pod"', query)
        self.assertNotIn('{pod=', query)

    def test_service_proxy_accepts_json_array(self) -> None:
        def runner(argv, timeout_seconds):
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps([{"id": "app"}]), stderr="")

        client = KubectlClient(("kubectl",), runner=runner)
        self.assertEqual([{"id": "app"}], client.get_raw("/history"))

    def test_all_recovery_plans_arm_before_creation(self) -> None:
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario):
                plan = build_recovery_plan(scenario, f"manual__{scenario}")
                self.assertEqual("shadow", plan.as_dict()["target"])
                self.assertLess(
                    plan.steps.index("Arm the scenario watcher before the Workflow Run."),
                    plan.steps.index("Create one manual shadow Workflow Run without a future logical date."),
                )

    def test_armed_action_observes_before_action(self) -> None:
        observed = threading.Event()

        def predicate():
            observed.set()
            return "exact-target"

        armed = _arm_action(predicate, lambda value: f"changed:{value}", timeout_seconds=1)
        result = armed.wait(2)
        self.assertTrue(observed.is_set())
        self.assertEqual("changed:exact-target", result["action_result"])

    def test_production_probe_programs_compile(self) -> None:
        programs = (
            _duplicate_probe_code("manual__probe"),
            _retry_probe_code("manual__probe"),
            _release_probe_code("manual__probe", 2),
            _cancellation_probe_code("manual__probe"),
            _expired_lease_probe_code("manual__probe", "manual__probe-probe"),
        )
        for index, program in enumerate(programs):
            with self.subTest(index=index):
                compile(program, f"probe-{index}", "exec")

    def test_task_wrappers_keep_dry_run_and_execute_separate(self) -> None:
        source = (REPO / ".taskfiles" / "airflow" / "Taskfile.yaml").read_text(encoding="utf-8")
        for target in (
            "gate-preflight:",
            "trigger-shadow-run:",
            "trigger-shadow-run:execute:",
            "attempt-evidence:",
            "recovery-case:",
            "recovery-case:execute:",
        ):
            self.assertIn(target, source)
        self.assertEqual(2, source.count("--approval-token shadow-live-mutation"))

    def test_application_outcome_uses_terminal_history(self) -> None:
        resource = {
            "status": {
                "currentState": {"currentStateSummary": "ResourceReleased"},
                "stateTransitionHistory": {
                    "1": {"currentStateSummary": "RunningHealthy"},
                    "2": {"currentStateSummary": "Succeeded"},
                    "3": {"currentStateSummary": "ResourceReleased"},
                },
            }
        }
        self.assertEqual("succeeded", application_outcome(resource))

    def test_resource_summary_excludes_full_pod_status(self) -> None:
        resource = {
            "apiVersion": "spark.apache.org/v1",
            "kind": "SparkApplication",
            "metadata": {"name": "attempt", "uid": "uid"},
            "spec": {"sparkConf": {"spark.kubernetes.container.image": "image@sha256:digest"}},
            "status": {
                "currentState": {"currentStateSummary": "Succeeded"},
                "stateTransitionHistory": {"1": {"currentStateSummary": "Succeeded"}},
                "lastObservedDriverStatus": {"podIP": "private-value"},
            },
        }
        summary = _resource_summary(resource)
        self.assertEqual("attempt", summary["name"])
        self.assertEqual(["SUCCEEDED"], summary["state_history"])
        self.assertNotIn("lastObservedDriverStatus", summary)
        self.assertNotIn("private-value", json.dumps(summary))

    def test_retained_artifact_can_satisfy_expired_live_lookup(self) -> None:
        retained = {"artifacts": {"loki": {"passed": True}}}
        self.assertTrue(_retained_artifact_passed(retained, "loki"))
        self.assertFalse(_retained_artifact_passed(retained, "history_server"))


if __name__ == "__main__":
    unittest.main()
