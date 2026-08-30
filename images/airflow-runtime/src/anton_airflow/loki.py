"""Read one bounded workflow-log window from Loki."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import PurePosixPath
import re
import time
from types import MappingProxyType
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Protocol

import anton_flight_recorder_contract as complete_hour_contract


DEFAULT_LOKI_ENDPOINT = "http://loki.observability.svc.cluster.local:3100"
DEFAULT_LOKI_QUERY = '{k8s_namespace_name="airflow"}'
DEFAULT_RAW_ENDPOINT = "http://seaweedfs-s3.storage.svc.cluster.local:8333"
DEFAULT_RAW_BUCKET = "iceberg-raw"
WINDOW_SECONDS = complete_hour_contract.WINDOW_SECONDS
HOUR_SECONDS = complete_hour_contract.HOUR_SECONDS
ENTRY_LIMIT = 1000
COMPLETE_HOUR_ENTRY_LIMIT = complete_hour_contract.COMPLETE_HOUR_ENTRY_LIMIT
TIMEOUT_SECONDS = complete_hour_contract.TIMEOUT_SECONDS
MAX_QUERY_LENGTH = complete_hour_contract.MAX_QUERY_LENGTH
MAX_RESPONSE_BYTES = complete_hour_contract.MAX_RESPONSE_BYTES
MAX_RAW_BYTES = complete_hour_contract.MAX_RAW_BYTES
MAX_MANIFEST_BYTES = complete_hour_contract.MAX_SOURCE_MANIFEST_BYTES
MANIFEST_SCHEMA_VERSION = complete_hour_contract.SOURCE_MANIFEST_SCHEMA_VERSION
COMPLETE_HOUR_SCHEMA_VERSION = complete_hour_contract.COMPLETE_HOUR_SCHEMA_VERSION
MAX_HOUR_MANIFEST_BYTES = complete_hour_contract.MAX_COMPLETE_MANIFEST_BYTES
MAX_COMPLETE_RAW_BYTES = complete_hour_contract.MAX_COMPLETE_RAW_BYTES
SOURCE_PREFIX = complete_hour_contract.SOURCE_PREFIX
COMPONENT_QUERIES = complete_hour_contract.COMPONENT_QUERIES
_QUERY_RANGE_PATH = "/loki/api/v1/query_range"
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class LokiQueryLimits:
    """One immutable Loki query fence contract."""

    entry_limit: int
    max_response_bytes: int
    timeout_seconds: int

    def __post_init__(self) -> None:
        values = (
            (self.entry_limit, COMPLETE_HOUR_ENTRY_LIMIT, "entry"),
            (self.max_response_bytes, MAX_RESPONSE_BYTES, "response byte"),
            (self.timeout_seconds, TIMEOUT_SECONDS, "timeout"),
        )
        for value, maximum, name in values:
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(f"Loki {name} limit was invalid")

    def as_dict(self) -> dict[str, int]:
        return {
            "entry_limit": self.entry_limit,
            "max_response_bytes": self.max_response_bytes,
            "timeout_seconds": self.timeout_seconds,
        }


LEGACY_QUERY_LIMITS = LokiQueryLimits(ENTRY_LIMIT, MAX_RESPONSE_BYTES, TIMEOUT_SECONDS)
COMPLETE_HOUR_QUERY_LIMITS = LokiQueryLimits(
    COMPLETE_HOUR_ENTRY_LIMIT,
    MAX_RESPONSE_BYTES,
    TIMEOUT_SECONDS,
)


class LokiSourceError(RuntimeError):
    """A bounded Loki read failed its source contract."""


class LokiHourCaptureError(LokiSourceError):
    """One component chunk prevented complete-hour publication."""

    def __init__(self, *, component: str, chunk_index: int, completed_queries: int) -> None:
        self.component = component
        self.chunk_index = chunk_index
        self.completed_queries = completed_queries
        super().__init__(f"complete hour capture failed at {component} chunk {chunk_index}")


class LokiPublicationAmbiguousError(LokiSourceError):
    """A source write could not be confirmed as present or absent."""

    complete_manifest_published = None


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
class LokiHour:
    """One closed UTC hour with twelve five-minute chunks."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        _require_utc(self.start)
        _require_utc(self.end)
        if self.end - self.start != timedelta(seconds=HOUR_SECONDS):
            raise ValueError("Loki hour must be exactly 3600 seconds")
        if any((self.start.minute, self.start.second, self.start.microsecond,
                self.end.minute, self.end.second, self.end.microsecond)):
            raise ValueError("Loki hour must use UTC hour boundaries")

    @classmethod
    def ending_at(cls, end: datetime) -> LokiHour:
        """Create the closed hour before one UTC hour boundary."""
        _require_utc(end)
        return cls(start=end - timedelta(seconds=HOUR_SECONDS), end=end)

    @property
    def start_ns(self) -> int:
        return _nanoseconds(self.start)

    @property
    def end_ns(self) -> int:
        return _nanoseconds(self.end)

    @property
    def chunks(self) -> tuple[LokiWindow, ...]:
        return tuple(
            LokiWindow(
                start=self.start + timedelta(seconds=WINDOW_SECONDS * index),
                end=self.start + timedelta(seconds=WINDOW_SECONDS * (index + 1)),
            )
            for index in range(HOUR_SECONDS // WINDOW_SECONDS)
        )


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


@dataclass(frozen=True, slots=True)
class CompleteHourSource:
    """One validated component chunk in a complete hour."""

    component: str
    chunk_index: int
    entry_limit: int
    max_response_bytes: int
    timeout_seconds: int
    manifest_key: str
    manifest_sha256: str
    query: str
    window_start: str
    window_end: str
    entry_count: int
    raw_bytes: int
    raw_key: str
    raw_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True, slots=True)
class CompleteHourManifest:
    """One immutable complete-hour source envelope."""

    schema_version: int
    kind: str
    status: str
    hour_start: str
    hour_end: str
    source_hour_id: str
    catalog_sha256: str
    component_count: int
    chunk_count: int
    source_count: int
    raw_bytes: int
    sources: tuple[CompleteHourSource, ...]

    def as_dict(self) -> dict[str, object]:
        value = {name: getattr(self, name) for name in self.__dataclass_fields__ if name != "sources"}
        value["sources"] = [source.as_dict() for source in self.sources]
        return value

    @property
    def manifest_sha256(self) -> str:
        return hashlib.sha256(_hour_manifest_bytes(self)).hexdigest()


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


def _raw_entries(
    payload: Mapping[str, Any],
    window: LokiWindow,
    *,
    entry_limit: int = ENTRY_LIMIT,
) -> tuple[LokiEntry, ...]:
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
            if len(entries) >= entry_limit:
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

    def query_range(
        self,
        *,
        window: LokiWindow,
        query: str = DEFAULT_LOKI_QUERY,
        limits: LokiQueryLimits = LEGACY_QUERY_LIMITS,
    ) -> tuple[LokiEntry, ...]:
        """Return raw entries from one complete half-open window."""
        _validate_query(query)
        if not isinstance(limits, LokiQueryLimits):
            raise TypeError("Loki query limits were invalid")
        params = urllib.parse.urlencode(
            {
                "query": query,
                "start": str(window.start_ns),
                "end": str(window.end_ns - 1),
                "limit": str(limits.entry_limit),
                "direction": "forward",
            }
        )
        request = urllib.request.Request(
            f"{self._endpoint}?{params}",
            headers={"Accept": "application/json"},
            method="GET",
        )
        try:
            raw = self._transport(
                request,
                timeout=limits.timeout_seconds,
                max_bytes=limits.max_response_bytes,
            )
        except LokiSourceError:
            raise
        except Exception as error:
            raise LokiSourceError("Loki transport failed") from error
        if not isinstance(raw, bytes):
            raise LokiSourceError("Loki transport returned a malformed response")
        if len(raw) > limits.max_response_bytes:
            raise LokiSourceError("Loki response exceeded the byte limit")
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise LokiSourceError("Loki returned invalid JSON") from error
        if not isinstance(payload, Mapping):
            raise LokiSourceError("Loki returned a non-object response")
        return _raw_entries(payload, window, entry_limit=limits.entry_limit)


def serialize_entries(
    entries: tuple[LokiEntry, ...],
    *,
    allow_empty: bool = False,
) -> bytes:
    """Serialize raw entries with deterministic cross-stream ordering."""
    if not entries and not allow_empty:
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


def component_manifest_key(
    *,
    component: str,
    query: str,
    window: LokiWindow,
    limits: LokiQueryLimits,
) -> str:
    """Return the contract-bound key for one complete-hour source."""
    return complete_hour_contract.component_manifest_key(
        component=component,
        query=query,
        start_ns=window.start_ns,
        end_ns=window.end_ns,
        entry_limit=limits.entry_limit,
        max_response_bytes=limits.max_response_bytes,
        timeout_seconds=limits.timeout_seconds,
    )


def raw_key(*, window: LokiWindow, checksum: str) -> str:
    """Return the immutable key for one source payload."""
    return complete_hour_contract.raw_key(
        start_ns=window.start_ns,
        end_ns=window.end_ns,
        checksum=checksum,
    )


def hour_manifest_key(*, hour: LokiHour, checksum: str) -> str:
    """Return the content-addressed key for one complete hour."""
    return complete_hour_contract.hour_manifest_key(
        start_ns=hour.start_ns,
        end_ns=hour.end_ns,
        checksum=checksum,
    )


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


def _hour_manifest_bytes(manifest: CompleteHourManifest) -> bytes:
    try:
        return complete_hour_contract.encode_complete_hour_manifest(manifest.as_dict())
    except ValueError as error:
        raise LokiSourceError("Complete hour manifest was invalid") from error


def _parse_manifest(
    payload: bytes,
    *,
    query: str,
    window: LokiWindow,
    allow_empty: bool = False,
) -> LokiSourceManifest:
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
    minimum = 0 if allow_empty else 1
    if type(value["entry_count"]) is not int or value["entry_count"] < minimum:
        raise LokiSourceError("Source manifest entry count was invalid")
    if type(value["raw_bytes"]) is not int or not minimum <= value["raw_bytes"] <= MAX_RAW_BYTES:
        raise LokiSourceError("Source manifest raw byte size was invalid")
    if (value["entry_count"] == 0) != (value["raw_bytes"] == 0):
        raise LokiSourceError("Source manifest empty state was invalid")
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

    def __init__(self, *, client: LokiClient, store: ObjectStore, sleeper: Callable[[float], None] = time.sleep) -> None:
        self.client = client
        self.store = store
        self.sleeper = sleeper

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

    def _publish(
        self,
        key: str,
        payload: bytes,
        *,
        maximum: int,
        allow_empty: bool = False,
    ) -> None:
        if not _safe_key(key) or (not payload and not allow_empty) or len(payload) > maximum:
            raise LokiSourceError("Source object publication was unsafe")
        try:
            created = self.store.put_if_absent(key=key, payload=payload)
        except Exception as error:
            try:
                retained = self._get(key, maximum=maximum)
                if retained is None:
                    self.sleeper(0.05)
                    retained = self._get(key, maximum=maximum)
            except LokiSourceError as read_error:
                raise LokiPublicationAmbiguousError(
                    "Source object publication state was ambiguous"
                ) from read_error
            if retained == payload:
                return
            if retained is not None:
                raise LokiPublicationAmbiguousError(
                    "Source object publication returned conflicting content"
                ) from error
            raise LokiSourceError("Source object publication failed and remained absent") from error
        if type(created) is not bool:
            raise LokiSourceError("Source object store returned an invalid result")
        if not created:
            retained = self._get(key, maximum=maximum)
            if retained is None:
                self.sleeper(0.05)
                retained = self._get(key, maximum=maximum)
            if retained != payload:
                raise LokiPublicationAmbiguousError(
                    "Immutable source object was unresolved after a write race"
                )

    def _replay(
        self,
        payload: bytes,
        *,
        query: str,
        window: LokiWindow,
        allow_empty: bool = False,
    ) -> LokiSourceManifest:
        manifest = _parse_manifest(
            payload,
            query=query,
            window=window,
            allow_empty=allow_empty,
        )
        retained = self._get(manifest.raw_key, maximum=MAX_RAW_BYTES)
        if retained is None or len(retained) != manifest.raw_bytes:
            raise LokiSourceError("Retained raw source size did not match its manifest")
        if hashlib.sha256(retained).hexdigest() != manifest.raw_sha256:
            raise LokiSourceError("Retained raw source checksum did not match its manifest")
        valid_count = (
            retained == b"" if manifest.entry_count == 0
            else retained.endswith(b"\n") and retained.count(b"\n") == manifest.entry_count
        )
        if not valid_count:
            raise LokiSourceError("Retained raw source count did not match its manifest")
        return manifest

    def capture(
        self,
        *,
        window: LokiWindow,
        query: str = DEFAULT_LOKI_QUERY,
        component: str | None = None,
        limits: LokiQueryLimits = LEGACY_QUERY_LIMITS,
    ) -> LokiSourceManifest:
        """Reuse a retained source or publish one bounded Loki result."""
        if component is None:
            if limits != LEGACY_QUERY_LIMITS:
                raise ValueError("Custom Loki limits require a component identity")
            key = manifest_key(query=query, window=window)
        else:
            key = component_manifest_key(
                component=component,
                query=query,
                window=window,
                limits=limits,
            )
        existing = self._get(key, maximum=MAX_MANIFEST_BYTES)
        if existing is not None:
            return self._replay(
                existing,
                query=query,
                window=window,
                allow_empty=component is not None,
            )
        entries = self.client.query_range(
            window=window,
            query=query,
            limits=limits,
        )
        payload = serialize_entries(entries, allow_empty=component is not None)
        checksum = hashlib.sha256(payload).hexdigest()
        source_key = raw_key(window=window, checksum=checksum)
        self._publish(
            source_key,
            payload,
            maximum=MAX_RAW_BYTES,
            allow_empty=component is not None,
        )
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

    def capture_hour(self, *, hour: LokiHour) -> CompleteHourManifest:
        """Publish a complete hour only after all component chunks succeed."""
        sources: list[CompleteHourSource] = []
        for component, query in COMPONENT_QUERIES:
            for chunk_index, window in enumerate(hour.chunks):
                try:
                    manifest = self.capture(
                        window=window,
                        query=query,
                        component=component,
                        limits=COMPLETE_HOUR_QUERY_LIMITS,
                    )
                except LokiSourceError as error:
                    raise LokiHourCaptureError(
                        component=component,
                        chunk_index=chunk_index,
                        completed_queries=len(sources),
                    ) from error
                retained_manifest = _manifest_bytes(manifest)
                retained_manifest_key = component_manifest_key(
                    component=component,
                    query=query,
                    window=window,
                    limits=COMPLETE_HOUR_QUERY_LIMITS,
                )
                sources.append(CompleteHourSource(
                    component=component,
                    chunk_index=chunk_index,
                    entry_limit=COMPLETE_HOUR_QUERY_LIMITS.entry_limit,
                    max_response_bytes=COMPLETE_HOUR_QUERY_LIMITS.max_response_bytes,
                    timeout_seconds=COMPLETE_HOUR_QUERY_LIMITS.timeout_seconds,
                    manifest_key=retained_manifest_key,
                    manifest_sha256=hashlib.sha256(retained_manifest).hexdigest(),
                    query=manifest.query,
                    window_start=manifest.window_start,
                    window_end=manifest.window_end,
                    entry_count=manifest.entry_count,
                    raw_bytes=manifest.raw_bytes,
                    raw_key=manifest.raw_key,
                    raw_sha256=manifest.raw_sha256,
                ))
        manifest = CompleteHourManifest(
            schema_version=COMPLETE_HOUR_SCHEMA_VERSION,
            kind=complete_hour_contract.COMPLETE_HOUR_KIND,
            status=complete_hour_contract.COMPLETE_HOUR_STATUS,
            hour_start=_iso_utc(hour.start),
            hour_end=_iso_utc(hour.end),
            source_hour_id=f"{hour.start_ns}-{hour.end_ns}",
            catalog_sha256=complete_hour_contract.component_catalog_sha256(),
            component_count=len(COMPONENT_QUERIES),
            chunk_count=len(sources),
            source_count=sum(source.entry_count for source in sources),
            raw_bytes=sum(source.raw_bytes for source in sources),
            sources=tuple(sources),
        )
        if manifest.raw_bytes > MAX_COMPLETE_RAW_BYTES:
            raise LokiSourceError("Complete hour raw source exceeded the byte limit")
        payload = _hour_manifest_bytes(manifest)
        key = hour_manifest_key(hour=hour, checksum=manifest.manifest_sha256)
        self._publish(key, payload, maximum=MAX_HOUR_MANIFEST_BYTES)
        return manifest


class S3ObjectStore:
    """Bounded path-style S3 storage with SigV4 requests."""

    def __init__(
        self, *, access_key: str, secret_key: str,
        endpoint: str = DEFAULT_RAW_ENDPOINT, bucket: str = DEFAULT_RAW_BUCKET,
        opener: Any = urllib.request.urlopen,
    ) -> None:
        parsed = urllib.parse.urlparse(endpoint)
        location_parts = (parsed.params, parsed.query, parsed.fragment, parsed.username, parsed.password)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path not in {"", "/"} or any(location_parts):
            raise ValueError("S3 endpoint must be an HTTP base URL")
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket):
            raise ValueError("S3 bucket name was invalid")
        if not access_key or not secret_key:
            raise ValueError("S3 credentials are required")
        self.endpoint, self.bucket = endpoint.rstrip("/"), bucket
        self._access_key, self._secret_key, self._opener = access_key, secret_key, opener

    def _request(self, method: str, key: str, payload: bytes = b"") -> urllib.request.Request:
        if not _safe_key(key) or len(payload) > MAX_RAW_BYTES:
            raise LokiSourceError("S3 request exceeded its object bounds")
        now = datetime.now(timezone.utc)
        date, short_date = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
        path = "/" + urllib.parse.quote(self.bucket, safe="") + "/" + urllib.parse.quote(key, safe="/")
        body_hash = hashlib.sha256(payload).hexdigest()
        headers = {"host": urllib.parse.urlparse(self.endpoint).netloc, "x-amz-content-sha256": body_hash, "x-amz-date": date}
        if method == "PUT":
            headers["if-none-match"] = "*"
        names = ";".join(sorted(headers))
        canonical_headers = "".join(f"{name}:{headers[name]}\n" for name in sorted(headers))
        canonical = "\n".join((method, path, "", canonical_headers, names, body_hash))
        scope = f"{short_date}/us-east-1/s3/aws4_request"
        to_sign = "\n".join(("AWS4-HMAC-SHA256", date, scope, hashlib.sha256(canonical.encode()).hexdigest()))
        signing_key = ("AWS4" + self._secret_key).encode()
        for value in (short_date, "us-east-1", "s3", "aws4_request"):
            signing_key = hmac.new(signing_key, value.encode(), hashlib.sha256).digest()
        signature = hmac.new(signing_key, to_sign.encode(), hashlib.sha256).hexdigest()
        request_headers = {name.title(): value for name, value in headers.items()}
        request_headers["Authorization"] = (
            f"AWS4-HMAC-SHA256 Credential={self._access_key}/{scope}, "
            f"SignedHeaders={names}, Signature={signature}")
        return urllib.request.Request(f"{self.endpoint}{path}", data=payload if method == "PUT" else None, headers=request_headers, method=method)

    def get(self, *, key: str) -> bytes | None:
        try:
            with self._opener(self._request("GET", key), timeout=TIMEOUT_SECONDS) as response:
                if getattr(response, "status", 200) != 200:
                    raise LokiSourceError("S3 GET returned an invalid status")
                payload = response.read(MAX_RAW_BYTES + 1)
        except urllib.error.HTTPError as error:
            error.close()
            if error.code == 404:
                return None
            raise LokiSourceError(f"S3 GET returned HTTP {error.code}") from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise LokiSourceError("S3 GET transport failed") from error
        if len(payload) > MAX_RAW_BYTES:
            raise LokiSourceError("S3 GET exceeded the response byte limit")
        return payload

    def put_if_absent(self, *, key: str, payload: bytes) -> bool:
        try:
            with self._opener(self._request("PUT", key, payload), timeout=TIMEOUT_SECONDS) as response:
                if getattr(response, "status", 200) not in {200, 201, 204}:
                    raise LokiSourceError("S3 PUT returned an invalid status")
                return True
        except urllib.error.HTTPError as error:
            error.close()
            if error.code in {409, 412}:
                return False
            raise LokiSourceError(f"S3 PUT returned HTTP {error.code}") from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise LokiSourceError("S3 PUT transport failed") from error


def extractor_from_environment() -> tuple[LokiSnapshotExtractor, str]:
    """Build the bounded Loki and raw object clients from runtime settings."""
    access_key, secret_key = os.getenv("RAW_ACCESS_KEY_ID"), os.getenv("RAW_SECRET_ACCESS_KEY")
    if not access_key or not secret_key:
        raise LokiSourceError("Raw S3 credentials are required")
    bucket = os.getenv("RAW_S3_BUCKET", DEFAULT_RAW_BUCKET)
    store = S3ObjectStore(
        access_key=access_key, secret_key=secret_key,
        endpoint=os.getenv("RAW_S3_ENDPOINT", DEFAULT_RAW_ENDPOINT), bucket=bucket)
    return LokiSnapshotExtractor(client=LokiClient(endpoint=os.getenv("LOKI_ENDPOINT", DEFAULT_LOKI_ENDPOINT)), store=store), bucket
