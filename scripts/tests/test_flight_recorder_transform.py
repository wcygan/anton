"""Tests for the pure Flight Recorder event-safety transform."""

from dataclasses import FrozenInstanceError, asdict
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[2]
CONTRACT_SOURCE = REPO / "images" / "flight-recorder-contract"
sys.path.insert(0, str(CONTRACT_SOURCE))

import anton_flight_recorder_contract as COMPLETE_HOUR_CONTRACT

SOURCE = REPO / "images" / "iceberg-log-spark" / "flight_recorder.py"
SPEC = importlib.util.spec_from_file_location("flight_recorder_transform", SOURCE)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

AIRFLOW_SOURCE = REPO / "images" / "airflow-runtime" / "src" / "anton_airflow" / "loki.py"
AIRFLOW_SPEC = importlib.util.spec_from_file_location("airflow_loki_contract", AIRFLOW_SOURCE)
assert AIRFLOW_SPEC and AIRFLOW_SPEC.loader
AIRFLOW_LOKI = importlib.util.module_from_spec(AIRFLOW_SPEC)
sys.modules[AIRFLOW_SPEC.name] = AIRFLOW_LOKI
AIRFLOW_SPEC.loader.exec_module(AIRFLOW_LOKI)


class FlightRecorderTransformTests(unittest.TestCase):
    window = "1786708500123456000-1786708800123457000"

    def test_complete_hour_contract_has_stable_golden_identity(self) -> None:
        start_ns = 1786705200000000000
        end_ns = 1786705500000000000
        component, query = COMPLETE_HOUR_CONTRACT.COMPONENT_QUERIES[0]
        self.assertEqual(
            "49275e31505c9300829cb0ca6fd86a198f6ee31c4b628695ba7ab555f4e930fd",
            COMPLETE_HOUR_CONTRACT.component_catalog_sha256(),
        )
        self.assertEqual(
            ("flight_recorder_complete_hour", "complete", 64 * 1024),
            (
                COMPLETE_HOUR_CONTRACT.COMPLETE_HOUR_KIND,
                COMPLETE_HOUR_CONTRACT.COMPLETE_HOUR_STATUS,
                COMPLETE_HOUR_CONTRACT.MAX_SOURCE_MANIFEST_BYTES,
            ),
        )
        self.assertEqual(
            (
                "flight-recorder/component-manifests/"
                "1786705200000000000-1786705500000000000/"
                "40ef1552da3bc8073da64184ae03426d3c0276b0ea23fc9dd5cf6f763d2ad637.json"
            ),
            COMPLETE_HOUR_CONTRACT.component_manifest_key(
                component=component,
                query=query,
                start_ns=start_ns,
                end_ns=end_ns,
            ),
        )

    def test_complete_hour_contract_encodes_stable_golden_wire(self) -> None:
        manifest, _, _ = self.complete_hour()
        payload = COMPLETE_HOUR_CONTRACT.encode_complete_hour_manifest(manifest)
        self.assertEqual(
            "03150e1a099fec3d4092464ceffa10689d4bdfaad0bda8f085d47724f3d46107",
            hashlib.sha256(payload).hexdigest(),
        )

    def test_complete_hour_contract_decodes_only_canonical_wire(self) -> None:
        manifest, payload, _ = self.complete_hour()

        self.assertEqual(
            manifest,
            COMPLETE_HOUR_CONTRACT.decode_complete_hour_manifest(payload),
        )

        noncanonical = json.dumps(manifest).encode()
        with self.assertRaisesRegex(ValueError, "canonical"):
            COMPLETE_HOUR_CONTRACT.decode_complete_hour_manifest(noncanonical)

    def test_complete_hour_contract_rejects_unknown_wire_fields(self) -> None:
        manifest, _, _ = self.complete_hour()
        cases = (
            {**manifest, "unexpected": True},
            {
                **manifest,
                "sources": [{**manifest["sources"][0], "unexpected": True}, *manifest["sources"][1:]],
            },
        )
        for changed in cases:
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                COMPLETE_HOUR_CONTRACT.encode_complete_hour_manifest(changed)

    def test_complete_hour_contract_rejects_invalid_wire_semantics(self) -> None:
        manifest, _, _ = self.complete_hour()

        def changed_source(**changes: object) -> dict[str, object]:
            return {
                **manifest,
                "sources": [{**manifest["sources"][0], **changes}, *manifest["sources"][1:]],
            }

        cases = (
            {**manifest, "schema_version": 99},
            {**manifest, "hour_end": manifest["hour_start"]},
            changed_source(component="trino"),
            changed_source(chunk_index=False),
            changed_source(window_end=manifest["sources"][0]["window_start"]),
            changed_source(entry_limit=4999),
            changed_source(manifest_key="flight-recorder/component-manifests/wrong.json"),
            changed_source(raw_sha256="A" * 64),
            changed_source(raw_key="flight-recorder/raw/wrong.jsonl"),
            {**manifest, "source_count": 49},
            {**manifest, "raw_bytes": 481},
        )
        for index, changed in enumerate(cases):
            with self.subTest(case=index), self.assertRaises(ValueError):
                COMPLETE_HOUR_CONTRACT.encode_complete_hour_manifest(changed)

    def test_complete_hour_contract_rejects_invalid_component_identity(self) -> None:
        base = {
            "component": "workflow",
            "query": '{k8s_namespace_name="airflow"}',
            "start_ns": 1786705200000000000,
            "end_ns": 1786705500000000000,
        }
        cases = (
            {**base, "component": "../workflow"},
            {**base, "query": ""},
            {**base, "end_ns": base["start_ns"]},
        )
        for index, changed in enumerate(cases):
            with self.subTest(case=index), self.assertRaises(ValueError):
                COMPLETE_HOUR_CONTRACT.component_manifest_key(**changed)

    def test_complete_hour_contract_derives_stable_object_keys(self) -> None:
        checksum = "a" * 64
        self.assertEqual(
            (
                "flight-recorder/raw/1786705200000000000-1786705500000000000/"
                f"{checksum}.jsonl"
            ),
            COMPLETE_HOUR_CONTRACT.raw_key(
                start_ns=1786705200000000000,
                end_ns=1786705500000000000,
                checksum=checksum,
            ),
        )
        self.assertEqual(
            (
                "flight-recorder/hours/1786705200000000000-1786708800000000000/"
                f"{checksum}.complete.json"
            ),
            COMPLETE_HOUR_CONTRACT.hour_manifest_key(
                start_ns=1786705200000000000,
                end_ns=1786708800000000000,
                checksum=checksum,
            ),
        )

    def test_complete_hour_contract_exports_exact_source_fields(self) -> None:
        self.assertEqual(
            frozenset({
                "schema_version",
                "query",
                "window_start",
                "window_end",
                "entry_count",
                "raw_bytes",
                "raw_key",
                "raw_sha256",
            }),
            COMPLETE_HOUR_CONTRACT.SOURCE_MANIFEST_FIELDS,
        )

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

    def runtime_env(self, checksum: str = "a" * 64) -> dict[str, str]:
        query_sha = hashlib.sha256(b'{k8s_namespace_name="airflow"}').hexdigest()
        return {
            "ANTON_LAKEHOUSE_TARGET": "authoritative",
            "FLIGHT_RECORDER_ICEBERG_NAMESPACE": "flight_recorder",
            "ICEBERG_WAREHOUSE": "s3://iceberg-warehouse",
            "FLIGHT_RECORDER_RAW_URI": f"s3a://iceberg-raw/flight-recorder/raw/{self.window}/{checksum}.jsonl",
            "FLIGHT_RECORDER_MANIFEST_URI": f"s3a://iceberg-raw/flight-recorder/manifests/{self.window}/{query_sha}.json",
            "FLIGHT_RECORDER_RAW_SHA256": checksum,
            "FLIGHT_RECORDER_SOURCE_WINDOW_ID": self.window,
            "ANTON_SPARK_ATTEMPT": "attempt-1",
        }

    def complete_hour(self):
        start_ns, end_ns = 1786705200000000000, 1786708800000000000
        sources = []
        for component, query in MODULE.COMPONENT_QUERIES:
            for index in range(12):
                chunk_start = start_ns + index * 300_000_000_000
                chunk_end = chunk_start + 300_000_000_000
                checksum = hashlib.sha256(f"{component}-{index}".encode()).hexdigest()
                sources.append({
                    "component": component,
                    "chunk_index": index,
                    "entry_limit": MODULE.ENTRY_LIMIT,
                    "max_response_bytes": MODULE.MAX_RESPONSE_BYTES,
                    "timeout_seconds": MODULE.TIMEOUT_SECONDS,
                    "manifest_key": MODULE.component_manifest_key(
                        component, query, chunk_start, chunk_end,
                    ),
                    "manifest_sha256": "b" * 64,
                    "query": query,
                    "window_start": MODULE._datetime_ns(str(chunk_start)).isoformat().replace("+00:00", "Z"),
                    "window_end": MODULE._datetime_ns(str(chunk_end)).isoformat().replace("+00:00", "Z"),
                    "entry_count": 1,
                    "raw_bytes": 10,
                    "raw_key": f"flight-recorder/raw/{chunk_start}-{chunk_end}/{checksum}.jsonl",
                    "raw_sha256": checksum,
                })
        manifest = {
            "schema_version": MODULE.COMPLETE_HOUR_SCHEMA_VERSION,
            "kind": "flight_recorder_complete_hour",
            "status": "complete",
            "hour_start": MODULE._datetime_ns(str(start_ns)).isoformat().replace("+00:00", "Z"),
            "hour_end": MODULE._datetime_ns(str(end_ns)).isoformat().replace("+00:00", "Z"),
            "source_hour_id": f"{start_ns}-{end_ns}",
            "catalog_sha256": MODULE.component_catalog_sha256(),
            "component_count": 4,
            "chunk_count": 48,
            "source_count": 48,
            "raw_bytes": 480,
            "sources": sources,
        }
        payload = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
        checksum = hashlib.sha256(payload).hexdigest()
        env = {
            "ANTON_LAKEHOUSE_TARGET": "authoritative",
            "FLIGHT_RECORDER_ICEBERG_NAMESPACE": "flight_recorder",
            "ICEBERG_WAREHOUSE": "s3://iceberg-warehouse",
            "FLIGHT_RECORDER_COMPLETE_MANIFEST_URI": (
                f"s3a://iceberg-raw/flight-recorder/hours/{start_ns}-{end_ns}/{checksum}.complete.json"
            ),
            "FLIGHT_RECORDER_COMPLETE_MANIFEST_SHA256": checksum,
            "FLIGHT_RECORDER_SOURCE_HOUR_ID": f"{start_ns}-{end_ns}",
            "ANTON_SPARK_ATTEMPT": "attempt-hour-1",
        }
        return manifest, payload, env

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

        order.clear()
        MODULE.commit_hour_in_order(
            action("events"), action("hourly"), action("component_counts"), action("run_receipts")
        )
        self.assertEqual(["events", "hourly", "component_counts", "run_receipts"], order)

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
        env = self.runtime_env()
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
                ("lake.flight_recorder.component_counts", "completion_date", "s3://iceberg-warehouse/flight_recorder/component_counts"),
            ),
            tuple((table, partition, location) for table, _, partition, location in MODULE._TABLES),
        )
        with self.assertRaises(MODULE.FlightRecorderTransformError):
            MODULE.RuntimeConfig.from_environment({**env, "ANTON_LAKEHOUSE_TARGET": "shadow"})

        manifest, _, hour_env = self.complete_hour()
        hour_config = MODULE.HourlyRuntimeConfig.from_environment(hour_env)
        self.assertEqual(manifest["source_hour_id"], hour_config.source_hour_id)
        with self.assertRaises(MODULE.FlightRecorderTransformError):
            MODULE.HourlyRuntimeConfig.from_environment({**hour_env, **env})

    def test_airflow_capture_round_trips_through_spark_validation(self) -> None:
        class MemoryStore:
            def __init__(self) -> None:
                self.objects: dict[str, bytes] = {}

            def get(self, *, key: str) -> bytes | None:
                return self.objects.get(key)

            def put_if_absent(self, *, key: str, payload: bytes) -> bool:
                if key in self.objects:
                    return False
                self.objects[key] = payload
                return True

        class HourClient:
            def query_range(self, *, window, query, **_: object):
                return (
                    AIRFLOW_LOKI.LokiEntry(
                        str(window.start_ns),
                        {"component": query},
                        "line",
                    ),
                )

        hour = AIRFLOW_LOKI.LokiHour.ending_at(
            datetime(2026, 8, 14, 12, tzinfo=timezone.utc),
        )
        store = MemoryStore()
        manifest = AIRFLOW_LOKI.LokiSnapshotExtractor(
            client=HourClient(),  # type: ignore[arg-type]
            store=store,
        ).capture_hour(hour=hour)
        key = AIRFLOW_LOKI.hour_manifest_key(
            hour=hour,
            checksum=manifest.manifest_sha256,
        )
        payload = store.objects[key]
        config = MODULE.HourlyRuntimeConfig.from_environment({
            "ANTON_LAKEHOUSE_TARGET": "authoritative",
            "FLIGHT_RECORDER_ICEBERG_NAMESPACE": "flight_recorder",
            "ICEBERG_WAREHOUSE": "s3://iceberg-warehouse",
            "FLIGHT_RECORDER_COMPLETE_MANIFEST_URI": f"s3a://iceberg-raw/{key}",
            "FLIGHT_RECORDER_COMPLETE_MANIFEST_SHA256": manifest.manifest_sha256,
            "FLIGHT_RECORDER_SOURCE_HOUR_ID": manifest.source_hour_id,
            "ANTON_SPARK_ATTEMPT": "attempt-hour-round-trip",
        })

        sources = MODULE.validate_complete_hour_manifest(config, payload)

        self.assertEqual(48, len(sources))
        self.assertEqual(manifest.manifest_sha256, hashlib.sha256(payload).hexdigest())
        self.assertEqual(
            tuple(component for component, _ in MODULE.COMPONENT_QUERIES for _ in range(12)),
            tuple(source["component"] for source in sources),
        )

    def test_complete_hour_manifest_requires_exact_ordered_48_source_matrix(self) -> None:
        manifest, payload, env = self.complete_hour()
        config = MODULE.HourlyRuntimeConfig.from_environment(env)
        sources = MODULE.validate_complete_hour_manifest(config, payload)
        self.assertEqual(48, len(sources))
        self.assertEqual(
            tuple(component for component, _ in MODULE.COMPONENT_QUERIES for _ in range(12)),
            tuple(item["component"] for item in sources),
        )
        cases = (
            {**manifest, "sources": manifest["sources"][:-1], "chunk_count": 47},
            {**manifest, "sources": [*manifest["sources"], manifest["sources"][0]], "chunk_count": 49},
            {**manifest, "sources": [
                {**manifest["sources"][0], "query": "{unknown=\"query\"}"},
                *manifest["sources"][1:],
            ]},
            {**manifest, "sources": [manifest["sources"][1], manifest["sources"][0], *manifest["sources"][2:]]},
        )
        for changed in cases:
            changed_payload = (json.dumps(changed, sort_keys=True, separators=(",", ":")) + "\n").encode()
            changed_checksum = hashlib.sha256(changed_payload).hexdigest()
            changed_env = {
                **env,
                "FLIGHT_RECORDER_COMPLETE_MANIFEST_SHA256": changed_checksum,
                "FLIGHT_RECORDER_COMPLETE_MANIFEST_URI": env["FLIGHT_RECORDER_COMPLETE_MANIFEST_URI"].replace(
                    env["FLIGHT_RECORDER_COMPLETE_MANIFEST_SHA256"], changed_checksum,
                ),
            }
            with self.subTest(changed=changed), self.assertRaises(MODULE.FlightRecorderTransformError):
                MODULE.validate_complete_hour_manifest(
                    MODULE.HourlyRuntimeConfig.from_environment(changed_env), changed_payload,
                )

    def test_complete_hour_manifest_uses_shared_canonical_decoder(self) -> None:
        _, payload, env = self.complete_hour()
        config = MODULE.HourlyRuntimeConfig.from_environment(env)

        with patch.object(
            COMPLETE_HOUR_CONTRACT,
            "decode_complete_hour_manifest",
            wraps=COMPLETE_HOUR_CONTRACT.decode_complete_hour_manifest,
        ) as decoder:
            MODULE.validate_complete_hour_manifest(config, payload)

        decoder.assert_called_once_with(payload)

        noncanonical = json.dumps(json.loads(payload)).encode()
        checksum = hashlib.sha256(noncanonical).hexdigest()
        changed_env = {
            **env,
            "FLIGHT_RECORDER_COMPLETE_MANIFEST_SHA256": checksum,
            "FLIGHT_RECORDER_COMPLETE_MANIFEST_URI": (
                f"s3a://iceberg-raw/flight-recorder/hours/{env['FLIGHT_RECORDER_SOURCE_HOUR_ID']}/"
                f"{checksum}.complete.json"
            ),
        }
        with self.assertRaisesRegex(MODULE.FlightRecorderTransformError, "canonical"):
            MODULE.validate_complete_hour_manifest(
                MODULE.HourlyRuntimeConfig.from_environment(changed_env),
                noncanonical,
            )

    def test_complete_hour_manifest_rejects_boolean_parent_counter(self) -> None:
        manifest, _, env = self.complete_hour()
        empty_checksum = hashlib.sha256(b"").hexdigest()
        sources = [manifest["sources"][0]]
        for retained in manifest["sources"][1:]:
            window_id = retained["raw_key"].split("/", 3)[2]
            sources.append({
                **retained,
                "entry_count": 0,
                "raw_bytes": 0,
                "raw_key": f"flight-recorder/raw/{window_id}/{empty_checksum}.jsonl",
                "raw_sha256": empty_checksum,
            })
        changed = {
            **manifest,
            "source_count": True,
            "raw_bytes": 10,
            "sources": sources,
        }
        payload = (json.dumps(changed, sort_keys=True, separators=(",", ":")) + "\n").encode()
        checksum = hashlib.sha256(payload).hexdigest()
        changed_env = {
            **env,
            "FLIGHT_RECORDER_COMPLETE_MANIFEST_SHA256": checksum,
            "FLIGHT_RECORDER_COMPLETE_MANIFEST_URI": (
                f"s3a://iceberg-raw/flight-recorder/hours/{env['FLIGHT_RECORDER_SOURCE_HOUR_ID']}/"
                f"{checksum}.complete.json"
            ),
        }

        with self.assertRaises(MODULE.FlightRecorderTransformError):
            MODULE.validate_complete_hour_manifest(
                MODULE.HourlyRuntimeConfig.from_environment(changed_env), payload,
            )

    def test_complete_hour_manifest_has_an_aggregate_raw_byte_limit(self) -> None:
        _, payload, env = self.complete_hour()
        config = MODULE.HourlyRuntimeConfig.from_environment(env)
        with patch.object(MODULE, "MAX_COMPLETE_RAW_BYTES", 1):
            with self.assertRaisesRegex(MODULE.FlightRecorderTransformError, "total raw bytes"):
                MODULE.validate_complete_hour_manifest(config, payload)

    def test_complete_hour_manifest_accepts_a_successful_empty_chunk(self) -> None:
        manifest, _, env = self.complete_hour()
        empty = manifest["sources"][0]
        empty_checksum = hashlib.sha256(b"").hexdigest()
        empty["entry_count"] = 0
        empty["raw_bytes"] = 0
        empty["raw_sha256"] = empty_checksum
        window_id = empty["raw_key"].split("/", 3)[2]
        empty["raw_key"] = f"flight-recorder/raw/{window_id}/{empty_checksum}.jsonl"
        manifest["source_count"] -= 1
        manifest["raw_bytes"] -= 10
        payload = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
        checksum = hashlib.sha256(payload).hexdigest()
        env["FLIGHT_RECORDER_COMPLETE_MANIFEST_SHA256"] = checksum
        env["FLIGHT_RECORDER_COMPLETE_MANIFEST_URI"] = (
            f"s3a://iceberg-raw/flight-recorder/hours/{env['FLIGHT_RECORDER_SOURCE_HOUR_ID']}/"
            f"{checksum}.complete.json"
        )
        sources = MODULE.validate_complete_hour_manifest(
            MODULE.HourlyRuntimeConfig.from_environment(env), payload,
        )
        self.assertEqual((0, 0), (sources[0]["entry_count"], sources[0]["raw_bytes"]))

    def test_component_manifest_key_matches_airflow_contract(self) -> None:
        start_ns, end_ns = 1786705200000000000, 1786705500000000000
        window = AIRFLOW_LOKI.LokiWindow(
            MODULE._datetime_ns(str(start_ns)),
            MODULE._datetime_ns(str(end_ns)),
        )
        for component, query in MODULE.COMPONENT_QUERIES:
            with self.subTest(component=component):
                self.assertEqual(
                    MODULE.component_manifest_key(component, query, start_ns, end_ns),
                    AIRFLOW_LOKI.component_manifest_key(
                        component=component,
                        query=query,
                        window=window,
                        limits=AIRFLOW_LOKI.COMPLETE_HOUR_QUERY_LIMITS,
                    ),
                )

    def test_child_manifest_checksum_fails_before_source_read(self) -> None:
        _, payload, env = self.complete_hour()
        config = MODULE.HourlyRuntimeConfig.from_environment(env)
        sources = MODULE.validate_complete_hour_manifest(config, payload)
        spark = object()
        with patch.object(MODULE, "_read_binary", return_value=b"wrong\n") as reader:
            with self.assertRaisesRegex(MODULE.FlightRecorderTransformError, "child manifest checksum"):
                MODULE._read_complete_hour_sources(spark, config, sources)
        reader.assert_called_once_with(spark, f's3a://iceberg-raw/{sources[0]["manifest_key"]}', MODULE.MAX_MANIFEST_BYTES)

    def test_parent_source_counts_must_match_validated_child_objects(self) -> None:
        _, payload, env = self.complete_hour()
        config = MODULE.HourlyRuntimeConfig.from_environment(env)
        source = dict(MODULE.validate_complete_hour_manifest(config, payload)[0])
        start_ns, end_ns = (
            int(value) for value in str(source["raw_key"]).split("/", 3)[2].split("-", 1)
        )
        raw_entry = {
            "timestamp": str(start_ns + 1),
            "labels": {"k8s_namespace_name": "airflow"},
            "line": "line",
        }
        raw_payload = (
            json.dumps(raw_entry, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
        raw_checksum = hashlib.sha256(raw_payload).hexdigest()
        raw_key = COMPLETE_HOUR_CONTRACT.raw_key(
            start_ns=start_ns,
            end_ns=end_ns,
            checksum=raw_checksum,
        )
        child_manifest = {
            "schema_version": MODULE.MANIFEST_SCHEMA_VERSION,
            "query": source["query"],
            "window_start": source["window_start"],
            "window_end": source["window_end"],
            "entry_count": 1,
            "raw_bytes": len(raw_payload),
            "raw_key": raw_key,
            "raw_sha256": raw_checksum,
        }
        child_payload = (
            json.dumps(child_manifest, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
        source.update({
            "manifest_sha256": hashlib.sha256(child_payload).hexdigest(),
            "raw_key": raw_key,
            "raw_sha256": raw_checksum,
        })
        cases = (
            {**source, "entry_count": 2, "raw_bytes": len(raw_payload)},
            {**source, "entry_count": 1, "raw_bytes": len(raw_payload) + 1},
        )
        for changed in cases:
            with self.subTest(changed=changed), patch.object(
                MODULE,
                "_read_binary",
                side_effect=(child_payload, raw_payload),
            ):
                with self.assertRaisesRegex(
                    MODULE.FlightRecorderTransformError,
                    "parent and child source counts",
                ):
                    MODULE._read_complete_hour_sources(object(), config, (changed,))

    def test_schema_migration_adds_only_missing_complete_hour_columns(self) -> None:
        class Field:
            def __init__(self, name): self.name = name

        class Spark:
            commands = []
            def table(self, table):
                retained = {
                    MODULE.EVENTS_TABLE: ("fingerprint", "source_component"),
                    MODULE.HOURLY_TABLE: ("hour",),
                    MODULE.RECEIPTS_TABLE: ("source_window_id",),
                }[table]
                return type("Table", (), {"schema": type("Schema", (), {
                    "fields": [Field(name) for name in retained],
                })()})()
            def sql(self, command): self.commands.append(command)

        spark = Spark()
        MODULE._migrate_tables(spark)
        self.assertEqual([
            f"ALTER TABLE {MODULE.EVENTS_TABLE} ADD COLUMNS (source_chunk_id int)",
            f"ALTER TABLE {MODULE.HOURLY_TABLE} ADD COLUMNS (source_component string)",
            (f"ALTER TABLE {MODULE.RECEIPTS_TABLE} ADD COLUMNS "
             "(source_kind string, complete_manifest_sha256 string)"),
        ], spark.commands)

    def test_component_counts_deduplicate_and_reconcile_per_component(self) -> None:
        events = (
            {"source_component": "workflow", "fingerprint": "a", "rejected": False},
            {"source_component": "workflow", "fingerprint": "a", "rejected": False},
            {"source_component": "workflow", "fingerprint": "b", "rejected": True},
            {"source_component": "trino", "fingerprint": "c", "rejected": False},
            {"source_component": "spark_operator", "fingerprint": "d", "rejected": False},
            {"source_component": "seaweedfs", "fingerprint": "e", "rejected": False},
        )
        deduplicated, counts = MODULE.reconcile_component_events(events)
        self.assertEqual(5, len(deduplicated))
        self.assertEqual({
            "source_count": 3, "accepted_count": 2, "rejected_count": 1,
            "deduplicated_count": 2,
        }, counts["workflow"])
        written = {"workflow": 2, "trino": 1, "spark_operator": 1, "seaweedfs": 1}
        reconciled = MODULE.validate_written_counts(counts, written)
        self.assertEqual(2, reconciled["workflow"]["written_count"])
        with self.assertRaises(MODULE.FlightRecorderTransformError):
            MODULE.validate_written_counts(counts, {**written, "workflow": 1})
        with self.assertRaisesRegex(MODULE.FlightRecorderTransformError, "multiple components"):
            MODULE.reconcile_component_events((*events, {
                "source_component": "seaweedfs", "fingerprint": "a", "rejected": False,
            }))

    def test_zero_event_components_reconcile_and_replay(self) -> None:
        deduplicated, counts = MODULE.reconcile_component_events(())
        self.assertEqual((), deduplicated)
        self.assertEqual(
            {name for name, _ in MODULE.COMPONENT_QUERIES},
            set(counts),
        )
        self.assertTrue(all(not any(values.values()) for values in counts.values()))
        reconciled = MODULE.validate_written_counts(counts, {})
        self.assertTrue(all(values["written_count"] == 0 for values in reconciled.values()))

        source_hour_id, checksum = "1-2", "a" * 64
        receipt = [{
            "source_window_id": source_hour_id,
            "complete_manifest_sha256": checksum,
            "source_count": 0,
            "accepted_count": 0,
            "rejected_count": 0,
            "final_event_count": 0,
        }]
        rows = [
            {"source_component": component, **values}
            for component, values in reconciled.items()
        ]
        self.assertTrue(MODULE.hourly_replay_is_complete(
            receipt,
            rows,
            {},
            source_hour_id=source_hour_id,
            manifest_sha256=checksum,
            final_event_count=0,
        ))

    def test_hourly_replay_requires_receipt_component_rows_and_final_counts(self) -> None:
        source_hour_id, checksum = "1-2", "a" * 64
        receipts = [{
            "source_window_id": source_hour_id,
            "complete_manifest_sha256": checksum,
            "source_count": 4,
            "accepted_count": 4,
            "rejected_count": 0,
            "final_event_count": 4,
        }]
        rows = [
            {"source_component": name, "source_count": 1, "accepted_count": 1,
             "rejected_count": 0, "deduplicated_count": 1, "written_count": 1}
            for name, _ in MODULE.COMPONENT_QUERIES
        ]
        final = {name: 1 for name, _ in MODULE.COMPONENT_QUERIES}
        self.assertTrue(MODULE.hourly_replay_is_complete(
            receipts, rows, final,
            source_hour_id=source_hour_id,
            manifest_sha256=checksum,
            final_event_count=4,
        ))
        with self.assertRaises(MODULE.FlightRecorderTransformError):
            MODULE.hourly_replay_is_complete(
                receipts, rows[:-1], final,
                source_hour_id=source_hour_id,
                manifest_sha256=checksum,
                final_event_count=4,
            )

    def test_source_manifest_and_checksum_mismatch_fail_closed(self) -> None:
        raw = (json.dumps(self.entry(), sort_keys=True, separators=(",", ":")) + "\n").encode()
        checksum = hashlib.sha256(raw).hexdigest()
        config = MODULE.RuntimeConfig.from_environment(self.runtime_env(checksum))
        manifest = {
            "schema_version": 1,
            "query": '{k8s_namespace_name="airflow"}',
            "window_start": config.window_start.isoformat().replace("+00:00", "Z"),
            "window_end": config.window_end.isoformat().replace("+00:00", "Z"),
            "entry_count": 1,
            "raw_bytes": len(raw),
            "raw_key": config.raw_uri.removeprefix("s3a://iceberg-raw/"),
            "raw_sha256": checksum,
        }
        encoded = lambda value: json.dumps(value, sort_keys=True).encode()
        self.assertEqual(len(MODULE.validate_source(config, encoded(manifest), raw)), 1)
        for changed in ({**manifest, "raw_sha256": "b" * 64}, {key: value for key, value in manifest.items() if key != "query"}):
            with self.subTest(changed=changed), self.assertRaises(MODULE.FlightRecorderTransformError):
                MODULE.validate_source(config, encoded(changed), raw)

    def test_component_source_accepts_canonical_empty_raw_bytes(self) -> None:
        base = MODULE.RuntimeConfig.from_environment(self.runtime_env())
        component, query = MODULE.COMPONENT_QUERIES[1]
        start_ns, end_ns = (int(value) for value in base.source_window_id.split("-", 1))
        manifest_key = MODULE.component_manifest_key(component, query, start_ns, end_ns)
        checksum = hashlib.sha256(b"").hexdigest()
        raw_key = f"flight-recorder/raw/{base.source_window_id}/{checksum}.jsonl"
        config = MODULE.RuntimeConfig(
            raw_uri=f"s3a://iceberg-raw/{raw_key}",
            manifest_uri=f"s3a://iceberg-raw/{manifest_key}",
            raw_sha256=checksum,
            source_window_id=base.source_window_id,
            spark_attempt=base.spark_attempt,
            window_start=base.window_start,
            window_end=base.window_end,
        )
        manifest = {
            "schema_version": MODULE.MANIFEST_SCHEMA_VERSION,
            "query": query,
            "window_start": base.window_start.isoformat().replace("+00:00", "Z"),
            "window_end": base.window_end.isoformat().replace("+00:00", "Z"),
            "entry_count": 0,
            "raw_bytes": 0,
            "raw_key": raw_key,
            "raw_sha256": checksum,
        }
        encoded = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
        self.assertEqual((), MODULE.validate_source(
            config,
            encoded,
            b"",
            allow_empty=True,
            expected_manifest_uri=config.manifest_uri,
            expected_query=query,
        ))
        changed = {**manifest, "query": '{k8s_namespace_name="other"}'}
        changed_encoded = (json.dumps(changed, sort_keys=True, separators=(",", ":")) + "\n").encode()
        with self.assertRaisesRegex(MODULE.FlightRecorderTransformError, "query conflicted"):
            MODULE.validate_source(
                config,
                changed_encoded,
                b"",
                allow_empty=True,
                expected_manifest_uri=config.manifest_uri,
                expected_query=query,
            )
        with self.assertRaises(MODULE.FlightRecorderTransformError):
            MODULE.validate_source(config, encoded, b"")

    def test_oversized_binary_metadata_never_selects_content(self) -> None:
        class Reader:
            selected = []
            def format(self, _value): return self
            def load(self, _uri): return self
            def select(self, *names): self.selected.append(names); return self
            def take(self, _limit): return [{"length": MODULE.MAX_RAW_BYTES + 1}]
        reader = Reader()
        spark = type("Spark", (), {"read": reader})()
        with self.assertRaisesRegex(MODULE.FlightRecorderTransformError, "size"):
            MODULE._read_binary(spark, "s3a://iceberg-raw/flight-recorder/raw/source", MODULE.MAX_RAW_BYTES)
        self.assertEqual([("length",)], reader.selected)

    def _empty_source_spark(self, source: Path):
        class Reader:
            def format(self, _value): return self
            def load(self, _uri): return self
            def select(self, *_names): return self
            def take(self, _limit): return []

        class Status:
            def isFile(self): return source.is_file()
            def getLen(self): return source.stat().st_size

        class FileSystem:
            def getFileStatus(self, _path): return Status()

        class HadoopPath:
            def getFileSystem(self, _configuration): return FileSystem()

        class PathFactory:
            def __call__(self, uri):
                self.uri = uri
                return HadoopPath()

        path_factory = PathFactory()
        hadoop = type("Hadoop", (), {"fs": type("Fs", (), {"Path": path_factory})()})()
        org = type("Org", (), {"apache": type("Apache", (), {"hadoop": hadoop})()})()
        context = type("Context", (), {
            "_jvm": type("Jvm", (), {"org": org})(),
            "_jsc": type("Jsc", (), {"hadoopConfiguration": lambda self: object()})(),
        })()
        spark = type("Spark", (), {"read": Reader(), "sparkContext": context})()
        return spark, path_factory

    def test_zero_byte_binary_uses_exact_hadoop_file_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "empty.jsonl"
            source.touch()
            spark, path_factory = self._empty_source_spark(source)
            uri = source.as_uri()
            self.assertEqual(b"", MODULE._read_binary(spark, uri, MODULE.MAX_RAW_BYTES, minimum=0))
            self.assertEqual(uri, path_factory.uri)

    def test_missing_zero_byte_binary_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "missing.jsonl"
            spark, _ = self._empty_source_spark(source)
            with self.assertRaisesRegex(MODULE.FlightRecorderTransformError, "did not exist"):
                MODULE._read_binary(spark, source.as_uri(), MODULE.MAX_RAW_BYTES, minimum=0)

    def test_zero_byte_fallback_rejects_nonzero_length(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "nonempty.jsonl"
            source.write_bytes(b"x")
            spark, _ = self._empty_source_spark(source)
            with self.assertRaisesRegex(MODULE.FlightRecorderTransformError, "was invalid"):
                MODULE._read_binary(spark, source.as_uri(), MODULE.MAX_RAW_BYTES, minimum=0)

    def test_nonempty_binary_retains_content_validation(self) -> None:
        class Reader:
            selected = []
            def format(self, _value): return self
            def load(self, _uri): return self
            def select(self, *names): self.selected.append(names); return self
            def take(self, _limit):
                return [{"length": 2}] if self.selected[-1] == ("length",) else [
                    {"length": 2, "content": bytearray(b"ok")}
                ]

        reader = Reader()
        spark = type("Spark", (), {"read": reader})()
        self.assertEqual(b"ok", MODULE._read_binary(spark, "s3a://bucket/nonempty", 2))
        self.assertEqual([("length",), ("length", "content")], reader.selected)

    def test_wrong_iceberg_table_contract_fails_closed(self) -> None:
        table, schema, partition, location = MODULE._TABLES[0]
        columns = tuple(tuple(field.rsplit(" ", 1)) for field in schema.split(", "))
        ddl = (
            f"CREATE TABLE {table} ({schema}) USING iceberg PARTITIONED BY ({partition}) "
            f"LOCATION '{location}' TBLPROPERTIES ('format-version'='2')"
        )
        MODULE.validate_table_contract(table, columns, ddl)
        with self.assertRaises(MODULE.FlightRecorderTransformError):
            MODULE.validate_table_contract(table, columns, ddl.replace(location, location + "-wrong"))


if __name__ == "__main__":
    unittest.main()
