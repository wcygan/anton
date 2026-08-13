"""Tests for the fail-closed five-run Airflow shadow gate."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[2]
LIB = REPO / "scripts" / "lib"
import sys

sys.path.insert(0, str(LIB))

from airflow_shadow_gate import (  # noqa: E402
    SPARK_API_VERSION,
    evaluate_shadow_gate,
    expected_spark_image_digest,
    load_shadow_gate,
)


def passed_run(index: int, digest: str) -> dict:
    return {
        "run_id": f"scheduled__2026-08-12T00:{index:02d}:00Z",
        "workflow_run": f"scheduled__2026-08-12T00:{index:02d}:00Z",
        "observed_at": f"2026-08-12T00:{index:02d}:00Z",
        "status": "passed",
        "target": "shadow",
        "spark": {
            "image_digest": digest,
            "api_version": SPARK_API_VERSION,
            "kind": "SparkApplication",
            "attempt_name": f"lh-fixture-run-{index:02d}-a1",
        },
        "trino": {
            "schema": True,
            "counts": True,
            "partitions": True,
            "snapshots": True,
            "locations": True,
            "time_travel": True,
            "write_denial_authoritative": True,
            "write_denial_shadow": True,
            "normalized_count": 5,
            "hourly_count": 5,
            "hourly_event_count_sum": 5,
        },
        "authoritative_unchanged": True,
        "kubernetes": {
            "version": "1.36",
            "task_pods": True,
            "custom_resource_observation": True,
            "spark_workloads": True,
        },
        "runtime_evidence": {
            "runtime_identity": True,
            "classpath": True,
            "s3fileio": True,
            "s3a": True,
            "loki": True,
            "history_server": True,
        },
        "evidence": {
            "workflow_run": f"evidence/run-{index}/workflow.json",
            "spark_application": f"evidence/run-{index}/spark-application.json",
            "trino": f"evidence/run-{index}/trino.json",
            "authoritative_state": f"evidence/run-{index}/authoritative.json",
            "runtime": f"evidence/run-{index}/runtime.json",
            "loki": f"evidence/run-{index}/loki.json",
            "history_server": f"evidence/run-{index}/history.json",
            "kubernetes": f"evidence/run-{index}/kubernetes.json",
        },
        "compatibility": {"fallback_used": False},
    }


def ledger(runs: list[dict]) -> dict:
    digest = expected_spark_image_digest(REPO / "images/airflow-runtime/dags/airflow_spark_lakehouse.py")
    return {
        "schema_version": 1,
        "candidate": {
            "source_revision": "5c2967c5",
            "airflow_image_digest": "sha256:" + "a" * 64,
            "spark_image_digest": digest,
            "spark_api_version": SPARK_API_VERSION,
        },
        "runs": runs,
    }


def write_artifacts(root: Path, value: dict) -> None:
    for run in value["runs"]:
        if run["status"] != "passed":
            continue
        run_id = run["run_id"]
        details = {
            "workflow_run": {"dag_id": "airflow_spark_lakehouse", "status": "success"},
            "spark_application": {
                "kind": "SparkApplication",
                "api_version": SPARK_API_VERSION,
                "image_digest": run["spark"]["image_digest"],
                "attempt_name": run["spark"]["attempt_name"],
                "state": "COMPLETED",
            },
            "trino": {
                "normalized_count": 5,
                "hourly_count": 5,
                "hourly_event_count_sum": 5,
                "write_denial_authoritative": True,
                "write_denial_shadow": True,
            },
            "authoritative_state": {"before": {"snapshot": 12}, "after": {"snapshot": 12}},
            "runtime": {
                "spark_version": "4.1.3",
                "scala_version": "2.13",
                "java_version": "21",
                "python_version": "3.12",
                "hadoop_version": "3.4.2",
                "iceberg_version": "1.11.0",
            },
            "kubernetes": {
                "version": "1.36",
                "task_pods": True,
                "custom_resource_observation": True,
                "spark_workloads": True,
            },
            "loki": {"unique_markers": [run_id], "containers_exited": True},
            "history_server": {"application_id": f"app-{run_id}", "event_log_source": "seaweedfs"},
        }
        for artifact, relative in run["evidence"].items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "run_id": run_id,
                        "artifact": artifact,
                        "passed": True,
                        "observed_at": run["observed_at"],
                        "source": {
                            "command": f"collect {artifact} for {run_id}",
                            "result": {"retained": True},
                        },
                        "details": details[artifact],
                    }
                ),
                encoding="utf-8",
            )


class AirflowShadowGateTests(unittest.TestCase):
    def evaluate(self, value: dict, directory: str):
        write_artifacts(Path(directory), value)
        return evaluate_shadow_gate(
            value,
            expected_digest=value["candidate"]["spark_image_digest"],
            evidence_root=Path(directory),
        )

    def test_five_valid_runs_are_eligible(self) -> None:
        value = ledger([passed_run(index, expected_spark_image_digest(REPO / "images/airflow-runtime/dags/airflow_spark_lakehouse.py")) for index in range(1, 6)])
        with tempfile.TemporaryDirectory() as directory:
            write_artifacts(Path(directory), value)
            result = evaluate_shadow_gate(value, expected_digest=value["candidate"]["spark_image_digest"], evidence_root=Path(directory))
        self.assertTrue(result["eligible"])
        self.assertEqual(result["consecutive_passes"], 5)

    def test_assertions_without_source_output_are_rejected(self) -> None:
        digest = expected_spark_image_digest(REPO / "images/airflow-runtime/dags/airflow_spark_lakehouse.py")
        value = ledger([passed_run(index, digest) for index in range(1, 6)])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_artifacts(root, value)
            path = root / value["runs"][-1]["evidence"]["trino"]
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload.pop("source")
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = evaluate_shadow_gate(value, expected_digest=digest, evidence_root=root)
        self.assertFalse(result["eligible"])
        self.assertIn("source must be an object", result["errors"][0])

    def test_one_run_cannot_bypass_the_five_run_requirement(self) -> None:
        value = ledger([passed_run(1, expected_spark_image_digest(REPO / "images/airflow-runtime/dags/airflow_spark_lakehouse.py"))])
        with tempfile.TemporaryDirectory() as directory:
            result = self.evaluate(value, directory)
        self.assertFalse(result["eligible"])
        self.assertEqual(result["required_runs"], 5)

    def test_invalid_run_resets_then_five_valid_runs_can_recover(self) -> None:
        digest = expected_spark_image_digest(REPO / "images/airflow-runtime/dags/airflow_spark_lakehouse.py")
        invalid = passed_run(1, digest)
        invalid["evidence"]["trino"] = "evidence/missing.json"
        value = ledger([invalid] + [passed_run(index, digest) for index in range(2, 7)])
        with tempfile.TemporaryDirectory() as directory:
            write_artifacts(Path(directory), value)
            (Path(directory) / "evidence" / "missing.json").unlink()
            result = evaluate_shadow_gate(value, expected_digest=digest, evidence_root=Path(directory))
        self.assertTrue(result["eligible"])
        self.assertEqual(result["consecutive_passes"], 5)

    def test_failure_resets_consecutive_suffix(self) -> None:
        digest = expected_spark_image_digest(REPO / "images/airflow-runtime/dags/airflow_spark_lakehouse.py")
        failed = {
            "run_id": "scheduled__failure",
            "observed_at": "2026-08-12T00:03:30Z",
            "status": "failed",
            "failure_reason": "bounded test failure",
            "failure_evidence": "evidence/failure.json",
        }
        value = ledger([passed_run(index, digest) for index in range(1, 4)] + [failed] + [passed_run(index, digest) for index in range(4, 8)])
        with tempfile.TemporaryDirectory() as directory:
            write_artifacts(Path(directory), value)
            result = evaluate_shadow_gate(value, expected_digest=digest, evidence_root=Path(directory))
        self.assertFalse(result["eligible"])
        self.assertEqual(result["consecutive_passes"], 4)
        self.assertIn("only 4 consecutive passed runs", result["errors"][0])

    def test_digest_mismatch_blocks_the_gate(self) -> None:
        digest = expected_spark_image_digest(REPO / "images/airflow-runtime/dags/airflow_spark_lakehouse.py")
        value = ledger([passed_run(index, digest) for index in range(1, 6)])
        value["runs"][4]["spark"]["image_digest"] = "sha256:" + "b" * 64
        with tempfile.TemporaryDirectory() as directory:
            write_artifacts(Path(directory), value)
            result = evaluate_shadow_gate(value, expected_digest=digest, evidence_root=Path(directory))
        self.assertFalse(result["eligible"])
        self.assertTrue(any("image_digest" in error for error in result["errors"]))

    def test_missing_trino_check_blocks_the_gate(self) -> None:
        digest = expected_spark_image_digest(REPO / "images/airflow-runtime/dags/airflow_spark_lakehouse.py")
        value = ledger([passed_run(index, digest) for index in range(1, 6)])
        del value["runs"][4]["trino"]["time_travel"]
        with tempfile.TemporaryDirectory() as directory:
            write_artifacts(Path(directory), value)
            result = evaluate_shadow_gate(value, expected_digest=digest, evidence_root=Path(directory))
        self.assertFalse(result["eligible"])
        self.assertTrue(any("trino.time_travel" in error for error in result["errors"]))

    def test_missing_artifact_file_blocks_the_gate(self) -> None:
        digest = expected_spark_image_digest(REPO / "images/airflow-runtime/dags/airflow_spark_lakehouse.py")
        value = ledger([passed_run(index, digest) for index in range(1, 6)])
        value["runs"][4]["evidence"]["loki"] = "evidence/run-5/missing.json"
        with tempfile.TemporaryDirectory() as directory:
            write_artifacts(Path(directory), value)
            (Path(directory) / "evidence" / "run-5" / "missing.json").unlink()
            result = evaluate_shadow_gate(value, expected_digest=digest, evidence_root=Path(directory))
        self.assertFalse(result["eligible"])
        self.assertTrue(any("does not identify a retained file" in error for error in result["errors"]))

    def test_duplicate_workflow_run_blocks_the_gate(self) -> None:
        digest = expected_spark_image_digest(REPO / "images/airflow-runtime/dags/airflow_spark_lakehouse.py")
        value = ledger([passed_run(index, digest) for index in range(1, 6)])
        value["runs"][4]["workflow_run"] = value["runs"][0]["workflow_run"]
        with tempfile.TemporaryDirectory() as directory:
            result = self.evaluate(value, directory)
        self.assertFalse(result["eligible"])
        self.assertTrue(any("workflow_run is duplicated" in error for error in result["errors"]))

    def test_fallback_requires_the_compatibility_ladder(self) -> None:
        digest = expected_spark_image_digest(REPO / "images/airflow-runtime/dags/airflow_spark_lakehouse.py")
        value = ledger([passed_run(index, digest) for index in range(1, 6)])
        value["runs"][4]["compatibility"] = {"fallback_used": True}
        with tempfile.TemporaryDirectory() as directory:
            write_artifacts(Path(directory), value)
            result = evaluate_shadow_gate(value, expected_digest=digest, evidence_root=Path(directory))
        self.assertFalse(result["eligible"])
        self.assertTrue(any("compatibility.ladder" in error for error in result["errors"]))

    def test_file_reader_matches_mapping_reader(self) -> None:
        digest = expected_spark_image_digest(REPO / "images/airflow-runtime/dags/airflow_spark_lakehouse.py")
        value = ledger([passed_run(index, digest) for index in range(1, 6)])
        with tempfile.TemporaryDirectory() as directory:
            write_artifacts(Path(directory), value)
            path = Path(directory) / "shadow-gate.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            loaded = load_shadow_gate(path)
        self.assertEqual(loaded, value)


if __name__ == "__main__":
    unittest.main()
