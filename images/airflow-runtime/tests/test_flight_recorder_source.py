"""Tests for the Flight Recorder Loki source boundary."""

from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

from anton_airflow.loki import (
    COMPLETE_HOUR_SCHEMA_VERSION,
    COMPLETE_HOUR_ENTRY_LIMIT,
    COMPLETE_HOUR_QUERY_LIMITS,
    COMPONENT_QUERIES,
    DEFAULT_LOKI_QUERY,
    ENTRY_LIMIT,
    MANIFEST_SCHEMA_VERSION,
    MAX_RAW_BYTES,
    MAX_RESPONSE_BYTES,
    LokiClient,
    LokiEntry,
    LokiHour,
    LokiPublicationAmbiguousError,
    LokiQueryLimits,
    LokiSnapshotExtractor,
    LokiSourceError,
    LokiWindow,
    S3ObjectStore,
    component_manifest_key,
    hour_manifest_key,
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
        self.write_keys: list[str] = []

    def get(self, *, key: str) -> bytes | None:
        return self.objects.get(key)

    def put_if_absent(self, *, key: str, payload: bytes) -> bool:
        self.writes += 1
        self.write_keys.append(key)
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

    def test_hour_is_closed_utc_and_contains_twelve_exact_chunks(self) -> None:
        hour = LokiHour.ending_at(datetime(2026, 8, 14, 12, tzinfo=timezone.utc))
        self.assertEqual(timedelta(hours=1), hour.end - hour.start)
        self.assertEqual(12, len(hour.chunks))
        self.assertEqual((hour.start, hour.end), (hour.chunks[0].start, hour.chunks[-1].end))
        self.assertTrue(all(
            left.end == right.start for left, right in zip(hour.chunks, hour.chunks[1:])
        ))
        for invalid in (
            datetime(2026, 8, 14, 12, 5, tzinfo=timezone.utc),
            datetime(2026, 8, 14, 12),
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                LokiHour.ending_at(invalid)

    def test_complete_hour_publishes_only_after_all_48_sources_succeed(self) -> None:
        hour = LokiHour.ending_at(datetime(2026, 8, 14, 12, tzinfo=timezone.utc))

        class HourClient:
            def __init__(self, fail_at: int | None = None) -> None:
                self.requests = []
                self.limits = []
                self.fail_at = fail_at

            def query_range(self, *, window, query, **limits):
                self.requests.append((window, query))
                self.limits.append(limits["limits"])
                if self.fail_at == len(self.requests):
                    raise LokiSourceError("expected query failure")
                return (LokiEntry(str(window.start_ns), {"component": query}, "line"),)

        store = MemoryStore()
        client = HourClient()
        extractor = LokiSnapshotExtractor(client=client, store=store)  # type: ignore[arg-type]
        manifest = extractor.capture_hour(hour=hour)
        expected_requests = [
            (chunk, query)
            for component, query in COMPONENT_QUERIES
            for chunk in hour.chunks
        ]
        self.assertEqual(expected_requests, client.requests)
        self.assertEqual(
            [COMPLETE_HOUR_QUERY_LIMITS] * 48,
            client.limits,
        )
        self.assertEqual((COMPLETE_HOUR_SCHEMA_VERSION, "complete", 48), (
            manifest.schema_version, manifest.status, len(manifest.sources),
        ))
        self.assertEqual(tuple(range(12)) * 4, tuple(item.chunk_index for item in manifest.sources))
        self.assertEqual(
            tuple(component for component, _ in COMPONENT_QUERIES for _ in range(12)),
            tuple(item.component for item in manifest.sources),
        )
        first = manifest.sources[0]
        self.assertEqual(COMPLETE_HOUR_ENTRY_LIMIT, first.entry_limit)
        self.assertEqual(
            component_manifest_key(
                component=first.component,
                query=first.query,
                window=hour.chunks[0],
                limits=COMPLETE_HOUR_QUERY_LIMITS,
            ),
            first.manifest_key,
        )
        self.assertNotEqual(
            manifest_key(query=first.query, window=hour.chunks[0]),
            first.manifest_key,
        )
        key = hour_manifest_key(hour=hour, checksum=manifest.manifest_sha256)
        self.assertEqual(key, store.write_keys[-1])
        self.assertEqual(manifest.manifest_sha256, __import__("hashlib").sha256(store.objects[key]).hexdigest())

        failed_store = MemoryStore()
        failed = LokiSnapshotExtractor(client=HourClient(fail_at=20), store=failed_store)  # type: ignore[arg-type]
        with self.assertRaisesRegex(LokiSourceError, "spark_operator chunk 7"):
            failed.capture_hour(hour=hour)
        self.assertFalse(any(key.startswith("flight-recorder/hours/") for key in failed_store.objects))

    def test_complete_hour_replay_uses_retained_children_without_loki(self) -> None:
        hour = LokiHour.ending_at(datetime(2026, 8, 14, 12, tzinfo=timezone.utc))

        class HourClient:
            def __init__(self) -> None:
                self.calls = 0

            def query_range(self, *, window, query, **_limits):
                self.calls += 1
                return (LokiEntry(str(window.start_ns), {"component": query}, "line"),)

        store, initial_client = MemoryStore(), HourClient()
        initial = LokiSnapshotExtractor(client=initial_client, store=store)  # type: ignore[arg-type]
        manifest = initial.capture_hour(hour=hour)
        replay_client = HourClient()
        replay = LokiSnapshotExtractor(client=replay_client, store=store)  # type: ignore[arg-type]
        self.assertEqual(manifest, replay.capture_hour(hour=hour))
        self.assertEqual(0, replay_client.calls)

    def test_complete_hour_does_not_reuse_a_weaker_source_contract(self) -> None:
        hour = LokiHour.ending_at(datetime(2026, 8, 14, 12, tzinfo=timezone.utc))

        class HourClient:
            def __init__(self) -> None:
                self.calls = 0

            def query_range(self, *, window, query, **_limits):
                self.calls += 1
                return (LokiEntry(str(window.start_ns), {"component": query}, "line"),)

        component, query = COMPONENT_QUERIES[0]
        store, client = MemoryStore(), HourClient()
        extractor = LokiSnapshotExtractor(client=client, store=store)  # type: ignore[arg-type]
        extractor.capture(
            window=hour.chunks[0],
            query=query,
            component=component,
            limits=LokiQueryLimits(2, MAX_RESPONSE_BYTES, 30),
        )
        manifest = extractor.capture_hour(hour=hour)
        self.assertEqual(49, client.calls)
        self.assertNotEqual(
            component_manifest_key(
                component=component,
                query=query,
                window=hour.chunks[0],
                limits=LokiQueryLimits(2, MAX_RESPONSE_BYTES, 30),
            ),
            manifest.sources[0].manifest_key,
        )

    def test_complete_hour_retains_successful_empty_chunks(self) -> None:
        hour = LokiHour.ending_at(datetime(2026, 8, 14, 12, tzinfo=timezone.utc))

        class EmptyClient:
            def __init__(self) -> None:
                self.calls = 0

            def query_range(self, **_request):
                self.calls += 1
                return ()

        store, client = MemoryStore(), EmptyClient()
        extractor = LokiSnapshotExtractor(client=client, store=store)  # type: ignore[arg-type]
        manifest = extractor.capture_hour(hour=hour)
        self.assertEqual((48, 0, 0), (client.calls, manifest.source_count, manifest.raw_bytes))
        self.assertTrue(all(source.entry_count == source.raw_bytes == 0 for source in manifest.sources))
        self.assertTrue(all(store.objects[source.raw_key] == b"" for source in manifest.sources))

        replay_client = EmptyClient()
        replay = LokiSnapshotExtractor(client=replay_client, store=store)  # type: ignore[arg-type]
        self.assertEqual(manifest, replay.capture_hour(hour=hour))
        self.assertEqual(0, replay_client.calls)

    def test_complete_hour_total_byte_limit_prevents_publication(self) -> None:
        hour = LokiHour.ending_at(datetime(2026, 8, 14, 12, tzinfo=timezone.utc))

        class HourClient:
            def query_range(self, *, window, query, **_limits):
                return (LokiEntry(str(window.start_ns), {"component": query}, "line"),)

        store = MemoryStore()
        extractor = LokiSnapshotExtractor(client=HourClient(), store=store)  # type: ignore[arg-type]
        with patch("anton_airflow.loki.MAX_COMPLETE_RAW_BYTES", 1):
            with self.assertRaisesRegex(LokiSourceError, "Complete hour raw source"):
                extractor.capture_hour(hour=hour)
        self.assertFalse(any(key.startswith("flight-recorder/hours/") for key in store.objects))

    def test_ambiguous_complete_manifest_write_is_read_back(self) -> None:
        hour = LokiHour.ending_at(datetime(2026, 8, 14, 12, tzinfo=timezone.utc))

        class HourClient:
            def query_range(self, *, window, query, **_limits):
                return (LokiEntry(str(window.start_ns), {"component": query}, "line"),)

        class Store(MemoryStore):
            def put_if_absent(self, *, key, payload):
                created = super().put_if_absent(key=key, payload=payload)
                if key.startswith("flight-recorder/hours/"):
                    raise TimeoutError("response was lost")
                return created

        manifest = LokiSnapshotExtractor(client=HourClient(), store=Store()).capture_hour(hour=hour)
        self.assertEqual("complete", manifest.status)

    def test_unresolved_complete_manifest_write_is_ambiguous(self) -> None:
        hour = LokiHour.ending_at(datetime(2026, 8, 14, 12, tzinfo=timezone.utc))

        class HourClient:
            def query_range(self, *, window, query, **_limits):
                return (LokiEntry(str(window.start_ns), {"component": query}, "line"),)

        class Store(MemoryStore):
            failed_key = None

            def get(self, *, key):
                if key == self.failed_key:
                    raise TimeoutError("read failed")
                return super().get(key=key)

            def put_if_absent(self, *, key, payload):
                if key.startswith("flight-recorder/hours/"):
                    self.failed_key = key
                    raise TimeoutError("write failed")
                return super().put_if_absent(key=key, payload=payload)

        with self.assertRaises(LokiPublicationAmbiguousError):
            LokiSnapshotExtractor(client=HourClient(), store=Store()).capture_hour(hour=hour)

    def test_complete_manifest_write_race_requires_exact_read_back(self) -> None:
        hour = LokiHour.ending_at(datetime(2026, 8, 14, 12, tzinfo=timezone.utc))

        class HourClient:
            def query_range(self, *, window, query, **_limits):
                return (LokiEntry(str(window.start_ns), {"component": query}, "line"),)

        for retained in (None, b"conflicting content"):
            class Store(MemoryStore):
                def get(self, *, key):
                    if key.startswith("flight-recorder/hours/"):
                        return retained
                    return super().get(key=key)

                def put_if_absent(self, *, key, payload):
                    if key.startswith("flight-recorder/hours/"):
                        return False
                    return super().put_if_absent(key=key, payload=payload)

            with self.subTest(retained=retained), self.assertRaises(LokiPublicationAmbiguousError):
                LokiSnapshotExtractor(client=HourClient(), store=Store()).capture_hour(hour=hour)

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

    def test_complete_hour_query_limit_is_enforced_by_the_real_client(self) -> None:
        accepted_values = [
            [str(self.window.start_ns + index), "line"]
            for index in range(ENTRY_LIMIT + 1)
        ]
        accepted_transport = RecordingTransport(self.success(accepted_values))
        entries = LokiClient(transport=accepted_transport).query_range(
            window=self.window,
            limits=COMPLETE_HOUR_QUERY_LIMITS,
        )
        self.assertEqual(ENTRY_LIMIT + 1, len(entries))
        request, timeout, max_bytes = accepted_transport.calls[0]
        params = parse_qs(urlparse(request.full_url).query)  # type: ignore[attr-defined]
        self.assertEqual([str(COMPLETE_HOUR_ENTRY_LIMIT)], params["limit"])
        self.assertEqual(COMPLETE_HOUR_QUERY_LIMITS.timeout_seconds, timeout)
        self.assertEqual(COMPLETE_HOUR_QUERY_LIMITS.max_response_bytes, max_bytes)

        saturated_values = [
            [str(self.window.start_ns + index), "line"]
            for index in range(COMPLETE_HOUR_ENTRY_LIMIT)
        ]
        saturated = LokiClient(transport=RecordingTransport(self.success(saturated_values)))
        with self.assertRaisesRegex(LokiSourceError, "entry limit"):
            saturated.query_range(window=self.window, limits=COMPLETE_HOUR_QUERY_LIMITS)

        invalid_values = (
            (COMPLETE_HOUR_ENTRY_LIMIT + 1, MAX_RESPONSE_BYTES, 30),
            (1, MAX_RESPONSE_BYTES + 1, 30),
            (1, 1, 31),
        )
        for values in invalid_values:
            with self.subTest(values=values), self.assertRaises(ValueError):
                LokiQueryLimits(*values)
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
        with self.assertRaisesRegex(LokiPublicationAmbiguousError, "unresolved"):
            colliding.capture(window=self.window)

    def test_s3_store_bounds_requests_and_maps_immutable_statuses(self) -> None:
        requests = []
        key = "flight-recorder/raw/window/checksum.jsonl"
        for conflict in (409, 412):
            def absent(request, *, timeout):
                requests.append((request, timeout))
                raise HTTPError(request.full_url, conflict, "expected", {}, None)
            store = S3ObjectStore(access_key="test-access", secret_key="test-secret", opener=absent)
            self.assertFalse(store.put_if_absent(key=key, payload=b"raw\n"))
        self.assertEqual("*", requests[0][0].get_header("If-none-match"))
        self.assertIn("/iceberg-raw/flight-recorder/raw/", requests[0][0].full_url)
        self.assertNotIn("test-secret", str(requests))

        outcomes, events = iter((409, 404, b"raw\n")), []
        def race(request, *, timeout):
            outcome = next(outcomes)
            events.append(outcome)
            if isinstance(outcome, int): raise HTTPError(request.full_url, outcome, "expected", {}, None)
            return BytesIO(outcome)
        source = LokiSnapshotExtractor(client=StubClient(()), store=S3ObjectStore(access_key="a", secret_key="b", opener=race), sleeper=lambda delay: events.append(delay))  # type: ignore[arg-type]
        source._publish(key, b"raw\n", maximum=MAX_RAW_BYTES)
        self.assertEqual([409, 404, 0.05, b"raw\n"], events)
        outcomes = iter((409, 404, 404))
        with self.assertRaisesRegex(LokiPublicationAmbiguousError, "unresolved"):
            source._publish(key, b"raw\n", maximum=MAX_RAW_BYTES)

        oversized = lambda *_args, **_kwargs: BytesIO(b"x" * (MAX_RAW_BYTES + 1))
        with self.assertRaisesRegex(LokiSourceError, "byte limit"):
            S3ObjectStore(access_key="a", secret_key="b", opener=oversized).get(key=key)
        with self.assertRaisesRegex(LokiSourceError, "object bounds"):
            store.get(key="../warehouse")


if __name__ == "__main__":
    unittest.main()
