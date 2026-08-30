"""Public outcome tests for Spark Attempt evidence."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[2]
LIB = REPO / "scripts" / "lib"
sys.path.insert(0, str(LIB))

from airflow_lakehouse_operations import OperationError, attempt_name  # noqa: E402
from lakehouse_trino import flight_recorder_facts_from_checks  # noqa: E402
from spark_attempt_evidence import (  # noqa: E402
    FlightRecorderInitialEvidenceRequest,
    FlightRecorderRejectionEvidenceRequest,
    FlightRecorderReplayEvidenceRequest,
    LakehouseEvidenceRequest,
    collect_spark_attempt_evidence,
)


DIGEST = "sha256:" + "a" * 64
NOW = datetime(2026, 8, 14, 12, 10, tzinfo=timezone.utc)
HOUR_ID = "1786705200000000000-1786708800000000000"
MANIFEST_SHA256 = "b" * 64


class FakeKubectl:
    """Return one bounded, successful Spark Attempt from cluster adapters."""

    def __init__(self, *, target: str, rejected: bool = False) -> None:
        self.target = target
        self.rejected = rejected
        self.attempt = ""

    def spark_application(self, name: str):
        self.attempt = name
        if self.rejected:
            return None
        return {
            "apiVersion": "spark.apache.org/v1",
            "kind": "SparkApplication",
            "metadata": {
                "name": name,
                "namespace": "lakehouse",
                "creationTimestamp": "2026-08-14T11:00:10+00:00",
            },
            "status": {
                "currentState": {"currentStateSummary": "ResourceReleased"},
                "stateTransitionHistory": {
                    "1": {"currentStateSummary": "Succeeded"},
                    "2": {"currentStateSummary": "ResourceReleased"},
                },
                "driverInfo": {"podName": "driver-pod"},
            },
        }

    def attempt_pods(self, _name: str):
        return []

    def airflow_task_pods(self, **_identity):
        return [{
            "metadata": {"name": "airflow-task"},
            "spec": {"containers": [{"name": "base", "image": f"registry/airflow@{DIGEST}"}]},
            "status": {
                "phase": "Failed" if self.rejected else "Succeeded",
                "containerStatuses": [{
                    "name": "base",
                    "ready": False,
                    "restartCount": 0,
                    "image": f"registry/airflow@{DIGEST}",
                    "imageID": f"registry/airflow@{DIGEST}",
                }],
            },
        }]

    def get_raw(self, path: str):
        if "spark-history-server" in path:
            if self.rejected:
                return []
            return [{
                "id": self.attempt,
                "name": self.attempt,
                "attempts": [{"completed": True}],
            }]
        if "spark_attempt_receipt" in path:
            if self.rejected:
                return {"data": {"result": []}}
            streams = []
            for event in ("lease_acquired", "terminal_state", "task_completion"):
                receipt = {"event": event, "attempt": self.attempt}
                if event == "lease_acquired":
                    receipt.update({"target": self.target, "prior_application_active": False})
                else:
                    receipt["state"] = "succeeded"
                streams.append({
                    "stream": {"event": f"spark_attempt_receipt {json.dumps(receipt)}"},
                    "values": [["1", "retained evidence"]],
                })
            return {"data": {"result": streams}}
        if "flight_recorder_" in path:
            event = self._rejection_event() if self.rejected else self._hour_receipt_event()
            return {"data": {"result": [{
                "stream": {"event": event},
                "values": [["1", "retained evidence"]],
            }]}}
        if "fatal%7Cerror" in path or "error%7Cexception%7Ctraceback" in path:
            return {"data": {"result": []}}
        if self.rejected:
            return {"data": {"result": []}}
        return {"data": {"result": [{"stream": {}, "values": [["1", "runtime log"]]}]}}

    def lease(self, _name: str):
        return None

    def _hour_receipt_event(self) -> str:
        receipt = {
            "schema_version": 2,
            "kind": "flight_recorder_complete_hour",
            "status": "complete",
            "hour_start": "2026-08-14T11:00:00Z",
            "hour_end": "2026-08-14T12:00:00Z",
            "source_hour_id": HOUR_ID,
            "catalog_sha256": "49275e31505c9300829cb0ca6fd86a198f6ee31c4b628695ba7ab555f4e930fd",
            "component_count": 4,
            "chunk_count": 48,
            "source_count": 48,
            "raw_bytes": 480,
            "attempt": self.attempt,
            "manifest_key": f"flight-recorder/hours/{HOUR_ID}/{MANIFEST_SHA256}.complete.json",
            "manifest_sha256": MANIFEST_SHA256,
        }
        return f"flight_recorder_hour_receipt {json.dumps(receipt)}"

    def _rejection_event(self) -> str:
        rejection = {
            "source_hour_id": HOUR_ID,
            "attempt": self.attempt,
            "component": "trino",
            "chunk_index": 4,
            "completed_queries": 28,
            "complete_manifest_published": False,
        }
        return f"flight_recorder_hour_rejection {json.dumps(rejection)}"


def _table_contracts() -> list[list[dict[str, object]]]:
    columns = {
        "events": (
            ("fingerprint", "varchar"), ("event_timestamp", "timestamp(6) with time zone"),
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
            ("spark_attempt", "varchar"), ("window_start", "timestamp(6) with time zone"),
            ("window_end", "timestamp(6) with time zone"),
            ("completed_at", "timestamp(6) with time zone"),
            ("completion_date", "date"), ("source_kind", "varchar"),
            ("complete_manifest_sha256", "varchar"),
        ),
        "component_counts": (
            ("source_window_id", "varchar"), ("source_component", "varchar"),
            ("source_count", "bigint"), ("accepted_count", "bigint"),
            ("rejected_count", "bigint"), ("deduplicated_count", "bigint"),
            ("written_count", "bigint"), ("completed_at", "timestamp(6) with time zone"),
            ("completion_date", "date"),
        ),
    }
    partitions = {
        "events": "event_date",
        "hourly": "day(hour)",
        "run_receipts": "completion_date",
        "component_counts": "completion_date",
    }
    result: list[list[dict[str, object]]] = []
    for table in ("events", "hourly", "run_receipts", "component_counts"):
        result.extend((
            [{"Column": name, "Type": kind} for name, kind in columns[table]],
            [{"Create Table": (
                f"CREATE TABLE iceberg.flight_recorder.{table} (x varchar) WITH ("
                f"format_version = 2, location = 's3://iceberg-warehouse/flight_recorder/{table}', "
                f"partitioning = ARRAY['{partitions[table]}'])"
            )}],
        ))
    return result


def _trino_checks(*, latest_attempt: str) -> dict[str, dict[str, object]]:
    summary = {
        "event_count": 40,
        "rejected_count": 4,
        "hourly_event_count_sum": 40,
        "hourly_rejection_count_sum": 4,
        "receipt_count": 1,
        "latest_source_window_id": HOUR_ID,
        "latest_complete_manifest_sha256": MANIFEST_SHA256,
        "latest_spark_attempt": latest_attempt,
        "latest_source_count": 48,
        "latest_accepted_count": 44,
        "latest_rejected_count": 4,
        "latest_final_event_count": 40,
        "latest_source_kind": "complete_hour",
    }
    components = [{
        "source_window_id": HOUR_ID,
        "source_component": component,
        "source_count": 12,
        "accepted_count": 11,
        "rejected_count": 1,
        "deduplicated_count": 10,
        "written_count": 10,
    } for component in ("workflow", "spark_operator", "trino", "seaweedfs")]
    namespace = [{
        "table_name": table,
        "snapshot_id": snapshot,
        "committed_at": "2026-08-14T10:59:00Z",
    } for table, snapshot in (("normalized", 10), ("hourly", 20))]
    return {
        "flight-recorder-summary": {"check": "flight-recorder-summary", "results": [[summary]]},
        "flight-recorder-contract": {"check": "flight-recorder-contract", "results": _table_contracts()},
        "flight-recorder-snapshots": {
            "check": "flight-recorder-snapshots",
            "results": [[{"snapshot_id": index, "committed_at": "2026-08-14T12:05:00Z"}]
                        for index in range(1, 5)],
        },
        "flight-recorder-components": {
            "check": "flight-recorder-components",
            "results": [components],
        },
        "flight-recorder-namespace-isolation": {
            "check": "flight-recorder-namespace-isolation",
            "results": [namespace],
        },
    }


class SparkAttemptEvidenceTests(unittest.TestCase):
    def test_lakehouse_request_returns_complete_report_without_trino(self) -> None:
        run_id = "manual__2026-08-14T11:00:00+00:00"
        attempt = attempt_name(run_id=run_id, try_number=1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "trino.json"
            artifact.write_text(json.dumps({
                "artifact": "trino",
                "run_id": run_id,
                "passed": True,
            }), encoding="utf-8")
            ledger = root / "ledger.json"
            ledger.write_text(json.dumps({
                "candidate": {},
                "runs": [{
                    "run_id": run_id,
                    "status": "passed",
                    "target": "shadow",
                    "spark": {"attempt_name": attempt},
                    "evidence": {"trino": artifact.name},
                }],
            }), encoding="utf-8")

            def unexpected_trino(_root: Path):
                self.fail("lakehouse evidence must not query live Trino")

            report = collect_spark_attempt_evidence(
                LakehouseEvidenceRequest(run_id=run_id, ledger_path=ledger),
                kubectl=FakeKubectl(target="shadow"),
                root=REPO,
                read_trino_facts=unexpected_trino,
                now=NOW,
            )

        self.assertEqual("complete", report["status"])
        self.assertEqual(1, report["schema_version"])

    def test_flight_recorder_initial_request_returns_complete_report(self) -> None:
        run_id = "manual__flight_recorder_initial"
        client = FakeKubectl(target="authoritative")
        with tempfile.TemporaryDirectory() as directory:
            baseline = Path(directory) / "namespace.json"
            checks = _trino_checks(latest_attempt="unused")
            baseline.write_text(
                json.dumps(checks["flight-recorder-namespace-isolation"]),
                encoding="utf-8",
            )
            report = collect_spark_attempt_evidence(
                FlightRecorderInitialEvidenceRequest(
                    run_id=run_id,
                    namespace_baseline_path=baseline,
                ),
                kubectl=client,
                root=REPO,
                expected_airflow_digest=DIGEST,
                read_trino_facts=lambda _root: flight_recorder_facts_from_checks(
                    _trino_checks(latest_attempt=client.attempt)
                ),
                now=NOW,
            )
            wrong_baseline = Path(directory) / "wrong-namespace.json"
            wrong_baseline.write_text(
                json.dumps({
                    **checks["flight-recorder-namespace-isolation"],
                    "check": "wrong-check",
                }),
                encoding="utf-8",
            )
            wrong_client = FakeKubectl(target="authoritative")
            wrong_report = collect_spark_attempt_evidence(
                FlightRecorderInitialEvidenceRequest(
                    run_id="manual__flight_recorder_wrong_namespace",
                    namespace_baseline_path=wrong_baseline,
                ),
                kubectl=wrong_client,
                root=REPO,
                expected_airflow_digest=DIGEST,
                read_trino_facts=lambda _root: flight_recorder_facts_from_checks(
                    _trino_checks(latest_attempt=wrong_client.attempt)
                ),
                now=NOW,
            )

        self.assertEqual("complete", report["status"])
        self.assertEqual([], report["missing"])
        self.assertEqual(1, report["schema_version"])
        self.assertIn("identity", report)
        self.assertIn("live", report)
        self.assertIn("trino", report)
        self.assertEqual(str(baseline), report["namespace_baseline"])
        self.assertIn("flight_recorder_namespace_isolation", wrong_report["missing"])

    def test_initial_request_rejects_malformed_namespace_baseline(self) -> None:
        client = FakeKubectl(target="authoritative")
        with tempfile.TemporaryDirectory() as directory:
            baseline = Path(directory) / "namespace.json"
            checks = _trino_checks(latest_attempt="unused")
            namespace_check = checks["flight-recorder-namespace-isolation"]
            namespace_check["results"][0][0]["table_name"] = ["normalized"]  # type: ignore[index]
            baseline.write_text(json.dumps(namespace_check), encoding="utf-8")

            report = collect_spark_attempt_evidence(
                FlightRecorderInitialEvidenceRequest(
                    run_id="manual__flight_recorder_malformed_namespace",
                    namespace_baseline_path=baseline,
                ),
                kubectl=client,
                root=REPO,
                expected_airflow_digest=DIGEST,
                read_trino_facts=lambda _root: flight_recorder_facts_from_checks(
                    _trino_checks(latest_attempt=client.attempt)
                ),
                now=NOW,
            )

        self.assertEqual("incomplete", report["status"])
        self.assertIn("flight_recorder_namespace_isolation", report["missing"])

    def test_flight_recorder_replay_request_accepts_same_semantic_facts(self) -> None:
        first_client = FakeKubectl(target="authoritative")
        checks = _trino_checks(latest_attempt="first-attempt")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            namespace = root / "namespace.json"
            namespace.write_text(
                json.dumps(checks["flight-recorder-namespace-isolation"]),
                encoding="utf-8",
            )
            first = collect_spark_attempt_evidence(
                FlightRecorderInitialEvidenceRequest(
                    run_id="manual__flight_recorder_first",
                    namespace_baseline_path=namespace,
                ),
                kubectl=first_client,
                root=REPO,
                expected_airflow_digest=DIGEST,
                read_trino_facts=lambda _root: flight_recorder_facts_from_checks(
                    _trino_checks(latest_attempt=first_client.attempt)
                ),
                now=NOW,
            )
            baseline = root / "baseline.json"
            baseline.write_text(json.dumps(first), encoding="utf-8")
            replay_client = FakeKubectl(target="authoritative")
            baseline_checks = first["trino"]
            reordered = deepcopy(baseline_checks)
            reordered["flight-recorder-components"]["results"][0].reverse()
            replay = collect_spark_attempt_evidence(
                FlightRecorderReplayEvidenceRequest(
                    run_id="manual__flight_recorder_replay",
                    baseline_path=baseline,
                ),
                kubectl=replay_client,
                root=REPO,
                expected_airflow_digest=DIGEST,
                read_trino_facts=lambda _root: flight_recorder_facts_from_checks(reordered),
                now=NOW,
            )
            changed_checks = deepcopy(baseline_checks)
            changed_checks["flight-recorder-snapshots"]["results"][0][0]["snapshot_id"] = 99
            changed = collect_spark_attempt_evidence(
                FlightRecorderReplayEvidenceRequest(
                    run_id="manual__flight_recorder_changed",
                    baseline_path=baseline,
                ),
                kubectl=FakeKubectl(target="authoritative"),
                root=REPO,
                expected_airflow_digest=DIGEST,
                read_trino_facts=lambda _root: flight_recorder_facts_from_checks(
                    changed_checks,
                ),
                now=NOW,
            )

        self.assertEqual("complete", replay["status"])
        self.assertNotIn("flight_recorder_replay_changed_state", replay["missing"])
        self.assertEqual(str(baseline), replay["replay_baseline"])
        self.assertIn("trino", replay)
        self.assertIn("flight_recorder_replay_changed_state", changed["missing"])

    def test_replay_baseline_requires_supported_schema_and_complete_identity(self) -> None:
        first_client = FakeKubectl(target="authoritative")
        checks = _trino_checks(latest_attempt="first-attempt")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            namespace = root / "namespace.json"
            namespace.write_text(
                json.dumps(checks["flight-recorder-namespace-isolation"]),
                encoding="utf-8",
            )
            first = collect_spark_attempt_evidence(
                FlightRecorderInitialEvidenceRequest(
                    run_id="manual__flight_recorder_baseline",
                    namespace_baseline_path=namespace,
                ),
                kubectl=first_client,
                root=REPO,
                expected_airflow_digest=DIGEST,
                read_trino_facts=lambda _root: flight_recorder_facts_from_checks(
                    _trino_checks(latest_attempt=first_client.attempt),
                ),
                now=NOW,
            )
            variants = {
                "schema version": {**first, "schema_version": 2},
                "identity": {
                    **first,
                    "identity": {
                        key: value
                        for key, value in first["identity"].items()
                        if key != "task_id"
                    },
                },
                "attempt identity": {
                    **first,
                    "identity": {**first["identity"], "attempt_name": "not-the-attempt"},
                },
            }
            for expected_error, document in variants.items():
                with self.subTest(expected_error=expected_error):
                    baseline = root / f"baseline-{expected_error.replace(' ', '-')}.json"
                    baseline.write_text(json.dumps(document), encoding="utf-8")
                    replay_client = FakeKubectl(target="authoritative")
                    with self.assertRaisesRegex(OperationError, expected_error):
                        collect_spark_attempt_evidence(
                            FlightRecorderReplayEvidenceRequest(
                                run_id=f"manual__flight_recorder_replay_{expected_error.replace(' ', '_')}",
                                baseline_path=baseline,
                            ),
                            kubectl=replay_client,
                            root=REPO,
                            expected_airflow_digest=DIGEST,
                            read_trino_facts=lambda _root: flight_recorder_facts_from_checks(
                                _trino_checks(latest_attempt=replay_client.attempt),
                            ),
                            now=NOW,
                        )

    def test_flight_recorder_rejection_returns_rejected_without_trino(self) -> None:
        def unexpected_trino(_root: Path):
            self.fail("rejection evidence must not query Trino")

        report = collect_spark_attempt_evidence(
            FlightRecorderRejectionEvidenceRequest(
                run_id="manual__flight_recorder_rejected",
            ),
            kubectl=FakeKubectl(target="authoritative", rejected=True),
            root=REPO,
            expected_airflow_digest=DIGEST,
            read_trino_facts=unexpected_trino,
            now=NOW,
        )

        self.assertEqual("rejected", report["status"])
        self.assertEqual([], report["missing"])
        self.assertEqual({}, report["trino"])
        self.assertIn("rejection", report)


if __name__ == "__main__":
    unittest.main()
