"""Public seams for the bounded Ticket 08 Loki-source workflow."""

from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
import unittest
from unittest.mock import patch

from anton_airflow.lakehouse import LOKI_APPLICATION_SPEC
from anton_airflow.loki import (
    LokiClient,
    LokiRecord,
    LokiSnapshot,
    LokiSnapshotExtractor,
    LokiSourceError,
    LokiWindow,
    snapshot_key,
    snapshot_lines,
)
from anton_airflow.loki_operator import LokiSourceSparkOperator


class Writer:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, *, key: str, payload: bytes) -> None:
        self.objects[key] = payload


class FakeExtractor:
    def __init__(self, snapshot: LokiSnapshot) -> None:
        self.snapshot = snapshot
        self.calls: list[tuple[str, LokiWindow]] = []

    def capture(self, *, query: str, window: LokiWindow) -> LokiSnapshot:
        self.calls.append((query, window))
        return self.snapshot


class Ticket08LokiSourceTests(unittest.TestCase):
    def test_loki_window_rejects_unbounded_duration(self) -> None:
        end = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)

        with self.assertRaisesRegex(ValueError, "between 1"):
            LokiWindow.ending_at(end, seconds=901)

        with self.assertRaisesRegex(ValueError, "between 1"):
            LokiWindow.ending_at(end, seconds=0)

        with self.assertRaisesRegex(ValueError, "include a timezone"):
            LokiWindow.ending_at(datetime(2026, 8, 12, 12, 0), seconds=300)

    def test_query_range_is_bounded_and_normalizes_stream_records(self) -> None:
        requests = []

        def transport(request, *, timeout):
            requests.append((request, timeout))
            return json.dumps(
                {
                    "status": "success",
                    "data": {
                        "resultType": "streams",
                        "result": [
                            {
                                "stream": {
                                    "k8s_namespace_name": "lakehouse",
                                    "service_name": "spark-driver",
                                    "severity": "error",
                                },
                                "values": [["1786536000000000000", '{"message":"failed"}']],
                            }
                        ],
                    },
                }
            ).encode()

        window = LokiWindow.ending_at(
            datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc), seconds=300
        )
        records = LokiClient(transport=transport).query_range(
            query='{k8s_namespace_name="lakehouse"}', window=window, limit=10
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].service, "spark-driver")
        self.assertEqual(records[0].level, "error")
        self.assertEqual(records[0].message, "failed")
        self.assertEqual(records[0].labels["service_name"], "spark-driver")
        parsed = parse_qs(urlparse(requests[0][0].full_url).query)
        self.assertEqual(parsed["limit"], ["10"])
        self.assertEqual(parsed["start"], [window.start_ns])
        self.assertEqual(parsed["end"], [window.end_ns])
        self.assertEqual(parsed["direction"], ["forward"])
        self.assertEqual(requests[0][1], 30)

    def test_result_over_limit_fails_closed(self) -> None:
        payload = {
            "status": "success",
            "data": {
                "resultType": "streams",
                "result": [
                    {
                        "stream": {},
                        "values": [["1786536000000000000", "one"], ["1786536001000000000", "two"]],
                    }
                ],
            },
        }
        window = LokiWindow.ending_at(
            datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc), seconds=300
        )
        client = LokiClient(transport=lambda request, timeout: json.dumps(payload).encode())

        with self.assertRaisesRegex(LokiSourceError, "bounded entry limit"):
            client.query_range(query="{job=\"test\"}", window=window, limit=1)

    def test_snapshot_key_and_payload_are_deterministic(self) -> None:
        window = LokiWindow.ending_at(
            datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc), seconds=300
        )
        records = [LokiRecord("evt", "2026-08-12T11:59:00Z", "api", "info", "ok")]
        payload = snapshot_lines(records)

        self.assertEqual(snapshot_key(query="{job=\"test\"}", window=window), snapshot_key(query="{job=\"test\"}", window=window))
        self.assertEqual(payload, b'{"event_id":"evt","labels":{},"level":"info","message":"ok","service":"api","ts":"2026-08-12T11:59:00Z"}\n')

        writer = Writer()
        extractor = LokiSnapshotExtractor(
            client=type("Client", (), {"query_range": lambda self, **kwargs: records})(),
            writer=writer,
            max_entries=10,
        )
        snapshot = extractor.capture(query="{job=\"test\"}", window=window)
        self.assertEqual(snapshot.entries, 1)
        self.assertEqual(writer.objects[snapshot.key], payload)
        self.assertTrue(snapshot.uri.startswith("s3a://iceberg-raw/loki/snapshots/"))

    def test_raw_snapshot_writer_uses_bounded_path_style_sigv4_put(self) -> None:
        from anton_airflow.loki import S3ObjectWriter

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        requests = []

        def opener(request, *, timeout):
            requests.append((request, timeout))
            return Response()

        writer = S3ObjectWriter(
            endpoint="http://seaweedfs.test:8333",
            bucket="iceberg-raw",
            access_key="access",
            secret_key="secret",
            opener=opener,
        )
        writer.put(key="loki/snapshot.jsonl", payload=b"{}\n")

        request, timeout = requests[0]
        self.assertEqual(request.method, "PUT")
        self.assertEqual(request.full_url, "http://seaweedfs.test:8333/iceberg-raw/loki/snapshot.jsonl")
        self.assertEqual(timeout, 30)
        self.assertIn("AWS4-HMAC-SHA256", request.headers["Authorization"])
        self.assertIn("x-amz-content-sha256", {key.lower() for key in request.headers})

        with self.assertRaises(ValueError):
            writer.put(key="../unsafe", payload=b"{}\n")

    def test_loki_source_operator_injects_snapshot_and_keeps_shadow_target(self) -> None:
        window = LokiWindow.ending_at(
            datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc), seconds=300
        )
        snapshot = LokiSnapshot(window, "{job=\"test\"}", "loki/key.jsonl", "s3a://iceberg-raw/loki/key.jsonl", 1, 8, "digest")
        fake = FakeExtractor(snapshot)
        operator = LokiSourceSparkOperator(
            task_id="source",
            application_spec=LOKI_APPLICATION_SPEC,
            source_query="{job=\"test\"}",
            extractor_factory=lambda **kwargs: fake,
            target="shadow",
        )
        context = {
            "dag_id": "airflow_loki_source",
            "run_id": "manual__ticket08",
            "task_id": "source",
            "map_index": -1,
            "try_number": 1,
            "data_interval_end": None,
            "logical_date": None,
            "dag_run": SimpleNamespace(run_after=window.end),
        }

        with patch("anton_airflow.spark.operator.ApacheSparkApplicationOperator.execute", return_value="submitted"):
            self.assertEqual(operator.execute(context), "submitted")

        self.assertEqual(fake.calls[0][0], "{job=\"test\"}")
        self.assertEqual(operator.target, "shadow")
        self.assertIsNotNone(operator.prior_output_validator)
        driver_env = {
            item["name"]: item["value"]
            for item in operator.application_spec["spec"]["driverSpec"]["podTemplateSpec"]["spec"]["containers"][0]["env"]
        }
        self.assertEqual(driver_env["LOKI_INPUT_URI"], snapshot.uri)
        self.assertEqual(
            operator.application_spec["metadata"]["annotations"]["anton.io/source-kind"],
            "loki",
        )

        with self.assertRaises(ValueError):
            LokiSourceSparkOperator(
                task_id="authoritative-source",
                application_spec=LOKI_APPLICATION_SPEC,
                target="authoritative",
            )

    def test_source_dag_is_manual_and_bounded(self) -> None:
        dag_path = Path("/opt/airflow/dags/airflow_loki_source.py")
        spec = importlib.util.spec_from_file_location("airflow_loki_source", dag_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        source_dag = module.loki_source_dag
        self.assertIsNone(source_dag.schedule)
        self.assertFalse(source_dag.catchup)
        self.assertEqual(source_dag.max_active_runs, 1)
        self.assertEqual(source_dag.task_ids, ["run_loki_source_spark_attempt"])
        operator = source_dag.task_dict[source_dag.task_ids[0]]
        self.assertEqual(operator.source_window_seconds, 300)
        self.assertEqual(operator.source_max_entries, 1000)
        self.assertEqual(operator.target, "shadow")


if __name__ == "__main__":
    unittest.main()
