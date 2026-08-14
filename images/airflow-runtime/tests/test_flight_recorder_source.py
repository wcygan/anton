"""Tests for the Flight Recorder Loki source boundary."""

from datetime import datetime, timedelta, timezone
import json
import unittest
from urllib.parse import parse_qs, urlparse

from anton_airflow.loki import (
    DEFAULT_LOKI_QUERY,
    ENTRY_LIMIT,
    MAX_RESPONSE_BYTES,
    LokiClient,
    LokiSourceError,
    LokiWindow,
)


class RecordingTransport:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls: list[tuple[object, int, int]] = []

    def __call__(self, request: object, *, timeout: int, max_bytes: int) -> bytes:
        self.calls.append((request, timeout, max_bytes))
        return json.dumps(self.payload).encode()


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


if __name__ == "__main__":
    unittest.main()
