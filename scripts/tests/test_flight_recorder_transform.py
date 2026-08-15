"""Tests for the pure Flight Recorder event-safety transform."""

from dataclasses import FrozenInstanceError, asdict
import importlib.util
from pathlib import Path
import sys
import unittest


REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "images" / "iceberg-log-spark" / "flight_recorder.py"
SPEC = importlib.util.spec_from_file_location("flight_recorder_transform", SOURCE)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class FlightRecorderTransformTests(unittest.TestCase):
    window = "1786708500123456000-1786708800123456000"

    def entry(self, *, line: str = "service started", **labels: str) -> dict[str, object]:
        return {
            "timestamp": "1786708800123456789",
            "labels": {
                "k8s_namespace_name": "airflow",
                "k8s_deployment_name": "scheduler",
                "k8s_job_name": "ignored-job",
                "k8s_pod_name": "scheduler-1",
                "k8s_container_name": "scheduler",
                "severity": "WARNING",
                "arbitrary_secret_label": "must-not-survive",
                **labels,
            },
            "line": line,
        }

    def transform(self, entry: object | None = None):
        return MODULE.transform_entry(entry or self.entry(), source_window_id=self.window)

    def test_safe_event_has_exact_allowlisted_immutable_schema(self) -> None:
        event = self.transform(self.entry(line="password=hunter2 completed"))
        self.assertEqual("2026-08-14T12:00:00.123456789Z", event.event_timestamp)
        self.assertEqual("2026-08-14", event.event_date)
        self.assertEqual(("airflow", "deployment", "scheduler"), (
            event.namespace, event.workload_kind, event.workload_name,
        ))
        self.assertEqual(("scheduler-1", "scheduler", "warn"), (
            event.pod_name, event.container_name, event.severity,
        ))
        self.assertEqual("password=[REDACTED]", event.redacted_preview)
        self.assertFalse(event.rejected)
        self.assertEqual(64, len(event.fingerprint))
        output = asdict(event)
        self.assertNotIn("line", output)
        self.assertNotIn("labels", output)
        self.assertNotIn("must-not-survive", str(output))
        with self.assertRaises(FrozenInstanceError):
            event.namespace = "changed"

    def test_fingerprint_uses_only_canonical_identity_and_original_line(self) -> None:
        entry = self.entry(line="same")
        first = self.transform(entry)
        reordered = dict(reversed(list(entry["labels"].items())))
        entry["labels"] = {**reordered, "another_dropped_label": "value"}
        self.assertEqual(first.fingerprint, self.transform(entry).fingerprint)
        changed_line = self.transform(self.entry(line="different"))
        changed_window = MODULE.transform_entry(self.entry(line="same"), source_window_id="other-window")
        self.assertNotEqual(first.fingerprint, changed_line.fingerprint)
        self.assertNotEqual(first.fingerprint, changed_window.fingerprint)

    def test_supported_workload_labels_and_severity_values_are_normalized(self) -> None:
        workloads = ("deployment", "statefulset", "daemonset", "job", "cronjob")
        for workload in workloads:
            labels = {f"k8s_{workload}_name": f"{workload}-name", "severity": "critical"}
            entry = self.entry()
            for candidate in workloads:
                entry["labels"].pop(f"k8s_{candidate}_name", None)
            entry["labels"].update(labels)
            with self.subTest(workload=workload):
                event = self.transform(entry)
                self.assertEqual((workload, f"{workload}-name", "fatal"), (
                    event.workload_kind, event.workload_name, event.severity,
                ))
        for source, expected in (("trace", "trace"), ("DEBUG", "debug"), ("notice", "info"),
                                 ("warning", "warn"), ("err", "error"), ("other", "unknown")):
            with self.subTest(severity=source):
                self.assertEqual(expected, self.transform(self.entry(severity=source)).severity)

    def test_secret_forms_are_redacted_before_preview_is_limited(self) -> None:
        cases = (
            ('{"Password":"swordfish"}', "swordfish"),
            ("api_key=sample-api-value", "sample-api-value"),
            ("code=7 count=10 method=GET status=running credential=summer2026", "summer2026"),
            ("status=AKIAABCDEFGHIJKLMNOP", "AKIAABCDEFGHIJKLMNOP"),
            ("code=eyJheader00.payload00.signature00", "eyJheader00.payload00.signature00"),
            ("method=https://user:pass@example.test/path", "user:pass"),
            ("cookie=session-value", "session-value"),
            ("Authorization: Token abc123", "abc123"),
            ("secret is hunter2", "hunter2"),
            ("AWS_SECRET_ACCESS_KEY=value", "value"),)
        for line, secret in cases:
            with self.subTest(line=line):
                preview = self.transform(self.entry(line=line)).redacted_preview
                self.assertIn("[REDACTED]", preview)
                self.assertNotIn(secret, preview)
                if line.startswith("code=7"): self.assertTrue(preview.startswith("code=7 count=10 method=GET status=running "))
        self.assertEqual(256, len(self.transform(self.entry(line=" ".join(["status=200"] * 100))).redacted_preview))

    def test_unsafe_lines_keep_safe_metadata_without_a_preview(self) -> None:
        cases = (
            ("x" * (MODULE.MAX_LINE_BYTES + 1), "line_exceeds_16_kib"),
            ("safe\x00unsafe", "disallowed_control_character"),
            ("-----BEGIN PRIVATE KEY-----\nmaterial", "private_key_marker"),
            ('credential="unterminated secret', "redaction_failed"),)
        for line, reason in cases:
            with self.subTest(reason=reason):
                event = self.transform(self.entry(line=line))
                self.assertTrue(event.rejected)
                self.assertIsNone(event.redacted_preview)
                self.assertEqual(reason, event.rejection_reason)
                self.assertEqual(("airflow", self.window), (event.namespace, event.source_window_id))
                self.assertEqual(64, len(event.fingerprint))

    def test_malformed_entries_and_timestamps_fail_closed(self) -> None:
        cases = (
            None,
            {**self.entry(), "extra": "field"},
            {**self.entry(), "timestamp": 1},
            {**self.entry(), "timestamp": "not-nanoseconds"},
            {**self.entry(), "timestamp": "9" * 21},
            {**self.entry(), "labels": {"severity": 1}},
            {**self.entry(), "line": 1},
        )
        for entry in cases:
            with self.subTest(entry=entry), self.assertRaises(MODULE.FlightRecorderTransformError):
                MODULE.transform_entry(entry, source_window_id=self.window)
        with self.assertRaises(MODULE.FlightRecorderTransformError):
            MODULE.transform_entry(self.entry(), source_window_id="../unsafe")

    def test_commit_order_keeps_receipt_last_and_stops_on_failure(self) -> None:
        order = []
        action = lambda name: lambda: order.append(name)
        MODULE.commit_in_order(action("events"), action("hourly"), action("run_receipts"))
        self.assertEqual(["events", "hourly", "run_receipts"], order)

        def fail_hourly() -> None:
            order.append("hourly-failed")
            raise RuntimeError("expected")

        order.clear()
        with self.assertRaises(RuntimeError):
            MODULE.commit_in_order(action("events"), fail_hourly, action("run_receipts"))
        self.assertEqual(["events", "hourly-failed"], order)

    def test_replay_requires_one_matching_receipt_and_final_count(self) -> None:
        checksum = "a" * 64
        receipt = {"source_window_id": self.window, "raw_sha256": checksum, "final_event_count": 7}
        self.assertFalse(MODULE.replay_is_complete([], source_window_id=self.window, raw_sha256=checksum, final_event_count=0))
        self.assertTrue(MODULE.replay_is_complete([receipt], source_window_id=self.window, raw_sha256=checksum, final_event_count=7))
        for changed in ({**receipt, "raw_sha256": "b" * 64}, {**receipt, "final_event_count": 8}):
            with self.subTest(changed=changed), self.assertRaises(MODULE.FlightRecorderTransformError):
                MODULE.replay_is_complete([changed], source_window_id=self.window, raw_sha256=checksum, final_event_count=7)

    def test_runtime_contract_has_exact_sources_tables_and_partitions(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn('os.getenv("AWS_ACCESS_KEY_ID")', source)
        self.assertIn('.config("spark.redaction.regex", SPARK_REDACTION_REGEX)', source)
        self.assertIn('.config(f"spark.sql.catalog.{CATALOG}.credential", credential)', source)
        self.assertIn('.config("spark.redaction.string.regex", re.escape(credential))', source)
        for key in ("secret", "password", "token", "access_key", "credential", "spark.redaction.regex", "spark.redaction.string.regex"):
            self.assertRegex(key, MODULE.SPARK_REDACTION_REGEX)
        env = {
            "ANTON_LAKEHOUSE_TARGET": "authoritative",
            "FLIGHT_RECORDER_ICEBERG_NAMESPACE": "flight_recorder",
            "ICEBERG_WAREHOUSE": "s3://iceberg-warehouse",
            "FLIGHT_RECORDER_RAW_URI": "s3a://iceberg-raw/flight-recorder/raw/source.jsonl",
            "FLIGHT_RECORDER_MANIFEST_URI": "s3a://iceberg-raw/flight-recorder/manifests/source.json",
            "FLIGHT_RECORDER_RAW_SHA256": "a" * 64,
            "FLIGHT_RECORDER_SOURCE_WINDOW_ID": self.window,
            "ANTON_SPARK_ATTEMPT": "attempt-1",
        }
        config = MODULE.RuntimeConfig.from_environment(env)
        self.assertEqual(("attempt-1", self.window), (config.spark_attempt, config.source_window_id))
        self.assertIn("fingerprint string", MODULE.EVENT_SCHEMA_DDL)
        self.assertNotIn(" line ", MODULE.EVENT_SCHEMA_DDL)
        self.assertNotIn("labels", MODULE.EVENT_SCHEMA_DDL)
        self.assertEqual(
            (
                ("lake.flight_recorder.events", "event_date", "s3://iceberg-warehouse/flight_recorder/events"),
                ("lake.flight_recorder.hourly", "days(hour)", "s3://iceberg-warehouse/flight_recorder/hourly"),
                ("lake.flight_recorder.run_receipts", "completion_date", "s3://iceberg-warehouse/flight_recorder/run_receipts"),
            ),
            tuple((table, partition, location) for table, _, partition, location in MODULE._TABLES),
        )
        with self.assertRaises(MODULE.FlightRecorderTransformError):
            MODULE.RuntimeConfig.from_environment({**env, "ANTON_LAKEHOUSE_TARGET": "shadow"})


if __name__ == "__main__":
    unittest.main()
