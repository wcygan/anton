"""Pure Flight Recorder event-safety transformation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
import unicodedata


MAX_LINE_BYTES = 16 * 1024
MAX_PREVIEW_CHARS = 256
_WORKLOAD_LABELS = (
    ("deployment", "k8s_deployment_name"),
    ("statefulset", "k8s_statefulset_name"),
    ("daemonset", "k8s_daemonset_name"),
    ("job", "k8s_job_name"),
    ("cronjob", "k8s_cronjob_name"),
)
_SEVERITY = {
    "trace": "trace",
    "debug": "debug",
    "info": "info",
    "information": "info",
    "notice": "info",
    "warn": "warn",
    "warning": "warn",
    "err": "error",
    "error": "error",
    "critical": "fatal",
    "fatal": "fatal",
    "panic": "fatal",
}
_SAFE_ASSIGNMENT_VALUES = {"code": r"[0-9]{1,10}", "count": r"[0-9]{1,10}",
                           "method": r"(?:CONNECT|DELETE|GET|HEAD|OPTIONS|PATCH|POST|PUT|TRACE)",
                           "status": r"(?i:(?:[1-5][0-9]{2}|ok|success|failed|error|running|completed|pending|skipped|retrying))"}
_ASSIGNMENT = re.compile(
    r'''(?ix)(?P<prefix>(?<![a-z0-9_.-])(?P<quote>["']?)(?P<key>[a-z][a-z0-9_.-]{0,63})(?P=quote)\s*[:=]\s*)(?!//)'''
    r'''(?P<value>"[^"\r\n]*"|'[^'\r\n]*'|(?!["'])[^\s,;&}\r\n]+)''')
_ASSIGNMENT_HINT = re.compile(r'''(?ix)(?<![a-z0-9_.-])["']?(?P<key>[a-z][a-z0-9_.-]*)["']?\s*[:=]\s*(?!//)''')
_PRIVATE_KEY = re.compile(r"(?i)-----BEGIN [^-\r\n]{0,64}PRIVATE KEY-----")
_SOURCE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")


class FlightRecorderTransformError(ValueError):
    """A raw entry did not satisfy the retained source contract."""


@dataclass(frozen=True, slots=True)
class FlightRecorderEvent:
    fingerprint: str
    event_timestamp: str
    event_date: str
    source_window_id: str
    source_timestamp_ns: str
    namespace: str
    workload_kind: str
    workload_name: str
    pod_name: str
    container_name: str
    severity: str
    redacted_preview: str | None
    rejected: bool
    rejection_reason: str | None


def _identity(labels: Mapping[str, str]) -> dict[str, str]:
    workload_kind, workload_name = "unknown", "unknown"
    for kind, label in _WORKLOAD_LABELS:
        if labels.get(label):
            workload_kind, workload_name = kind, labels[label]
            break
    severity_text = labels.get("severity") or labels.get("level") or ""
    return {
        "namespace": labels.get("k8s_namespace_name") or "unknown",
        "workload_kind": workload_kind,
        "workload_name": workload_name,
        "pod_name": labels.get("k8s_pod_name") or "unknown",
        "container_name": labels.get("k8s_container_name") or "unknown",
        "severity": _SEVERITY.get(severity_text.strip().lower(), "unknown"),
    }


def _event_time(timestamp: str) -> tuple[str, str]:
    if not timestamp.isascii() or not timestamp.isdigit() or not 1 <= len(timestamp) <= 21:
        raise FlightRecorderTransformError("timestamp must be a nanosecond string")
    seconds, nanoseconds = divmod(int(timestamp), 1_000_000_000)
    try:
        value = datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OverflowError, OSError, ValueError) as error:
        raise FlightRecorderTransformError("timestamp was outside the UTC range") from error
    rendered = f"{value:%Y-%m-%dT%H:%M:%S}.{nanoseconds:09d}Z"
    return rendered, value.date().isoformat()


def _rejection_reason(line: str, encoded: bytes) -> str | None:
    if len(encoded) > MAX_LINE_BYTES:
        return "line_exceeds_16_kib"
    if any(unicodedata.category(character) == "Cc" and character not in "\t\n\r" for character in line):
        return "disallowed_control_character"
    if _PRIVATE_KEY.search(line):
        return "private_key_marker"
    return None


def _redact(line: str) -> str | None:
    def retained(match: re.Match[str]) -> bool:
        value = match.group("value")
        value = value[1:-1] if value[0] in "\"'" else value
        return re.fullmatch(_SAFE_ASSIGNMENT_VALUES.get(match.group("key").lower(), r"(?!x)x"), value) is not None
    assignments = tuple(_ASSIGNMENT.finditer(line))
    if any(all(not (match.start() <= hint.start() < match.end()) for match in assignments)
           for hint in _ASSIGNMENT_HINT.finditer(line)):
        return None
    preview = " ".join(
        match.group(0) if retained(match)
        else f'{match.group("prefix")}[REDACTED]' for match in assignments
    )
    return (preview or "[REDACTED]")[:MAX_PREVIEW_CHARS]


def transform_entry(entry: object, *, source_window_id: str) -> FlightRecorderEvent:
    """Return one immutable safe event from one retained raw entry."""
    if not isinstance(entry, Mapping) or set(entry) != {"timestamp", "labels", "line"}:
        raise FlightRecorderTransformError("raw entry fields were malformed")
    timestamp, labels, line = entry["timestamp"], entry["labels"], entry["line"]
    if not isinstance(timestamp, str) or not isinstance(labels, Mapping) or not isinstance(line, str):
        raise FlightRecorderTransformError("raw entry types were malformed")
    if any(not isinstance(key, str) or not isinstance(value, str) for key, value in labels.items()):
        raise FlightRecorderTransformError("raw entry labels were malformed")
    if not isinstance(source_window_id, str) or _SOURCE_ID.fullmatch(source_window_id) is None:
        raise FlightRecorderTransformError("source window identity was malformed")
    event_timestamp, event_date = _event_time(timestamp)
    try:
        encoded = line.encode("utf-8")
    except UnicodeEncodeError as error:
        raise FlightRecorderTransformError("raw line was not valid Unicode") from error
    identity = _identity(labels)
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(f"{source_window_id}\0{timestamp}\0{canonical}\0{line}".encode()).hexdigest()
    reason = _rejection_reason(line, encoded)
    preview = None if reason else _redact(line)
    reason = reason or ("redaction_failed" if preview is None else None)
    return FlightRecorderEvent(
        fingerprint=fingerprint,
        event_timestamp=event_timestamp,
        event_date=event_date,
        source_window_id=source_window_id,
        source_timestamp_ns=timestamp,
        **identity,
        redacted_preview=preview,
        rejected=reason is not None,
        rejection_reason=reason,
    )
