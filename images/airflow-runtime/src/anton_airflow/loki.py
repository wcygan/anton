"""Bounded Loki extraction and deterministic S3 snapshot writing."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import PurePosixPath
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping, Protocol


DEFAULT_LOKI_ENDPOINT = "http://loki.observability.svc.cluster.local:3100"
DEFAULT_LOKI_QUERY = '{k8s_namespace_name=~"airflow|lakehouse"}'
DEFAULT_RAW_ENDPOINT = "http://seaweedfs-s3.storage.svc.cluster.local:8333"
DEFAULT_RAW_BUCKET = "iceberg-raw"
DEFAULT_WINDOW_SECONDS = 300
MAX_WINDOW_SECONDS = 900
DEFAULT_MAX_ENTRIES = 1000
MAX_ENTRIES = 5000
DEFAULT_TIMEOUT_SECONDS = 30
MAX_TIMEOUT_SECONDS = 60
MAX_QUERY_LENGTH = 1024
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024
_SAFE_KEY = re.compile(r"[^a-zA-Z0-9._/-]+")


class LokiSourceError(RuntimeError):
    """The source window or source response failed a bounded contract."""


@dataclass(frozen=True, slots=True)
class LokiWindow:
    """One explicit UTC interval accepted by Loki's range query endpoint."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        start = _as_utc(self.start)
        end = _as_utc(self.end)
        if end <= start:
            raise ValueError("Loki window end must be after start")
        duration = (end - start).total_seconds()
        if duration > MAX_WINDOW_SECONDS:
            raise ValueError(f"Loki window cannot exceed {MAX_WINDOW_SECONDS} seconds")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)

    @classmethod
    def ending_at(cls, end: datetime, *, seconds: int = DEFAULT_WINDOW_SECONDS) -> "LokiWindow":
        if not 1 <= seconds <= MAX_WINDOW_SECONDS:
            raise ValueError(f"window seconds must be between 1 and {MAX_WINDOW_SECONDS}")
        end = _as_utc(end)
        return cls(end - timedelta(seconds=seconds), end)

    @property
    def start_ns(self) -> str:
        return str(int(self.start.timestamp() * 1_000_000_000))

    @property
    def end_ns(self) -> str:
        return str(int(self.end.timestamp() * 1_000_000_000))

    @property
    def identifier(self) -> str:
        return f"{self.start_ns}-{self.end_ns}"


@dataclass(frozen=True, slots=True)
class LokiRecord:
    """One normalized source record written to the raw snapshot."""

    event_id: str
    ts: str
    service: str
    level: str
    message: str
    labels: Mapping[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "ts": self.ts,
            "service": self.service,
            "level": self.level,
            "message": self.message,
            "labels": dict(sorted(self.labels.items())),
        }


@dataclass(frozen=True, slots=True)
class LokiSnapshot:
    """The retained bounded input and its deterministic raw object identity."""

    window: LokiWindow
    query: str
    key: str
    uri: str
    entries: int
    bytes_written: int
    sha256: str


class HttpTransport(Protocol):
    def __call__(self, request: urllib.request.Request, *, timeout: int) -> bytes: ...


class ObjectWriter(Protocol):
    def put(self, *, key: str, payload: bytes) -> None: ...


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Loki window timestamps must include a timezone")
    return value.astimezone(timezone.utc)


def _read_response(response: Any, *, max_bytes: int) -> bytes:
    payload = response.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise LokiSourceError(f"Loki response exceeds {max_bytes} bytes")
    return payload


def _default_http_transport(request: urllib.request.Request, *, timeout: int) -> bytes:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return _read_response(response, max_bytes=MAX_RESPONSE_BYTES)
    except urllib.error.HTTPError as error:
        body = error.read(512).decode("utf-8", errors="replace")
        raise LokiSourceError(f"Loki returned HTTP {error.code}: {body}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise LokiSourceError(f"Loki request failed: {type(error).__name__}") from error


def _json_line(value: str) -> Mapping[str, Any] | None:
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, Mapping) else None


def _severity(value: Any, line: str) -> str:
    text = str(value or "").strip().lower()
    if text in {"fatal", "critical", "panic"}:
        return "fatal"
    if text in {"error", "err", "failed", "failure"}:
        return "error"
    if text in {"warn", "warning"}:
        return "warn"
    if text in {"debug", "trace"}:
        return text
    body = line.lower()
    if body.startswith(("fatal", "critical", "panic")):
        return "fatal"
    if body.startswith(("error", "err", "failed", "failure")):
        return "error"
    if body.startswith(("warn", "warning")):
        return "warn"
    if body.startswith("debug"):
        return "debug"
    if body.startswith("trace"):
        return "trace"
    return "info"


def _record_from_value(labels: Mapping[str, Any], timestamp: Any, line: Any) -> LokiRecord:
    raw_line = str(line)
    timestamp_text = str(timestamp)
    try:
        timestamp_ns = int(timestamp_text)
        timestamp_value = datetime.fromtimestamp(timestamp_ns / 1_000_000_000, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError) as error:
        raise LokiSourceError("Loki returned a non-nanosecond timestamp") from error
    parsed = _json_line(raw_line)
    message = raw_line
    level: Any = labels.get("severity") or labels.get("level")
    service: Any = (
        labels.get("service_name")
        or labels.get("service")
        or labels.get("app")
        or labels.get("job")
        or "unknown"
    )
    if parsed is not None:
        message = parsed.get("message") or parsed.get("msg") or parsed.get("body") or parsed.get("log") or raw_line
        level = level or parsed.get("level") or parsed.get("severity")
        service = parsed.get("service") or parsed.get("service_name") or service
    ts = timestamp_value.isoformat().replace("+00:00", "Z")
    fingerprint = json.dumps(dict(labels), sort_keys=True, separators=(",", ":"))
    event_id = hashlib.sha256(f"{fingerprint}\0{timestamp_text}\0{raw_line}".encode("utf-8")).hexdigest()
    return LokiRecord(
        event_id=event_id,
        ts=ts,
        service=str(service),
        level=_severity(level, raw_line),
        message=str(message),
        labels={str(key): str(value) for key, value in labels.items()},
    )


def _records_from_response(payload: Mapping[str, Any], *, limit: int) -> list[LokiRecord]:
    if payload.get("status") != "success":
        raise LokiSourceError("Loki response status was not success")
    data = payload.get("data")
    if not isinstance(data, Mapping) or data.get("resultType") != "streams":
        raise LokiSourceError("Loki response did not contain stream results")
    results = data.get("result")
    if not isinstance(results, list):
        raise LokiSourceError("Loki response streams were malformed")
    records: list[LokiRecord] = []
    for stream in results:
        if not isinstance(stream, Mapping):
            raise LokiSourceError("Loki response contained a malformed stream")
        labels = stream.get("stream")
        values = stream.get("values")
        if not isinstance(labels, Mapping) or not isinstance(values, list):
            raise LokiSourceError("Loki response stream omitted labels or values")
        for value in values:
            if not isinstance(value, (list, tuple)) or len(value) != 2:
                raise LokiSourceError("Loki response contained a malformed value")
            records.append(_record_from_value(labels, value[0], value[1]))
            if len(records) >= limit:
                # Loki's range API does not expose a portable "truncated"
                # bit. Treat the limit as a completeness fence instead of
                # silently ingesting a partial source window.
                raise LokiSourceError("Loki result reached the bounded entry limit")
    records.sort(key=lambda item: (item.ts, item.event_id))
    return records


class LokiClient:
    """Query Loki with a fixed timeout, interval, limit, and response bound."""

    def __init__(
        self,
        *,
        endpoint: str = DEFAULT_LOKI_ENDPOINT,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        transport: HttpTransport | None = None,
    ) -> None:
        parsed = urllib.parse.urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Loki endpoint must be an HTTP(S) URL")
        if not 1 <= timeout_seconds <= MAX_TIMEOUT_SECONDS:
            raise ValueError(f"timeout must be between 1 and {MAX_TIMEOUT_SECONDS} seconds")
        self.endpoint = endpoint.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.transport = transport or _default_http_transport

    def query_range(self, *, query: str, window: LokiWindow, limit: int = DEFAULT_MAX_ENTRIES) -> list[LokiRecord]:
        if not query or len(query) > MAX_QUERY_LENGTH:
            raise ValueError(f"query must contain 1-{MAX_QUERY_LENGTH} characters")
        if not 1 <= limit <= MAX_ENTRIES:
            raise ValueError(f"limit must be between 1 and {MAX_ENTRIES}")
        params = urllib.parse.urlencode(
            {
                "query": query,
                "start": window.start_ns,
                "end": window.end_ns,
                "limit": str(limit),
                "direction": "forward",
            }
        )
        request = urllib.request.Request(
            f"{self.endpoint}/loki/api/v1/query_range?{params}",
            headers={"Accept": "application/json"},
            method="GET",
        )
        bearer = os.getenv("LOKI_BEARER_TOKEN")
        if bearer:
            request.add_header("Authorization", f"Bearer {bearer}")
        try:
            raw = self.transport(request, timeout=self.timeout_seconds)
            payload = json.loads(raw)
        except json.JSONDecodeError as error:
            raise LokiSourceError("Loki returned invalid JSON") from error
        if not isinstance(payload, Mapping):
            raise LokiSourceError("Loki returned a non-object response")
        return _records_from_response(payload, limit=limit)


def snapshot_lines(records: list[LokiRecord]) -> bytes:
    payload = "".join(
        json.dumps(record.as_dict(), sort_keys=True, separators=(",", ":")) + "\n"
        for record in records
    ).encode("utf-8")
    if len(payload) > MAX_SNAPSHOT_BYTES:
        raise LokiSourceError(f"Loki snapshot exceeds {MAX_SNAPSHOT_BYTES} bytes")
    return payload


def snapshot_key(*, query: str, window: LokiWindow) -> str:
    query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]
    return f"loki/snapshots/{window.identifier}-{query_hash}.jsonl"


class S3ObjectWriter:
    """Small path-style S3 PUT client with SigV4 and bounded payloads."""

    def __init__(
        self,
        *,
        endpoint: str = DEFAULT_RAW_ENDPOINT,
        bucket: str = DEFAULT_RAW_BUCKET,
        access_key: str,
        secret_key: str,
        region: str = "us-east-1",
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        opener: Any | None = None,
    ) -> None:
        parsed = urllib.parse.urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("S3 endpoint must be an HTTP(S) URL")
        if not bucket or "/" in bucket or ".." in bucket:
            raise ValueError("S3 bucket must be a simple bucket name")
        if not access_key or not secret_key:
            raise ValueError("S3 access and secret keys are required")
        if not 1 <= timeout_seconds <= MAX_TIMEOUT_SECONDS:
            raise ValueError(f"timeout must be between 1 and {MAX_TIMEOUT_SECONDS} seconds")
        self.endpoint = endpoint.rstrip("/")
        self.bucket = bucket
        self.access_key = access_key
        self.secret_key = secret_key
        self.region = region
        self.timeout_seconds = timeout_seconds
        self.opener = opener or urllib.request.urlopen

    def put(self, *, key: str, payload: bytes) -> None:
        if not key or len(key) > 512 or _SAFE_KEY.search(key) or ".." in PurePosixPath(key).parts:
            raise ValueError("S3 object key is unsafe or too long")
        if len(payload) > MAX_SNAPSHOT_BYTES:
            raise ValueError(f"S3 payload exceeds {MAX_SNAPSHOT_BYTES} bytes")
        now = datetime.now(timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        short_date = now.strftime("%Y%m%d")
        body_hash = hashlib.sha256(payload).hexdigest()
        path = "/" + urllib.parse.quote(self.bucket, safe="") + "/" + urllib.parse.quote(key, safe="/")
        parsed = urllib.parse.urlparse(self.endpoint)
        host = parsed.netloc
        canonical_headers = (
            f"content-type:application/x-ndjson\n"
            f"host:{host}\n"
            f"x-amz-content-sha256:{body_hash}\n"
            f"x-amz-date:{amz_date}\n"
        )
        signed_headers = "content-type;host;x-amz-content-sha256;x-amz-date"
        canonical_request = "\n".join(
            ("PUT", path, "", canonical_headers, signed_headers, body_hash)
        )
        scope = f"{short_date}/{self.region}/s3/aws4_request"
        string_to_sign = "\n".join(
            ("AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical_request.encode()).hexdigest())
        )
        signing_key = _signing_key(self.secret_key, short_date, self.region, "s3")
        signature = _hmac(signing_key, string_to_sign).hex()
        authorization = (
            f"AWS4-HMAC-SHA256 Credential={self.access_key}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        request = urllib.request.Request(
            f"{self.endpoint}{path}",
            data=payload,
            headers={
                "Authorization": authorization,
                "Content-Type": "application/x-ndjson",
                "Host": host,
                "X-Amz-Content-Sha256": body_hash,
                "X-Amz-Date": amz_date,
            },
            method="PUT",
        )
        try:
            with self.opener(request, timeout=self.timeout_seconds) as response:
                status = getattr(response, "status", 200)
                if status not in {200, 201, 204}:
                    raise LokiSourceError(f"S3 returned HTTP {status}")
        except urllib.error.HTTPError as error:
            raise LokiSourceError(f"S3 returned HTTP {error.code}") from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise LokiSourceError(f"S3 upload failed: {type(error).__name__}") from error


def _hmac(key: bytes, value: str) -> bytes:
    import hmac

    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret: str, date: str, region: str, service: str) -> bytes:
    date_key = _hmac(("AWS4" + secret).encode("utf-8"), date)
    region_key = _hmac(date_key, region)
    service_key = _hmac(region_key, service)
    return _hmac(service_key, "aws4_request")


class LokiSnapshotExtractor:
    """Capture one Loki window and retain it as a deterministic raw object."""

    def __init__(
        self,
        *,
        client: LokiClient,
        writer: ObjectWriter,
        bucket: str = DEFAULT_RAW_BUCKET,
        max_entries: int = DEFAULT_MAX_ENTRIES,
    ) -> None:
        if not 1 <= max_entries <= MAX_ENTRIES:
            raise ValueError(f"max_entries must be between 1 and {MAX_ENTRIES}")
        self.client = client
        self.writer = writer
        self.bucket = bucket
        self.max_entries = max_entries

    def capture(self, *, query: str, window: LokiWindow) -> LokiSnapshot:
        records = self.client.query_range(query=query, window=window, limit=self.max_entries)
        if not records:
            raise LokiSourceError("Loki source window returned no records")
        payload = snapshot_lines(records)
        key = snapshot_key(query=query, window=window)
        self.writer.put(key=key, payload=payload)
        return LokiSnapshot(
            window=window,
            query=query,
            key=key,
            uri=f"s3a://{self.bucket}/{key}",
            entries=len(records),
            bytes_written=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
        )


def extractor_from_environment(*, max_entries: int | None = None) -> LokiSnapshotExtractor:
    """Build the runtime extractor from non-secret environment settings."""
    access_key = os.getenv("RAW_ACCESS_KEY_ID")
    secret_key = os.getenv("RAW_SECRET_ACCESS_KEY")
    if not access_key or not secret_key:
        raise LokiSourceError("RAW_ACCESS_KEY_ID and RAW_SECRET_ACCESS_KEY are required")
    endpoint = os.getenv("LOKI_ENDPOINT", DEFAULT_LOKI_ENDPOINT)
    raw_endpoint = os.getenv("RAW_S3_ENDPOINT", DEFAULT_RAW_ENDPOINT)
    bucket = os.getenv("RAW_S3_BUCKET", DEFAULT_RAW_BUCKET)
    timeout = int(os.getenv("LOKI_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)))
    configured_max_entries = int(os.getenv("LOKI_MAX_ENTRIES", str(DEFAULT_MAX_ENTRIES)))
    return LokiSnapshotExtractor(
        client=LokiClient(endpoint=endpoint, timeout_seconds=timeout),
        writer=S3ObjectWriter(
            endpoint=raw_endpoint,
            bucket=bucket,
            access_key=access_key,
            secret_key=secret_key,
            timeout_seconds=timeout,
        ),
        bucket=bucket,
        max_entries=max_entries if max_entries is not None else configured_max_entries,
    )
