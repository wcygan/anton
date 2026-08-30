"""Stable wire rules for one Flight Recorder Complete Hour."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone


WINDOW_SECONDS = 300
HOUR_SECONDS = 3600
CHUNKS_PER_HOUR = HOUR_SECONDS // WINDOW_SECONDS
COMPLETE_HOUR_ENTRY_LIMIT = 5000
MAX_QUERY_LENGTH = 1024
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
TIMEOUT_SECONDS = 30
MAX_RAW_BYTES = 8 * 1024 * 1024
MAX_SOURCE_MANIFEST_BYTES = 64 * 1024
MAX_COMPLETE_MANIFEST_BYTES = 128 * 1024
MAX_COMPLETE_RAW_BYTES = 32 * 1024 * 1024
SOURCE_MANIFEST_SCHEMA_VERSION = 1
COMPLETE_HOUR_SCHEMA_VERSION = 2
COMPLETE_HOUR_KIND = "flight_recorder_complete_hour"
COMPLETE_HOUR_STATUS = "complete"
SOURCE_PREFIX = "flight-recorder/"
COMPONENT_QUERIES = (
    ("workflow", '{k8s_namespace_name="airflow"}'),
    ("spark_operator", '{k8s_namespace_name="spark-system"}'),
    ("trino", '{k8s_namespace_name="iceberg-demo"} | k8s_pod_name=~"trino.*"'),
    ("seaweedfs", '{k8s_namespace_name="storage"} | k8s_pod_name=~"seaweedfs.*"'),
)
SOURCE_MANIFEST_FIELDS = frozenset({
    "schema_version",
    "query",
    "window_start",
    "window_end",
    "entry_count",
    "raw_bytes",
    "raw_key",
    "raw_sha256",
})
COMPLETE_HOUR_MANIFEST_FIELDS = frozenset({
    "schema_version",
    "kind",
    "status",
    "hour_start",
    "hour_end",
    "source_hour_id",
    "catalog_sha256",
    "component_count",
    "chunk_count",
    "source_count",
    "raw_bytes",
    "sources",
})
COMPLETE_HOUR_SOURCE_FIELDS = frozenset({
    "component",
    "chunk_index",
    "entry_limit",
    "max_response_bytes",
    "timeout_seconds",
    "manifest_key",
    "manifest_sha256",
    "query",
    "window_start",
    "window_end",
    "entry_count",
    "raw_bytes",
    "raw_key",
    "raw_sha256",
})
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_NANOSECONDS_PER_SECOND = 1_000_000_000
_SHA256 = re.compile(r"[0-9a-f]{64}")


def component_catalog_sha256() -> str:
    """Return the fixed Complete Hour catalog identity."""
    catalog = [
        {
            "component": component,
            "query": query,
            "entry_limit": COMPLETE_HOUR_ENTRY_LIMIT,
            "max_response_bytes": MAX_RESPONSE_BYTES,
            "timeout_seconds": TIMEOUT_SECONDS,
        }
        for component, query in COMPONENT_QUERIES
    ]
    payload = json.dumps(catalog, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def component_manifest_key(
    *,
    component: str,
    query: str,
    start_ns: int,
    end_ns: int,
    entry_limit: int = COMPLETE_HOUR_ENTRY_LIMIT,
    max_response_bytes: int = MAX_RESPONSE_BYTES,
    timeout_seconds: int = TIMEOUT_SECONDS,
) -> str:
    """Return the key for one contract-bound source manifest."""
    if (
        not isinstance(component, str)
        or not component
        or not component.isascii()
        or not component.replace("_", "").isalnum()
    ):
        raise ValueError("Complete Hour component was invalid")
    if not isinstance(query, str) or not query or len(query) > MAX_QUERY_LENGTH:
        raise ValueError("Complete Hour query was invalid")
    if (
        type(start_ns) is not int
        or type(end_ns) is not int
        or start_ns < 0
        or end_ns <= start_ns
    ):
        raise ValueError("Complete Hour source window was invalid")
    fences = (
        (entry_limit, COMPLETE_HOUR_ENTRY_LIMIT),
        (max_response_bytes, MAX_RESPONSE_BYTES),
        (timeout_seconds, TIMEOUT_SECONDS),
    )
    if any(type(value) is not int or not 1 <= value <= maximum for value, maximum in fences):
        raise ValueError("Complete Hour query fence was invalid")
    contract = {
        "component": component,
        "entry_limit": entry_limit,
        "max_response_bytes": max_response_bytes,
        "manifest_schema_version": SOURCE_MANIFEST_SCHEMA_VERSION,
        "max_raw_bytes": MAX_RAW_BYTES,
        "query": query,
        "complete_hour_schema_version": COMPLETE_HOUR_SCHEMA_VERSION,
        "timeout_seconds": timeout_seconds,
    }
    payload = json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()
    contract_sha256 = hashlib.sha256(payload).hexdigest()
    return (
        f"{SOURCE_PREFIX}component-manifests/"
        f"{start_ns}-{end_ns}/{contract_sha256}.json"
    )


def _content_key(
    *,
    kind: str,
    suffix: str,
    start_ns: int,
    end_ns: int,
    duration_seconds: int | None,
    checksum: str,
) -> str:
    if (
        type(start_ns) is not int
        or type(end_ns) is not int
        or start_ns < 0
        or end_ns <= start_ns
        or (
            duration_seconds is not None
            and end_ns - start_ns != duration_seconds * 1_000_000_000
        )
    ):
        raise ValueError("Complete Hour object window was invalid")
    if not isinstance(checksum, str) or re.fullmatch(r"[0-9a-f]{64}", checksum) is None:
        raise ValueError("Complete Hour object checksum was invalid")
    return f"{SOURCE_PREFIX}{kind}/{start_ns}-{end_ns}/{checksum}{suffix}"


def raw_key(*, start_ns: int, end_ns: int, checksum: str) -> str:
    """Return the content-addressed key for one raw source."""
    return _content_key(
        kind="raw",
        suffix=".jsonl",
        start_ns=start_ns,
        end_ns=end_ns,
        duration_seconds=None,
        checksum=checksum,
    )


def hour_manifest_key(*, start_ns: int, end_ns: int, checksum: str) -> str:
    """Return the content-addressed key for one Complete Hour."""
    return _content_key(
        kind="hours",
        suffix=".complete.json",
        start_ns=start_ns,
        end_ns=end_ns,
        duration_seconds=HOUR_SECONDS,
        checksum=checksum,
    )


def _utc_timestamp(value: object) -> tuple[datetime, int]:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("Complete Hour timestamp was invalid")
    try:
        timestamp = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ValueError("Complete Hour timestamp was invalid") from error
    if timestamp.utcoffset() != timedelta(0):
        raise ValueError("Complete Hour timestamp was invalid")
    if timestamp.isoformat().replace("+00:00", "Z") != value:
        raise ValueError("Complete Hour timestamp was not canonical")
    delta = timestamp - _EPOCH
    nanoseconds = (
        (delta.days * 86400 + delta.seconds) * _NANOSECONDS_PER_SECOND
        + delta.microseconds * 1000
    )
    return timestamp, nanoseconds


def _iso_utc(nanoseconds: int) -> str:
    seconds, remainder = divmod(nanoseconds, _NANOSECONDS_PER_SECOND)
    if remainder:
        raise ValueError("Complete Hour window was not second-aligned")
    return (_EPOCH + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def _valid_checksum(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _validate_complete_hour_manifest(manifest: Mapping[str, object]) -> None:
    if set(manifest) != COMPLETE_HOUR_MANIFEST_FIELDS:
        raise ValueError("Complete Hour manifest fields were invalid")
    sources = manifest.get("sources")
    expected_source_count = len(COMPONENT_QUERIES) * CHUNKS_PER_HOUR
    valid_header = (
        type(manifest.get("schema_version")) is int
        and manifest.get("schema_version") == COMPLETE_HOUR_SCHEMA_VERSION
        and manifest.get("kind") == COMPLETE_HOUR_KIND
        and manifest.get("status") == COMPLETE_HOUR_STATUS
        and manifest.get("catalog_sha256") == component_catalog_sha256()
        and type(manifest.get("component_count")) is int
        and manifest.get("component_count") == len(COMPONENT_QUERIES)
        and type(manifest.get("chunk_count")) is int
        and manifest.get("chunk_count") == expected_source_count
        and isinstance(sources, (list, tuple))
        and len(sources) == expected_source_count
    )
    if not valid_header:
        raise ValueError("Complete Hour manifest identity was invalid")

    hour_start, start_ns = _utc_timestamp(manifest.get("hour_start"))
    hour_end, end_ns = _utc_timestamp(manifest.get("hour_end"))
    if (
        end_ns - start_ns != HOUR_SECONDS * _NANOSECONDS_PER_SECOND
        or any((hour_start.minute, hour_start.second, hour_start.microsecond,
                hour_end.minute, hour_end.second, hour_end.microsecond))
        or manifest.get("source_hour_id") != f"{start_ns}-{end_ns}"
    ):
        raise ValueError("Complete Hour geometry was invalid")

    expected_matrix = (
        (component, query, index)
        for component, query in COMPONENT_QUERIES
        for index in range(CHUNKS_PER_HOUR)
    )
    source_count = 0
    total_raw_bytes = 0
    chunk_ns = WINDOW_SECONDS * _NANOSECONDS_PER_SECOND
    for source, (component, query, index) in zip(sources, expected_matrix, strict=True):
        if not isinstance(source, Mapping) or set(source) != COMPLETE_HOUR_SOURCE_FIELDS:
            raise ValueError("Complete Hour source fields were invalid")
        window_start_ns = start_ns + index * chunk_ns
        window_end_ns = window_start_ns + chunk_ns
        raw_checksum = source.get("raw_sha256")
        manifest_checksum = source.get("manifest_sha256")
        valid_identity = (
            type(source.get("chunk_index")) is int
            and (source.get("component"), source.get("query"), source.get("chunk_index"))
            == (component, query, index)
            and type(source.get("entry_limit")) is int
            and source.get("entry_limit") == COMPLETE_HOUR_ENTRY_LIMIT
            and type(source.get("max_response_bytes")) is int
            and source.get("max_response_bytes") == MAX_RESPONSE_BYTES
            and type(source.get("timeout_seconds")) is int
            and source.get("timeout_seconds") == TIMEOUT_SECONDS
            and source.get("window_start") == _iso_utc(window_start_ns)
            and source.get("window_end") == _iso_utc(window_end_ns)
            and _valid_checksum(manifest_checksum)
            and _valid_checksum(raw_checksum)
        )
        if not valid_identity:
            raise ValueError("Complete Hour source identity was invalid")
        if source.get("manifest_key") != component_manifest_key(
            component=component,
            query=query,
            start_ns=window_start_ns,
            end_ns=window_end_ns,
        ):
            raise ValueError("Complete Hour source manifest key was invalid")
        if source.get("raw_key") != raw_key(
            start_ns=window_start_ns,
            end_ns=window_end_ns,
            checksum=raw_checksum,
        ):
            raise ValueError("Complete Hour source raw key was invalid")
        entry_count = source.get("entry_count")
        raw_bytes = source.get("raw_bytes")
        valid_counts = (
            type(entry_count) is int
            and 0 <= entry_count < COMPLETE_HOUR_ENTRY_LIMIT
            and type(raw_bytes) is int
            and 0 <= raw_bytes <= MAX_RAW_BYTES
            and (entry_count == 0) == (raw_bytes == 0)
        )
        if not valid_counts:
            raise ValueError("Complete Hour source counts were invalid")
        source_count += entry_count
        total_raw_bytes += raw_bytes

    if (
        type(manifest.get("source_count")) is not int
        or manifest.get("source_count") != source_count
        or type(manifest.get("raw_bytes")) is not int
        or manifest.get("raw_bytes") != total_raw_bytes
        or total_raw_bytes > MAX_COMPLETE_RAW_BYTES
    ):
        raise ValueError("Complete Hour source totals were invalid")


def encode_complete_hour_manifest(manifest: Mapping[str, object]) -> bytes:
    """Encode one Complete Hour manifest in its canonical wire form."""
    if not isinstance(manifest, Mapping):
        raise ValueError("Complete Hour manifest fields were invalid")
    _validate_complete_hour_manifest(manifest)
    payload = (
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    if len(payload) > MAX_COMPLETE_MANIFEST_BYTES:
        raise ValueError("Complete Hour manifest exceeded the byte limit")
    return payload
