"""Tests for guarded Airflow Spark lakehouse operations."""

from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[2]
LIB = REPO / "scripts" / "lib"
sys.path.insert(0, str(LIB))

from airflow_lakehouse_operations import (  # noqa: E402
    APPROVAL_TOKEN,
    KubectlClient,
    OperationError,
    _loki_summary,
    _resource_summary,
    _retained_artifact_passed,
    _task_pod_image_matches,
    airflow_loki_query,
    application_outcome,
    attempt_pod_loki_query,
    attempt_name,
    build_trigger_command,
    evaluate_gate_preflight,
    flight_recorder_source_loki_query,
    pod_loki_query,
    require_live_approval,
    resource_released_after_success,
    validate_evidence_run_id,
    validate_run_request,
)
from lakehouse_trino import flight_recorder_facts_from_checks  # noqa: E402
from spark_attempt_evidence import (  # noqa: E402
    LakehouseEvidenceRequest,
    _evaluate_flight_recorder_rejection,
    _evaluate_flight_recorder_report,
    _valid_component_counts,
    _valid_contracts,
    _valid_summary,
    _valid_source_receipt,
    component_catalog_sha256,
    collect_spark_attempt_evidence,
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
    def _authoritative_evidence(
        self,
        *,
        receipt_events=("lease_acquired", "task_completion", "terminal_state"),
        receipt_attempt="lh-airflow-run-auth-a2e1e078723c-a1",
        prior_application_active=False,
        lease_holder=None,
        spark_state="Succeeded",
        completion_state="succeeded",
        lease_target="authoritative",
        ledger_target="authoritative",
        trino_run_id=None,
        extra_conflicting_lease=False,
        history_completed=True,
        error_samples=0,
        trino_artifact="trino",
        snapshot_changed=True,
        workflow_status="success",
        schedule_enabled=True,
        within_learning_ceilings=True,
        include_prior_attempt=False,
        run_id="scheduled__2026-08-14T13:23:00+00:00",
    ):
        attempt = "lh-airflow-run-auth-a2e1e078723c-a1"
        airflow_digest = "sha256:" + "a" * 64
        spark_digest = "sha256:" + "b" * 64

        class FakeKubectl:
            def spark_application(self, name):
                return {
                    "apiVersion": "spark.apache.org/v1",
                    "kind": "SparkApplication",
                    "metadata": {
                        "name": name,
                        "creationTimestamp": "2026-08-14T13:23:20+00:00",
                    },
                    "status": {
                        "currentState": {"currentStateSummary": "ResourceReleased"},
                        "stateTransitionHistory": {
                            "1": {"currentStateSummary": spark_state},
                            "2": {"currentStateSummary": "ResourceReleased"},
                        },
                        "driverInfo": {"podName": "driver-pod"},
                    },
                }

            def attempt_pods(self, name):
                return []

            def get_raw(self, path):
                if "spark-history-server" in path:
                    return [{"id": attempt, "name": attempt, "attempts": [{"completed": history_completed}]}]
                if "error%7Cexception%7Ctraceback" in path or "fatal%7Cerror" in path:
                    result = []
                    if error_samples:
                        result = [{"stream": {}, "values": [["1", "error"]] * error_samples}]
                    return {"data": {"result": result}}
                streams = []
                for event in receipt_events:
                    receipt = {"event": event, "attempt": receipt_attempt}
                    if event == "lease_acquired":
                        receipt["prior_application_active"] = prior_application_active
                        receipt["target"] = lease_target
                    if event in {"task_completion", "terminal_state"}:
                        receipt["state"] = completion_state
                    streams.append(
                        {
                            "stream": {"event": f"spark_attempt_receipt {json.dumps(receipt)}"},
                            "values": [["1", "line"]],
                        }
                    )
                if include_prior_attempt:
                    for event in receipt_events:
                        receipt = {"event": event, "attempt": "lh-prior-attempt-a1"}
                        if event == "lease_acquired":
                            receipt["prior_application_active"] = False
                            receipt["target"] = "authoritative"
                        if event in {"task_completion", "terminal_state"}:
                            receipt["state"] = "succeeded"
                        streams.append(
                            {
                                "stream": {"event": f"spark_attempt_receipt {json.dumps(receipt)}"},
                                "values": [["1", "line"]],
                            }
                        )
                if extra_conflicting_lease:
                    receipt = {
                        "event": "lease_acquired",
                        "attempt": receipt_attempt,
                        "target": "shadow",
                        "prior_application_active": True,
                    }
                    streams.append(
                        {
                            "stream": {"event": f"spark_attempt_receipt {json.dumps(receipt)}"},
                            "values": [["1", "line"]],
                        }
                    )
                return {"data": {"result": streams}}

            def lease(self, name):
                if lease_holder is None:
                    return None
                return {"spec": {"holderIdentity": lease_holder}}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "trino.json").write_text(
                json.dumps(
                    {
                        "artifact": trino_artifact,
                        "run_id": trino_run_id or run_id,
                        "passed": True,
                        "details": {
                            "normalized_count": 5,
                            "hourly_count": 5,
                            "hourly_event_count_sum": 5,
                            "schema": True,
                            "partitions": True,
                            "snapshots": True,
                            "locations": True,
                            "snapshots_before": {"normalized": "100", "hourly": "200"},
                            "snapshots_after": {
                                "normalized": "101" if snapshot_changed else "100",
                                "hourly": "201" if snapshot_changed else "200",
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            (root / "workflow.json").write_text(
                json.dumps(
                    {
                        "artifact": "workflow_run",
                        "run_id": run_id,
                        "passed": True,
                        "details": {
                            "dag_id": "airflow_spark_lakehouse",
                            "run_id": run_id,
                            "task_id": "run_authoritative_spark_attempt",
                            "try_number": 1,
                            "attempt_name": attempt,
                            "run_type": "scheduled",
                            "status": workflow_status,
                            "task_status": "success",
                            "schedule_enabled": schedule_enabled,
                            "schedule": "23 * * * *",
                            "dag_digest": "dag-sha256",
                            "expected_start": "2026-08-14T13:23:00+00:00",
                            "end_date": "2026-08-14T13:30:00+00:00",
                            "airflow_image_digest": airflow_digest,
                            "spark_image_digest": spark_digest,
                        },
                    }
                ),
                encoding="utf-8",
            )
            (root / "resources.json").write_text(
                json.dumps(
                    {
                        "artifact": "resources",
                        "run_id": run_id,
                        "attempt_name": attempt,
                        "passed": True,
                        "details": {
                            "within_learning_ceilings": within_learning_ceilings,
                            "measurements": {
                                "peak_memory_bytes": 278357606,
                                "memory_ceiling_bytes": 1073741824,
                                "cpu_sample": None,
                                "cpu_sample_limitation": "Pods ended before the next scrape.",
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            ledger = root / "ledger.json"
            ledger.write_text(
                json.dumps(
                    {
                        "candidate": {
                            "airflow_image_digest": airflow_digest,
                            "spark_image_digest": spark_digest,
                            "dag_digest": "dag-sha256",
                        },
                        "runs": [
                            {
                                "run_id": run_id,
                                "status": "passed",
                                "target": ledger_target,
                                "spark": {"attempt_name": attempt, "image_digest": spark_digest},
                                "evidence": {
                                    "trino": "trino.json",
                                    "workflow_run": "workflow.json",
                                    "resources": "resources.json",
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            return collect_spark_attempt_evidence(
                LakehouseEvidenceRequest(
                    run_id=run_id,
                    target="authoritative",
                    ledger_path=ledger,
                ),
                kubectl=FakeKubectl(),
                root=REPO,
                now=datetime(2026, 8, 14, 13, 30, tzinfo=timezone.utc),
            )

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

    def test_authoritative_attempt_name_matches_deployed_identity(self) -> None:
        deployed = _load_identity_module()
        run_id = "scheduled__2026-08-14T13:23:00+00:00"
        task_id = "run_authoritative_spark_attempt"
        self.assertEqual(
            attempt_name(run_id=run_id, try_number=1, task_id=task_id),
            deployed.attempt_name(
                dag_id="airflow_spark_lakehouse",
                run_id=run_id,
                task_id=task_id,
                map_index=-1,
                try_number=1,
            ),
        )

    def test_authoritative_evidence_dispatches_exact_identity_and_lease(self) -> None:
        class FakeKubectl:
            spark_name = None
            lease_name = None

            def spark_application(self, name):
                self.spark_name = name
                return None

            def attempt_pods(self, name):
                return []

            def get_raw(self, path):
                if "spark-history-server" in path:
                    return []
                return {"data": {"result": []}}

            def lease(self, name):
                self.lease_name = name
                return None

        client = FakeKubectl()
        result = collect_spark_attempt_evidence(
            LakehouseEvidenceRequest(
                run_id="scheduled__2026-08-14T13:23:00+00:00",
                target="authoritative",
            ),
            kubectl=client,
            root=REPO,
            now=datetime(2026, 8, 14, 13, 30, tzinfo=timezone.utc),
        )
        self.assertEqual("lh-airflow-run-auth-a2e1e078723c-a1", client.spark_name)
        self.assertEqual("lakehouse-authoritative-writer", client.lease_name)
        self.assertEqual("run_authoritative_spark_attempt", result["identity"]["task_id"])
        self.assertEqual("authoritative", result["identity"]["target"])

    def test_evidence_rejects_unknown_target(self) -> None:
        with self.assertRaisesRegex(OperationError, "unsupported evidence target"):
            LakehouseEvidenceRequest(
                run_id="scheduled__2026-08-14T13:23:00+00:00",
                target="unknown",
            )

    def test_authoritative_evidence_requires_complete_success_chain(self) -> None:
        self.assertEqual("complete", self._authoritative_evidence()["status"])
        cases = {
            "missing receipt": {
                "receipt_events": ("lease_acquired", "terminal_state"),
                "missing": "airflow_receipts",
            },
            "wrong attempt": {
                "receipt_attempt": "different-attempt",
                "missing": "airflow_attempt_identity",
            },
            "active prior application": {
                "prior_application_active": True,
                "missing": "lease_acquisition",
            },
            "conflicting holder": {
                "lease_holder": "different-attempt",
                "missing": "conflicting_lease_holder",
            },
            "failed Spark outcome": {
                "spark_state": "Failed",
                "missing": "spark_succeeded",
            },
            "failed completion receipt": {
                "completion_state": "failed",
                "missing": "terminal_state_succeeded",
            },
            "wrong Lease target": {
                "lease_target": "shadow",
                "missing": "lease_acquisition",
            },
            "wrong retained target": {
                "ledger_target": "shadow",
                "missing": "trino",
            },
            "wrong Trino run": {
                "trino_run_id": "scheduled__different",
                "missing": "trino",
            },
            "conflicting Lease receipt": {
                "extra_conflicting_lease": True,
                "missing": "lease_acquisition",
            },
            "incomplete history": {
                "history_completed": False,
                "missing": "history_server",
            },
            "runtime log errors": {
                "error_samples": 1,
                "missing": "pod_loki_errors",
            },
            "wrong Trino artifact": {
                "trino_artifact": "workflow_run",
                "missing": "trino",
            },
            "unchanged snapshots": {
                "snapshot_changed": False,
                "missing": "trino",
            },
            "failed Workflow Run": {
                "workflow_status": "failed",
                "missing": "workflow_run",
            },
            "disabled schedule": {
                "schedule_enabled": False,
                "missing": "workflow_run",
            },
            "resource ceiling failure": {
                "within_learning_ceilings": False,
                "missing": "resources",
            },
        }
        for label, values in cases.items():
            missing = values.pop("missing")
            with self.subTest(label=label):
                result = self._authoritative_evidence(**values)
                self.assertEqual("incomplete", result["status"])
                self.assertIn(missing, result["missing"])

    def test_authoritative_evidence_accepts_receipts_from_a_prior_retry(self) -> None:
        result = self._authoritative_evidence(include_prior_attempt=True)
        self.assertEqual("complete", result["status"])

    def test_authoritative_evidence_rejects_manual_run(self) -> None:
        result = self._authoritative_evidence(run_id="manual__2026-08-14T13:23:00+00:00")
        self.assertEqual("incomplete", result["status"])
        self.assertIn("scheduled_run_identity", result["missing"])

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
        attempt_query = attempt_pod_loki_query("exact-attempt")
        self.assertIn('k8s_pod_name=~"exact-attempt.*"', attempt_query)
        self.assertIn('severity=~"fatal|error"', attempt_pod_loki_query("exact-attempt", errors_only=True))

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

    def test_task_wrappers_remove_retired_shadow_mutations(self) -> None:
        source = (REPO / ".taskfiles" / "airflow" / "Taskfile.yaml").read_text(encoding="utf-8")
        self.assertIn("attempt-evidence:", source)
        for retired_target in (
            "gate-preflight:",
            "trigger-shadow-run:",
            "trigger-shadow-run:execute:",
            "recovery-case:",
            "recovery-case:execute:",
        ):
            self.assertNotIn(retired_target, source)
        self.assertIn("--target \"$TARGET\"", source)
        self.assertNotIn("--approval-token shadow-live-mutation", source)

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

    def test_flight_recorder_requires_success_before_resource_release(self) -> None:
        self.assertTrue(resource_released_after_success({
            "status": {"stateTransitionHistory": {
                "1": {"currentStateSummary": "RunningHealthy"},
                "2": {"currentStateSummary": "Succeeded"},
                "3": {"currentStateSummary": "ResourceReleased"},
            }},
        }))
        for history in (
            {"1": {"currentStateSummary": "Succeeded"}},
            {"1": {"currentStateSummary": "ResourceReleased"}},
            {
                "1": {"currentStateSummary": "ResourceReleased"},
                "2": {"currentStateSummary": "Succeeded"},
            },
        ):
            with self.subTest(history=history):
                self.assertFalse(resource_released_after_success({
                    "status": {"stateTransitionHistory": history},
                }))

    def test_loki_summary_retains_exact_flight_recorder_source_receipt(self) -> None:
        receipt = {
            "schema_version": 1,
            "query": '{k8s_namespace_name="airflow"}',
            "window_start": "2026-08-14T12:00:00Z",
            "window_end": "2026-08-14T12:05:00Z",
            "entry_count": 312,
            "raw_bytes": 42000,
            "raw_key": "flight-recorder/raw/window/checksum.jsonl",
            "raw_sha256": "a" * 64,
            "attempt": "attempt-1",
            "manifest_key": "flight-recorder/manifests/window/query.json",
        }

        class FakeKubectl:
            def get_raw(self, _path):
                return {"data": {"result": [{
                    "stream": {"event": f"flight_recorder_source_receipt {json.dumps(receipt)}"},
                    "values": [["1", "line"]],
                }]}}

        summary = _loki_summary(
            FakeKubectl(),
            flight_recorder_source_loki_query("attempt-1"),
            datetime(2026, 8, 14, 12, tzinfo=timezone.utc),
            datetime(2026, 8, 14, 13, tzinfo=timezone.utc),
        )
        self.assertEqual([receipt], summary["source_receipts"])

    def test_complete_hour_receipt_and_component_counts_reconcile(self) -> None:
        hour_id, checksum = "1786705200000000000-1786708800000000000", "a" * 64
        receipt = {
            "schema_version": 2, "kind": "flight_recorder_complete_hour", "status": "complete",
            "hour_start": "2026-08-14T11:00:00Z", "hour_end": "2026-08-14T12:00:00Z",
            "source_hour_id": hour_id, "catalog_sha256": component_catalog_sha256(),
            "component_count": 4, "chunk_count": 48, "source_count": 48,
            "raw_bytes": 480, "attempt": "attempt-hour",
            "manifest_key": f"flight-recorder/hours/{hour_id}/{checksum}.complete.json",
            "manifest_sha256": checksum,
        }
        summary = {
            "latest_source_window_id": hour_id, "latest_complete_manifest_sha256": checksum,
            "latest_source_kind": "complete_hour", "latest_source_count": 48,
            "latest_accepted_count": 44, "latest_rejected_count": 4,
            "latest_final_event_count": 40,
        }
        self.assertTrue(_valid_source_receipt(receipt, attempt="attempt-hour", summary=summary))
        changed_receipt = {**receipt, "catalog_sha256": "b" * 64}
        self.assertFalse(
            _valid_source_receipt(changed_receipt, attempt="attempt-hour", summary=summary),
        )
        changed_receipt = {**receipt, "source_count": 1_000_000}
        changed_summary = {**summary, "latest_source_count": 1_000_000}
        self.assertFalse(
            _valid_source_receipt(
                changed_receipt,
                attempt="attempt-hour",
                summary=changed_summary,
            ),
        )
        changed_receipt = {**receipt, "raw_bytes": 1_000_000_000}
        self.assertFalse(
            _valid_source_receipt(changed_receipt, attempt="attempt-hour", summary=summary),
        )
        rows = [{
            "source_window_id": hour_id, "source_component": component,
            "source_count": 12, "accepted_count": 11, "rejected_count": 1,
            "deduplicated_count": 10, "written_count": 10,
        } for component in ("workflow", "spark_operator", "trino", "seaweedfs")]
        self.assertTrue(_valid_component_counts(rows, summary, receipt))
        rows[0]["written_count"] = 9
        self.assertFalse(_valid_component_counts(rows, summary, receipt))
        rows[0]["source_component"] = ["workflow"]
        self.assertFalse(_valid_component_counts(rows, summary, receipt))

    def test_loki_summary_retains_complete_hour_and_rejection_evidence(self) -> None:
        attempt = "attempt-hour"
        hour_receipt = {
            "schema_version": 2, "kind": "flight_recorder_complete_hour", "status": "complete",
            "hour_start": "2026-08-14T11:00:00Z", "hour_end": "2026-08-14T12:00:00Z",
            "source_hour_id": "1-2", "catalog_sha256": "a" * 64,
            "component_count": 4, "chunk_count": 48, "source_count": 48, "raw_bytes": 480,
            "attempt": attempt, "manifest_key": "flight-recorder/hours/1-2/a.complete.json",
            "manifest_sha256": "a" * 64,
        }
        rejection = {
            "source_hour_id": "1-2", "attempt": attempt, "component": "trino",
            "chunk_index": 4, "completed_queries": 28,
            "complete_manifest_published": False,
        }

        class FakeKubectl:
            def get_raw(self, _path):
                return {"data": {"result": [
                    {"stream": {"event": f"flight_recorder_hour_receipt {json.dumps(hour_receipt)}"},
                     "values": [["1", "line"]]},
                    {"stream": {"event": f"flight_recorder_hour_rejection {json.dumps(rejection)}"},
                     "values": [["2", "line"]]},
                ]}}

        summary = _loki_summary(
            FakeKubectl(), flight_recorder_source_loki_query(attempt),
            datetime(2026, 8, 14, 12, tzinfo=timezone.utc),
            datetime(2026, 8, 14, 13, tzinfo=timezone.utc),
        )
        self.assertEqual(([hour_receipt], [rejection]), (
            summary["hour_receipts"], summary["hour_rejections"],
        ))

    def test_complete_hour_summary_allows_deduplicated_events(self) -> None:
        summary = {
            "latest_source_kind": "complete_hour",
            "latest_source_count": 48,
            "latest_accepted_count": 44,
            "latest_rejected_count": 4,
            "latest_final_event_count": 40,
            "event_count": 40,
            "hourly_event_count_sum": 40,
            "rejected_count": 4,
            "hourly_rejection_count_sum": 4,
            "receipt_count": 1,
        }
        self.assertTrue(_valid_summary(summary))
        summary["latest_source_count"] = "48"
        self.assertFalse(_valid_summary(summary))
        summary["latest_source_count"] = 48
        summary["latest_source_kind"] = None
        self.assertFalse(_valid_summary(summary))

    def test_rejected_hour_skips_new_schema_checks(self) -> None:
        attempt = "lh-airflow-run-flig-1e20acc910bd-a1"
        digest = "sha256:" + "a" * 64
        result = {
            "status": "incomplete",
            "identity": {"attempt_name": attempt},
            "live": {
                "spark_application": None,
                "pods": [],
                "airflow_task_pods": [{
                    "phase": "Failed",
                    "requested_images": [f"registry/airflow@{digest}"],
                    "containers": [{"image_id": f"registry/airflow@{digest}"}],
                }],
                "expected_airflow_digest": digest,
                "lease_holder": None,
                "flight_recorder_source_loki": {
                    "samples": 1,
                    "source_receipts": [],
                    "hour_receipts": [],
                    "hour_rejections": [{
                        "source_hour_id": "1786705200000000000-1786708800000000000",
                        "attempt": attempt,
                        "component": "trino",
                        "chunk_index": 4,
                        "completed_queries": 28,
                        "complete_manifest_published": False,
                    }],
                },
            },
            "missing": ["spark_application", "spark_succeeded", "history_server"],
        }

        evaluated = _evaluate_flight_recorder_rejection(result)
        self.assertEqual("rejected", evaluated["status"])
        self.assertEqual([], evaluated["missing"])
        self.assertEqual({}, evaluated["trino"])
        result["live"]["flight_recorder_source_loki"]["hour_rejections"][0][
            "component"
        ] = ["trino"]
        malformed = _evaluate_flight_recorder_rejection(result)
        self.assertEqual("incomplete", malformed["status"])

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

    def test_task_pod_image_requires_requested_and_runtime_digest(self) -> None:
        digest = "sha256:" + "a" * 64
        pod = {
            "spec": {"containers": [{"name": "base", "image": f"registry/image@{digest}"}]},
            "status": {"containerStatuses": [{
                "name": "base", "image": f"registry/image@{digest}",
                "imageID": f"registry/image@{digest}", "restartCount": 0,
            }]},
        }
        self.assertTrue(_task_pod_image_matches([pod], digest))
        pod["status"]["containerStatuses"][0]["imageID"] = "registry/image@sha256:" + "b" * 64
        self.assertFalse(_task_pod_image_matches([pod], digest))

    def test_flight_recorder_checks_require_exact_source_and_unchanged_replay(self) -> None:
        attempt = "lh-airflow-run-flig-123-a1"
        source_receipt = {
            "schema_version": 1, "query": '{k8s_namespace_name="airflow"}',
            "window_start": "2026-08-14T12:00:00Z", "window_end": "2026-08-14T12:05:00Z",
            "entry_count": 2, "raw_bytes": 200,
            "raw_key": "flight-recorder/raw/1786708800000000000-1786709100000000000/" + "a" * 64 + ".jsonl",
            "raw_sha256": "a" * 64, "attempt": attempt,
            "manifest_key": "flight-recorder/manifests/1786708800000000000-1786709100000000000/q.json",
        }
        row = {
            "event_count": 2, "rejected_count": 0, "hourly_event_count_sum": 2,
            "hourly_rejection_count_sum": 0, "receipt_count": 1,
            "latest_source_window_id": "1786708800000000000-1786709100000000000",
            "latest_raw_sha256": "a" * 64,
            "latest_spark_attempt": attempt, "latest_source_count": 2,
            "latest_accepted_count": 2, "latest_rejected_count": 0,
            "latest_final_event_count": 2,
        }
        columns = {
            "events": (
                ("fingerprint", "varchar"),
                ("event_timestamp", "timestamp(6) with time zone"),
                ("event_date", "date"), ("source_window_id", "varchar"),
                ("source_timestamp_ns", "varchar"), ("namespace", "varchar"),
                ("workload_kind", "varchar"), ("workload_name", "varchar"),
                ("pod_name", "varchar"), ("container_name", "varchar"),
                ("severity", "varchar"), ("redacted_preview", "varchar"),
                ("rejected", "boolean"), ("rejection_reason", "varchar"),
                ("source_component", "varchar"), ("source_chunk_id", "integer"),
            ),
            "hourly": (
                ("hour", "timestamp(6) with time zone"), ("namespace", "varchar"),
                ("workload_kind", "varchar"), ("workload_name", "varchar"),
                ("severity", "varchar"), ("event_count", "bigint"),
                ("rejection_count", "bigint"), ("source_component", "varchar"),
            ),
            "run_receipts": (
                ("source_window_id", "varchar"), ("raw_sha256", "varchar"),
                ("manifest_uri", "varchar"), ("raw_uri", "varchar"),
                ("source_count", "bigint"), ("accepted_count", "bigint"),
                ("rejected_count", "bigint"), ("final_event_count", "bigint"),
                ("spark_attempt", "varchar"),
                ("window_start", "timestamp(6) with time zone"),
                ("window_end", "timestamp(6) with time zone"),
                ("completed_at", "timestamp(6) with time zone"),
                ("completion_date", "date"), ("source_kind", "varchar"),
                ("complete_manifest_sha256", "varchar"),
            ),
            "component_counts": (
                ("source_window_id", "varchar"), ("source_component", "varchar"),
                ("source_count", "bigint"), ("accepted_count", "bigint"),
                ("rejected_count", "bigint"), ("deduplicated_count", "bigint"),
                ("written_count", "bigint"),
                ("completed_at", "timestamp(6) with time zone"),
                ("completion_date", "date"),
            ),
        }
        partitions = {
            "events": "event_date", "hourly": "day(hour)",
            "run_receipts": "completion_date", "component_counts": "completion_date",
        }
        contracts = []
        for table in ("events", "hourly", "run_receipts", "component_counts"):
            contracts.extend((
                [{"Column": name, "Type": kind} for name, kind in columns[table]],
                [{"Create Table": (
                    f"CREATE TABLE iceberg.flight_recorder.{table} (x varchar) WITH ("
                    f"format = 'PARQUET', format_version = 2, location = "
                    f"'s3://iceberg-warehouse/flight_recorder/{table}', partitioning = ARRAY['{partitions[table]}'])"
                )}],
            ))
        self.assertTrue(_valid_contracts(contracts))
        timestamp_columns = (
            (0, "event_timestamp"),
            (2, "hour"),
            (4, "window_start"),
            (4, "window_end"),
            (4, "completed_at"),
            (6, "completed_at"),
        )
        for result_index, column in timestamp_columns:
            changed_contracts = json.loads(json.dumps(contracts))
            changed_row = next(
                row for row in changed_contracts[result_index] if row["Column"] == column
            )
            changed_row["Type"] = "timestamp(6)"
            with self.subTest(column=column, result_index=result_index):
                self.assertFalse(_valid_contracts(changed_contracts))
        outputs = {
            "flight-recorder-summary": {
                "check": "flight-recorder-summary", "results": [[row]],
            },
            "flight-recorder-contract": {
                "check": "flight-recorder-contract", "results": contracts,
            },
            "flight-recorder-snapshots": {
                "check": "flight-recorder-snapshots",
                "results": [[{
                    "snapshot_id": 1, "committed_at": "2026-08-14T12:06:00Z",
                }]] * 4,
            },
            "flight-recorder-components": {
                "check": "flight-recorder-components", "results": [[]],
            },
            "flight-recorder-namespace-isolation": {
                "check": "flight-recorder-namespace-isolation", "results": [[
                {"table_name": "normalized", "snapshot_id": 1, "committed_at": "2026-08-14T11:59:00Z"},
                {"table_name": "hourly", "snapshot_id": 2, "committed_at": "2026-08-14T11:59:00Z"},
            ]]},
        }
        result = {
            "status": "complete",
            "identity": {"dag_id": "airflow_flight_recorder", "run_id": "run-1", "attempt_name": attempt},
            "observed_at": "2026-08-14T12:10:00+00:00",
            "live": {
                "spark_application": {"created_at": "2026-08-14T12:00:00+00:00"},
                "flight_recorder_source_loki": {"source_receipts": [source_receipt]},
            },
            "missing": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            namespace_baseline = Path(directory) / "namespace-baseline.json"
            namespace_baseline.write_text(
                json.dumps(outputs["flight-recorder-namespace-isolation"]),
                encoding="utf-8",
            )
            result = _evaluate_flight_recorder_report(
                result,
                flight_recorder_facts_from_checks(outputs),
                namespace_baseline=json.loads(namespace_baseline.read_text(encoding="utf-8")),
                namespace_baseline_path=namespace_baseline,
            )
            self.assertEqual([], result["missing"])
            baseline = Path(directory) / "baseline.json"
            baseline.write_text(json.dumps(result), encoding="utf-8")
            replay_receipt = {**source_receipt, "attempt": "attempt-2"}
            replay = {
                **result,
                "identity": {**result["identity"], "run_id": "run-2", "attempt_name": "attempt-2"},
                "live": {
                    **result["live"],
                    "flight_recorder_source_loki": {"source_receipts": [replay_receipt]},
                },
            }
            replay = _evaluate_flight_recorder_report(
                replay,
                flight_recorder_facts_from_checks(outputs),
                replay_baseline=json.loads(baseline.read_text(encoding="utf-8")),
                replay_baseline_path=baseline,
            )
            self.assertEqual((result["status"], replay["status"]), ("complete", "complete"))

            changed = {**replay_receipt, "window_end": "2026-08-14T12:10:00Z"}
            replay["live"]["flight_recorder_source_loki"]["source_receipts"] = [changed]
            replay = _evaluate_flight_recorder_report(
                replay,
                flight_recorder_facts_from_checks(outputs),
                replay_baseline=json.loads(baseline.read_text(encoding="utf-8")),
                replay_baseline_path=baseline,
            )
            self.assertIn("flight_recorder_replay_source_changed", replay["missing"])

    def test_retained_artifact_can_satisfy_expired_live_lookup(self) -> None:
        retained = {"artifacts": {"loki": {"passed": True}}}
        self.assertTrue(_retained_artifact_passed(retained, "loki"))
        self.assertFalse(_retained_artifact_passed(retained, "history_server"))


if __name__ == "__main__":
    unittest.main()
