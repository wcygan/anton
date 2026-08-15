"""Read one bounded workflow-log window from Loki."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from types import MappingProxyType
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


DEFAULT_LOKI_ENDPOINT = "http://loki.observability.svc.cluster.local:3100"
DEFAULT_LOKI_QUERY = '{k8s_namespace_name="airflow"}'
WINDOW_SECONDS = 300
ENTRY_LIMIT = 1000
TIMEOUT_SECONDS = 30
MAX_QUERY_LENGTH = 1024
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_QUERY_RANGE_PATH = "/loki/api/v1/query_range"
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class LokiSourceError(RuntimeError):
    """A bounded Loki read failed its source contract."""


@dataclass(frozen=True, slots=True)
class LokiWindow:
    """One five-minute UTC interval with an exclusive end."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        _require_utc(self.start)
        _require_utc(self.end)
        if self.end - self.start != timedelta(seconds=WINDOW_SECONDS):
            raise ValueError("Loki window must be exactly 300 seconds")

    @classmethod
    def ending_at(cls, end: datetime) -> LokiWindow:
        """Create the five-minute interval that ends at the given time."""
        _require_utc(end)
        return cls(start=end - timedelta(seconds=WINDOW_SECONDS), end=end)

    @property
    def start_ns(self) -> int:
        return _nanoseconds(self.start)

    @property
    def end_ns(self) -> int:
        """Return the exclusive window end."""
        return _nanoseconds(self.end)

    def contains(self, timestamp_ns: int) -> bool:
        return self.start_ns <= timestamp_ns < self.end_ns


@dataclass(frozen=True, slots=True)
class LokiEntry:
    """One immutable raw Loki entry."""

    timestamp: str
    labels: Mapping[str, str]
    line: str


Transport = Callable[..., bytes]


def _require_utc(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("Loki window timestamps must include a UTC timezone")
    if value.utcoffset() != timedelta(0):
        raise ValueError("Loki window timestamps must use UTC")


def _nanoseconds(value: datetime) -> int:
    delta = value - _EPOCH
    return delta.days * 86_400_000_000_000 + delta.seconds * 1_000_000_000 + delta.microseconds * 1_000


def _default_transport(request: urllib.request.Request, *, timeout: int, max_bytes: int) -> bytes:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read(max_bytes + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise LokiSourceError("Loki transport failed") from error


def _raw_entries(payload: Mapping[str, Any], window: LokiWindow) -> tuple[LokiEntry, ...]:
    if payload.get("status") != "success":
        raise LokiSourceError("Loki response status was not success")
    data = payload.get("data")
    if not isinstance(data, Mapping) or data.get("resultType") != "streams":
        raise LokiSourceError("Loki response did not contain streams")
    streams = data.get("result")
    if not isinstance(streams, list):
        raise LokiSourceError("Loki response streams were malformed")

    entries: list[LokiEntry] = []
    for stream in streams:
        if not isinstance(stream, Mapping):
            raise LokiSourceError("Loki response contained a malformed stream")
        labels = stream.get("stream")
        values = stream.get("values")
        if not isinstance(labels, Mapping) or not isinstance(values, list):
            raise LokiSourceError("Loki stream omitted labels or values")
        invalid_labels = any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in labels.items()
        )
        if invalid_labels:
            raise LokiSourceError("Loki stream labels were malformed")
        frozen_labels = MappingProxyType(dict(sorted(labels.items())))
        for value in values:
            if not isinstance(value, list) or len(value) != 2:
                raise LokiSourceError("Loki response contained a malformed entry")
            timestamp, line = value
            if not isinstance(timestamp, str) or not timestamp.isascii() or not timestamp.isdigit():
                raise LokiSourceError("Loki entry timestamp was invalid")
            if not isinstance(line, str):
                raise LokiSourceError("Loki entry line was malformed")
            timestamp_ns = int(timestamp)
            if not window.contains(timestamp_ns):
                raise LokiSourceError("Loki entry timestamp was outside the source window")
            entries.append(LokiEntry(timestamp=timestamp, labels=frozen_labels, line=line))
            if len(entries) >= ENTRY_LIMIT:
                raise LokiSourceError("Loki result reached the bounded entry limit")
    return tuple(entries)


class LokiClient:
    """Read Loki through one fixed and bounded range endpoint."""

    def __init__(
        self,
        *,
        endpoint: str = DEFAULT_LOKI_ENDPOINT,
        transport: Transport | None = None,
    ) -> None:
        parsed = urllib.parse.urlparse(endpoint)
        location_parts = (parsed.params, parsed.query, parsed.fragment, parsed.username, parsed.password)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Loki endpoint must be an HTTP base URL")
        if parsed.path not in {"", "/"} or any(location_parts):
            raise ValueError("Loki endpoint must be an HTTP base URL")
        self._endpoint = endpoint.rstrip("/") + _QUERY_RANGE_PATH
        self._transport = transport or _default_transport

    def query_range(self, *, window: LokiWindow, query: str = DEFAULT_LOKI_QUERY) -> tuple[LokiEntry, ...]:
        """Return raw entries from one complete half-open window."""
        if not isinstance(query, str) or not query or len(query) > MAX_QUERY_LENGTH:
            raise ValueError(f"query must contain 1-{MAX_QUERY_LENGTH} characters")
        params = urllib.parse.urlencode(
            {
                "query": query,
                "start": str(window.start_ns),
                "end": str(window.end_ns - 1),
                "limit": str(ENTRY_LIMIT),
                "direction": "forward",
            }
        )
        request = urllib.request.Request(
            f"{self._endpoint}?{params}",
            headers={"Accept": "application/json"},
            method="GET",
        )
        try:
            raw = self._transport(request, timeout=TIMEOUT_SECONDS, max_bytes=MAX_RESPONSE_BYTES)
        except LokiSourceError:
            raise
        except Exception as error:
            raise LokiSourceError("Loki transport failed") from error
        if not isinstance(raw, bytes):
            raise LokiSourceError("Loki transport returned a malformed response")
        if len(raw) > MAX_RESPONSE_BYTES:
            raise LokiSourceError("Loki response exceeded the byte limit")
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise LokiSourceError("Loki returned invalid JSON") from error
        if not isinstance(payload, Mapping):
            raise LokiSourceError("Loki returned a non-object response")
        return _raw_entries(payload, window)
