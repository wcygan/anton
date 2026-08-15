"""Read one bounded workflow-log window from Loki."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import PurePosixPath
import re
from types import MappingProxyType
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Protocol


DEFAULT_LOKI_ENDPOINT = "http://loki.observability.svc.cluster.local:3100"
DEFAULT_LOKI_QUERY = '{k8s_namespace_name="airflow"}'
WINDOW_SECONDS = 300
ENTRY_LIMIT = 1000
TIMEOUT_SECONDS = 30
MAX_QUERY_LENGTH = 1024
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_RAW_BYTES = 8 * 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024
MANIFEST_SCHEMA_VERSION = 1
SOURCE_PREFIX = "flight-recorder/"
_QUERY_RANGE_PATH = "/loki/api/v1/query_range"
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_SHA256 = re.compile(r"[0-9a-f]{64}")


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


@dataclass(frozen=True, slots=True)
class LokiSourceManifest:
    """The immutable identity of one retained source object."""

    schema_version: int
    query: str
    window_start: str
    window_end: str
    entry_count: int
    raw_bytes: int
    raw_key: str
    raw_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


class ObjectStore(Protocol):
    """Store immutable objects through compare-after-race operations."""

    def get(self, *, key: str) -> bytes | None: ...

    def put_if_absent(self, *, key: str, payload: bytes) -> bool: ...


Transport = Callable[..., bytes]


def _require_utc(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("Loki window timestamps must include a UTC timezone")
    if value.utcoffset() != timedelta(0):
        raise ValueError("Loki window timestamps must use UTC")


def _nanoseconds(value: datetime) -> int:
    delta = value - _EPOCH
    return delta.days * 86_400_000_000_000 + delta.seconds * 1_000_000_000 + delta.microseconds * 1_000


def _iso_utc(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _validate_query(query: str) -> None:
    if not isinstance(query, str) or not query or len(query) > MAX_QUERY_LENGTH:
        raise ValueError(f"query must contain 1-{MAX_QUERY_LENGTH} characters")


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
        _validate_query(query)
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


def serialize_entries(entries: tuple[LokiEntry, ...]) -> bytes:
    """Serialize raw entries with deterministic cross-stream ordering."""
    if not entries:
        raise LokiSourceError("Loki source window returned no entries")
    ordered = sorted(
        entries,
        key=lambda entry: (int(entry.timestamp), tuple(sorted(entry.labels.items())), entry.line),
    )
    payload = b"".join(
        (
            json.dumps(
                {"timestamp": entry.timestamp, "labels": dict(sorted(entry.labels.items())), "line": entry.line},
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode()
        for entry in ordered
    )
    if len(payload) > MAX_RAW_BYTES:
        raise LokiSourceError("Serialized Loki source exceeded the raw byte limit")
    return payload


def manifest_key(*, query: str, window: LokiWindow) -> str:
    """Return the immutable key for one query and source window."""
    _validate_query(query)
    query_sha = hashlib.sha256(query.encode()).hexdigest()
    return f"{SOURCE_PREFIX}manifests/{window.start_ns}-{window.end_ns}/{query_sha}.json"


def raw_key(*, window: LokiWindow, checksum: str) -> str:
    """Return the immutable key for one source payload."""
    if _SHA256.fullmatch(checksum) is None:
        raise ValueError("raw checksum must be a lowercase SHA-256 value")
    return f"{SOURCE_PREFIX}raw/{window.start_ns}-{window.end_ns}/{checksum}.jsonl"


def _safe_key(key: str) -> bool:
    parts = PurePosixPath(key).parts
    return (
        isinstance(key, str)
        and len(key) <= 512
        and key.startswith(SOURCE_PREFIX)
        and not key.startswith("/")
        and "//" not in key
        and all(part not in {"", ".", ".."} for part in parts)
        and all(character.isalnum() or character in "._-/" for character in key)
    )


def _manifest_bytes(manifest: LokiSourceManifest) -> bytes:
    return (json.dumps(manifest.as_dict(), sort_keys=True, separators=(",", ":")) + "\n").encode()


def _parse_manifest(payload: bytes, *, query: str, window: LokiWindow) -> LokiSourceManifest:
    if not payload or len(payload) > MAX_MANIFEST_BYTES:
        raise LokiSourceError("Source manifest size was invalid")
    try:
        value = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise LokiSourceError("Source manifest was not valid JSON") from error
    fields = LokiSourceManifest.__dataclass_fields__
    if not isinstance(value, Mapping) or set(value) != set(fields):
        raise LokiSourceError("Source manifest fields were invalid")
    if type(value["schema_version"]) is not int or value["schema_version"] != MANIFEST_SCHEMA_VERSION:
        raise LokiSourceError("Source manifest schema was invalid")
    if type(value["entry_count"]) is not int or value["entry_count"] < 1:
        raise LokiSourceError("Source manifest entry count was invalid")
    if type(value["raw_bytes"]) is not int or not 1 <= value["raw_bytes"] <= MAX_RAW_BYTES:
        raise LokiSourceError("Source manifest raw byte size was invalid")
    text_fields = ("query", "window_start", "window_end", "raw_key", "raw_sha256")
    if any(not isinstance(value[name], str) for name in text_fields):
        raise LokiSourceError("Source manifest text fields were invalid")
    manifest = LokiSourceManifest(**value)
    expected = (query, _iso_utc(window.start), _iso_utc(window.end))
    if (manifest.query, manifest.window_start, manifest.window_end) != expected:
        raise LokiSourceError("Source manifest identity did not match the request")
    if _SHA256.fullmatch(manifest.raw_sha256) is None:
        raise LokiSourceError("Source manifest checksum was invalid")
    if not _safe_key(manifest.raw_key):
        raise LokiSourceError("Source manifest raw key was unsafe")
    if manifest.raw_key != raw_key(window=window, checksum=manifest.raw_sha256):
        raise LokiSourceError("Source manifest raw identity was invalid")
    return manifest


class LokiSnapshotExtractor:
    """Publish or reuse one immutable source window."""

    def __init__(self, *, client: LokiClient, store: ObjectStore) -> None:
        self.client = client
        self.store = store

    def _get(self, key: str, *, maximum: int) -> bytes | None:
        if not _safe_key(key):
            raise LokiSourceError("Source object key was unsafe")
        try:
            payload = self.store.get(key=key)
        except Exception as error:
            raise LokiSourceError("Source object read failed") from error
        if payload is not None and (not isinstance(payload, bytes) or len(payload) > maximum):
            raise LokiSourceError("Source object read returned invalid bytes")
        return payload

    def _publish(self, key: str, payload: bytes, *, maximum: int) -> None:
        if not _safe_key(key) or not payload or len(payload) > maximum:
            raise LokiSourceError("Source object publication was unsafe")
        try:
            created = self.store.put_if_absent(key=key, payload=payload)
        except Exception as error:
            raise LokiSourceError("Source object publication failed") from error
        if type(created) is not bool:
            raise LokiSourceError("Source object store returned an invalid result")
        if not created and self._get(key, maximum=maximum) != payload:
            raise LokiSourceError("Immutable source object differed after a write race")

    def _replay(self, payload: bytes, *, query: str, window: LokiWindow) -> LokiSourceManifest:
        manifest = _parse_manifest(payload, query=query, window=window)
        retained = self._get(manifest.raw_key, maximum=MAX_RAW_BYTES)
        if retained is None or len(retained) != manifest.raw_bytes:
            raise LokiSourceError("Retained raw source size did not match its manifest")
        if hashlib.sha256(retained).hexdigest() != manifest.raw_sha256:
            raise LokiSourceError("Retained raw source checksum did not match its manifest")
        if not retained.endswith(b"\n") or retained.count(b"\n") != manifest.entry_count:
            raise LokiSourceError("Retained raw source count did not match its manifest")
        return manifest

    def capture(self, *, window: LokiWindow, query: str = DEFAULT_LOKI_QUERY) -> LokiSourceManifest:
        """Reuse a retained source or publish one bounded Loki result."""
        key = manifest_key(query=query, window=window)
        existing = self._get(key, maximum=MAX_MANIFEST_BYTES)
        if existing is not None:
            return self._replay(existing, query=query, window=window)
        entries = self.client.query_range(window=window, query=query)
        payload = serialize_entries(entries)
        checksum = hashlib.sha256(payload).hexdigest()
        source_key = raw_key(window=window, checksum=checksum)
        self._publish(source_key, payload, maximum=MAX_RAW_BYTES)
        manifest = LokiSourceManifest(
            schema_version=MANIFEST_SCHEMA_VERSION,
            query=query,
            window_start=_iso_utc(window.start),
            window_end=_iso_utc(window.end),
            entry_count=len(entries),
            raw_bytes=len(payload),
            raw_key=source_key,
            raw_sha256=checksum,
        )
        self._publish(key, _manifest_bytes(manifest), maximum=MAX_MANIFEST_BYTES)
        return manifest
