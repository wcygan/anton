"""Tests for the Flight Recorder Loki source boundary."""

from datetime import datetime, timedelta, timezone
import json
import unittest
from urllib.parse import parse_qs, urlparse

from anton_airflow.loki import (
    DEFAULT_LOKI_QUERY,
    ENTRY_LIMIT,
    MANIFEST_SCHEMA_VERSION,
    MAX_RAW_BYTES,
    MAX_RESPONSE_BYTES,
    LokiClient,
    LokiEntry,
    LokiSnapshotExtractor,
    LokiSourceError,
    LokiWindow,
    manifest_key,
    serialize_entries,
)


class RecordingTransport:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls: list[tuple[object, int, int]] = []

    def __call__(self, request: object, *, timeout: int, max_bytes: int) -> bytes:
        self.calls.append((request, timeout, max_bytes))
        return json.dumps(self.payload).encode()


class MemoryStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.writes = 0

    def get(self, *, key: str) -> bytes | None:
        return self.objects.get(key)

    def put_if_absent(self, *, key: str, payload: bytes) -> bool:
        self.writes += 1
        if key in self.objects:
            return False
        self.objects[key] = payload
        return True


class StubClient:
    def __init__(self, entries: tuple[LokiEntry, ...]) -> None:
        self.entries = entries
        self.calls = 0

    def query_range(self, **_: object) -> tuple[LokiEntry, ...]:
        self.calls += 1
        return self.entries


class FlightRecorderSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.end = datetime(2026, 8, 14, 12, 0, 0, 123456, tzinfo=timezone.utc)
        self.window = LokiWindow.ending_at(self.end)

    def success(self, values: list[list[object]]) -> dict[str, object]:
        return {
            "status": "success",
            "data": {
                "resultType": "streams",
                "result": [{"stream": {"job": "airflow"}, "values": values}],
            },
        }

    def test_window_is_exact_utc_and_half_open(self) -> None:
        self.assertEqual(timedelta(seconds=300), self.window.end - self.window.start)
        self.assertEqual(1786708800123456000, self.window.end_ns)
        self.assertTrue(self.window.contains(self.window.start_ns))
        self.assertFalse(self.window.contains(self.window.end_ns))
        with self.assertRaises(ValueError):
            LokiWindow.ending_at(datetime(2026, 8, 14, 12, 0))
        with self.assertRaises(ValueError):
            LokiWindow.ending_at(self.end.astimezone(timezone(timedelta(hours=-5))))

    def test_query_uses_fixed_bounds_and_returns_raw_immutable_entries(self) -> None:
        timestamp = str(self.window.start_ns)
        transport = RecordingTransport(self.success([[timestamp, '{"password":"raw"}']]))
        entries = LokiClient(transport=transport).query_range(window=self.window)

        actual = (entries[0].timestamp, entries[0].labels, entries[0].line)
        self.assertEqual((timestamp, {"job": "airflow"}, '{"password":"raw"}'), actual)
        with self.assertRaises(TypeError):
            entries[0].labels["job"] = "changed"  # type: ignore[index]
        request, timeout, max_bytes = transport.calls[0]
        parsed = urlparse(request.full_url)  # type: ignore[attr-defined]
        params = parse_qs(parsed.query)
        self.assertEqual("/loki/api/v1/query_range", parsed.path)
        self.assertEqual([DEFAULT_LOKI_QUERY], params["query"])
        self.assertEqual([str(self.window.start_ns)], params["start"])
        self.assertEqual([str(self.window.end_ns - 1)], params["end"])
        self.assertEqual([str(ENTRY_LIMIT)], params["limit"])
        self.assertEqual(["forward"], params["direction"])
        self.assertEqual((30, MAX_RESPONSE_BYTES), (timeout, max_bytes))

    def test_limit_reach_fails_closed(self) -> None:
        values = [[str(self.window.start_ns + index), "line"] for index in range(ENTRY_LIMIT)]
        client = LokiClient(transport=RecordingTransport(self.success(values)))
        with self.assertRaisesRegex(LokiSourceError, "entry limit"):
            client.query_range(window=self.window)

    def test_malformed_and_invalid_timestamp_responses_fail_closed(self) -> None:
        failures = [
            {"status": "error"},
            {"status": "success", "data": {"resultType": "matrix", "result": []}},
            self.success([["not-nanoseconds", "line"]]),
            self.success([[str(self.window.end_ns), "line"]]),
            self.success([[str(self.window.start_ns), 12]]),
        ]
        for payload in failures:
            with self.subTest(payload=payload):
                client = LokiClient(transport=RecordingTransport(payload))
                with self.assertRaises(LokiSourceError):
                    client.query_range(window=self.window)

    def test_transport_json_and_byte_failures_are_closed(self) -> None:
        def failed_transport(*_: object, **__: object) -> bytes:
            raise TimeoutError("timeout details")

        cases = [
            failed_transport,
            lambda *_args, **_kwargs: b"not-json",
            lambda *_args, **_kwargs: b"x" * (MAX_RESPONSE_BYTES + 1),
        ]
        for transport in cases:
            with self.subTest(transport=transport):
                with self.assertRaises(LokiSourceError):
                    LokiClient(transport=transport).query_range(window=self.window)

    def test_capture_is_deterministic_and_exact_replay_skips_loki(self) -> None:
        entries = (
            LokiEntry(str(self.window.start_ns + 2), {"stream": "b"}, "second"),
            LokiEntry(str(self.window.start_ns + 1), {"stream": "a"}, "first"),
        )
        self.assertEqual(serialize_entries(entries), serialize_entries(tuple(reversed(entries))))
        store = MemoryStore()
        client = StubClient(entries)
        source = LokiSnapshotExtractor(client=client, store=store)  # type: ignore[arg-type]
        manifest = source.capture(window=self.window)

        key = manifest_key(query=DEFAULT_LOKI_QUERY, window=self.window)
        retained_manifest = json.loads(store.objects[key])
        self.assertEqual(MANIFEST_SCHEMA_VERSION, retained_manifest["schema_version"])
        self.assertEqual(DEFAULT_LOKI_QUERY, retained_manifest["query"])
        self.assertEqual(self.window.start.isoformat().replace("+00:00", "Z"), retained_manifest["window_start"])
        self.assertEqual(self.window.end.isoformat().replace("+00:00", "Z"), retained_manifest["window_end"])
        self.assertEqual(2, retained_manifest["entry_count"])
        self.assertTrue(manifest.raw_key.startswith("flight-recorder/raw/"))
        self.assertNotIn("warehouse", manifest.raw_key)
        self.assertEqual(manifest.raw_bytes, len(store.objects[manifest.raw_key]))
        raw_lines = store.objects[manifest.raw_key].splitlines()
        self.assertEqual(["first", "second"], [json.loads(line)["line"] for line in raw_lines])
        writes = store.writes
        replay_client = StubClient(())
        replay = LokiSnapshotExtractor(client=replay_client, store=store)  # type: ignore[arg-type]
        self.assertEqual(manifest, replay.capture(window=self.window))
        self.assertEqual((0, writes), (replay_client.calls, store.writes))

    def test_replay_rejects_bad_manifest_key_and_checksum(self) -> None:
        entry = LokiEntry(str(self.window.start_ns), {"job": "airflow"}, "line")
        store = MemoryStore()
        source = LokiSnapshotExtractor(client=StubClient((entry,)), store=store)  # type: ignore[arg-type]
        manifest = source.capture(window=self.window)
        key = manifest_key(query=DEFAULT_LOKI_QUERY, window=self.window)
        valid_manifest = store.objects[key]

        changed = json.loads(valid_manifest)
        changed["raw_key"] = "flight-recorder/raw/../warehouse/object"
        store.objects[key] = json.dumps(changed).encode()
        with self.assertRaisesRegex(LokiSourceError, "unsafe"):
            source.capture(window=self.window)

        store.objects[key] = valid_manifest
        retained = store.objects[manifest.raw_key]
        store.objects[manifest.raw_key] = b"x" + retained[1:]
        with self.assertRaisesRegex(LokiSourceError, "checksum"):
            source.capture(window=self.window)

    def test_empty_oversized_and_write_collision_fail_closed(self) -> None:
        empty = LokiSnapshotExtractor(client=StubClient(()), store=MemoryStore())  # type: ignore[arg-type]
        with self.assertRaisesRegex(LokiSourceError, "no entries"):
            empty.capture(window=self.window)
        huge = LokiEntry(str(self.window.start_ns), {}, "x" * MAX_RAW_BYTES)
        with self.assertRaisesRegex(LokiSourceError, "byte limit"):
            serialize_entries((huge,))

        class CollisionStore(MemoryStore):
            def put_if_absent(self, *, key: str, payload: bytes) -> bool:
                self.objects[key] = b"different"
                return False

        entry = LokiEntry(str(self.window.start_ns), {}, "line")
        colliding = LokiSnapshotExtractor(client=StubClient((entry,)), store=CollisionStore())  # type: ignore[arg-type]
        with self.assertRaisesRegex(LokiSourceError, "differed"):
            colliding.capture(window=self.window)


if __name__ == "__main__":
    unittest.main()
