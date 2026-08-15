"""Pure Flight Recorder event-safety transformation."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import os
import re
import unicodedata


MAX_LINE_BYTES = 16 * 1024
MAX_PREVIEW_CHARS = 256
SPARK_REDACTION_REGEX = r"(?i)secret|password|token|access[._-]?key|credential|redaction"
MAX_MANIFEST_BYTES = 64 * 1024
MAX_RAW_BYTES = 8 * 1024 * 1024
MANIFEST_FIELDS = frozenset({
    "schema_version", "query", "window_start", "window_end", "entry_count",
    "raw_bytes", "raw_key", "raw_sha256",
})
CATALOG = "lake"
NAMESPACE = "flight_recorder"
WAREHOUSE = "s3://iceberg-warehouse"
EVENTS_TABLE = f"{CATALOG}.{NAMESPACE}.events"
HOURLY_TABLE = f"{CATALOG}.{NAMESPACE}.hourly"
RECEIPTS_TABLE = f"{CATALOG}.{NAMESPACE}.run_receipts"
RAW_SCHEMA_DDL = "timestamp string, labels map<string,string>, line string"
EVENT_SCHEMA_DDL = (
    "fingerprint string, event_timestamp timestamp, event_date date, source_window_id string, "
    "source_timestamp_ns string, namespace string, workload_kind string, workload_name string, "
    "pod_name string, container_name string, severity string, redacted_preview string, "
    "rejected boolean, rejection_reason string"
)
HOURLY_SCHEMA_DDL = (
    "hour timestamp, namespace string, workload_kind string, workload_name string, severity string, "
    "event_count bigint, rejection_count bigint"
)
RECEIPT_SCHEMA_DDL = (
    "source_window_id string, raw_sha256 string, manifest_uri string, raw_uri string, source_count bigint, "
    "accepted_count bigint, rejected_count bigint, final_event_count bigint, spark_attempt string, "
    "window_start timestamp, window_end timestamp, completed_at timestamp, completion_date date"
)
_TABLES = (
    (EVENTS_TABLE, EVENT_SCHEMA_DDL, "event_date", f"{WAREHOUSE}/flight_recorder/events"),
    (HOURLY_TABLE, HOURLY_SCHEMA_DDL, "days(hour)", f"{WAREHOUSE}/flight_recorder/hourly"),
    (RECEIPTS_TABLE, RECEIPT_SCHEMA_DDL, "completion_date", f"{WAREHOUSE}/flight_recorder/run_receipts"),
)
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


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    raw_uri: str
    manifest_uri: str
    raw_sha256: str
    source_window_id: str
    spark_attempt: str
    window_start: datetime
    window_end: datetime

    @classmethod
    def from_environment(cls, environ: Mapping[str, str]) -> RuntimeConfig:
        if environ.get("ANTON_LAKEHOUSE_TARGET") != "authoritative":
            raise FlightRecorderTransformError("Flight Recorder requires the authoritative target")
        if environ.get("FLIGHT_RECORDER_ICEBERG_NAMESPACE") != NAMESPACE:
            raise FlightRecorderTransformError("Flight Recorder namespace was invalid")
        if environ.get("ICEBERG_WAREHOUSE") != WAREHOUSE:
            raise FlightRecorderTransformError("Flight Recorder warehouse was invalid")
        raw_uri = _source_uri(environ.get("FLIGHT_RECORDER_RAW_URI"))
        manifest_uri = _source_uri(environ.get("FLIGHT_RECORDER_MANIFEST_URI"))
        checksum = environ.get("FLIGHT_RECORDER_RAW_SHA256", "")
        if re.fullmatch(r"[0-9a-f]{64}", checksum) is None:
            raise FlightRecorderTransformError("Flight Recorder checksum was invalid")
        window_id = environ.get("FLIGHT_RECORDER_SOURCE_WINDOW_ID", "")
        match = re.fullmatch(r"(\d{1,21})-(\d{1,21})", window_id)
        if match is None:
            raise FlightRecorderTransformError("Flight Recorder source window was invalid")
        start, end = _datetime_ns(match.group(1)), _datetime_ns(match.group(2))
        if end <= start:
            raise FlightRecorderTransformError("Flight Recorder source window was not ordered")
        attempt = environ.get("ANTON_SPARK_ATTEMPT", "")
        if not attempt or len(attempt) > 253 or not attempt.isascii():
            raise FlightRecorderTransformError("Flight Recorder Spark Attempt was invalid")
        return cls(raw_uri, manifest_uri, checksum, window_id, attempt, start, end)


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


def _datetime_ns(value: str) -> datetime:
    rendered, _ = _event_time(value)
    return datetime.fromisoformat(rendered.replace("Z", "+00:00"))


def _source_uri(value: str | None) -> str:
    prefix = "s3a://iceberg-raw/flight-recorder/"
    pattern = r"s3a://iceberg-raw/flight-recorder/[A-Za-z0-9._/-]+"
    if not value or len(value) > 1024 or re.fullmatch(pattern, value) is None or ".." in value or "//" in value[len(prefix):]:
        raise FlightRecorderTransformError("Flight Recorder source URI was invalid")
    return value


def validate_source(
    config: RuntimeConfig, manifest_payload: bytes, raw_payload: bytes,
) -> tuple[Mapping[str, object], ...]:
    """Validate one retained manifest and its exact raw bytes."""
    if not 1 <= len(manifest_payload) <= MAX_MANIFEST_BYTES or not 1 <= len(raw_payload) <= MAX_RAW_BYTES:
        raise FlightRecorderTransformError("Flight Recorder source object size was invalid")
    try:
        manifest = json.loads(manifest_payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise FlightRecorderTransformError("Flight Recorder manifest was invalid") from error
    if not isinstance(manifest, Mapping) or set(manifest) != MANIFEST_FIELDS:
        raise FlightRecorderTransformError("Flight Recorder manifest fields were invalid")
    expected_window = (
        config.window_start.isoformat().replace("+00:00", "Z"),
        config.window_end.isoformat().replace("+00:00", "Z"),
    )
    expected_key = f"flight-recorder/raw/{config.source_window_id}/{config.raw_sha256}.jsonl"
    if type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1:
        raise FlightRecorderTransformError("Flight Recorder manifest schema was invalid")
    if not isinstance(manifest["query"], str) or not manifest["query"] or len(manifest["query"]) > 1024:
        raise FlightRecorderTransformError("Flight Recorder manifest query was invalid")
    query_sha = hashlib.sha256(manifest["query"].encode()).hexdigest()
    expected_manifest_uri = f"s3a://iceberg-raw/flight-recorder/manifests/{config.source_window_id}/{query_sha}.json"
    if config.manifest_uri != expected_manifest_uri:
        raise FlightRecorderTransformError("Flight Recorder manifest identity conflicted")
    if (manifest["window_start"], manifest["window_end"]) != expected_window:
        raise FlightRecorderTransformError("Flight Recorder manifest window conflicted")
    if manifest["raw_key"] != expected_key or f's3a://iceberg-raw/{manifest["raw_key"]}' != config.raw_uri:
        raise FlightRecorderTransformError("Flight Recorder manifest raw identity conflicted")
    if type(manifest["raw_bytes"]) is not int or manifest["raw_bytes"] != len(raw_payload):
        raise FlightRecorderTransformError("Flight Recorder manifest byte count conflicted")
    checksum = hashlib.sha256(raw_payload).hexdigest()
    if manifest["raw_sha256"] != config.raw_sha256 or checksum != config.raw_sha256:
        raise FlightRecorderTransformError("Flight Recorder source checksum conflicted")
    if type(manifest["entry_count"]) is not int or manifest["entry_count"] < 1:
        raise FlightRecorderTransformError("Flight Recorder manifest entry count was invalid")
    try:
        entries = tuple(json.loads(line) for line in raw_payload.decode("utf-8").splitlines())
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise FlightRecorderTransformError("Flight Recorder raw source was invalid") from error
    if not raw_payload.endswith(b"\n") or len(entries) != manifest["entry_count"]:
        raise FlightRecorderTransformError("Flight Recorder raw entry count conflicted")
    if any(not isinstance(entry, Mapping) for entry in entries):
        raise FlightRecorderTransformError("Flight Recorder raw entry was invalid")
    for entry in entries:
        transform_entry(entry, source_window_id=config.source_window_id)
    return entries


def _read_binary(spark: object, uri: str, maximum: int) -> bytes:
    source = spark.read.format("binaryFile").load(uri)
    metadata = source.select("length").take(2)
    if len(metadata) != 1:
        raise FlightRecorderTransformError("Flight Recorder source object count was invalid")
    length = metadata[0]["length"]
    if type(length) is not int or not 1 <= length <= maximum:
        raise FlightRecorderTransformError("Flight Recorder binary source size was invalid")
    rows = source.select("length", "content").take(2)
    if len(rows) != 1:
        raise FlightRecorderTransformError("Flight Recorder source object count was invalid")
    retained_length, content = rows[0]["length"], rows[0]["content"]
    if type(retained_length) is not int or retained_length != length or not isinstance(content, (bytes, bytearray)):
        raise FlightRecorderTransformError("Flight Recorder binary source was invalid")
    payload = bytes(content)
    if length != len(payload):
        raise FlightRecorderTransformError("Flight Recorder binary source size was invalid")
    return payload


def validate_table_contract(table: str, columns: Sequence[tuple[str, str]], ddl: str) -> None:
    """Validate one existing Iceberg table before data writes."""
    try:
        _, schema, partition, location = next(item for item in _TABLES if item[0] == table)
    except StopIteration as error:
        raise FlightRecorderTransformError("Flight Recorder table identity was invalid") from error
    expected_columns = tuple(tuple(field.rsplit(" ", 1)) for field in schema.split(", "))
    provider = re.search(r"\bUSING\s+(\w+)", ddl, re.IGNORECASE)
    retained_location = re.search(r"\bLOCATION\s+['\"]([^'\"]+)['\"]", ddl, re.IGNORECASE)
    retained_partition = re.search(
        r"\bPARTITIONED\s+BY\s*\((.*?)\)\s*(?:LOCATION|TBLPROPERTIES|$)", ddl,
        re.IGNORECASE | re.DOTALL,
    )
    normalized = lambda value: re.sub(r"[`\s]", "", value).lower()
    valid = (
        tuple(columns) == expected_columns
        and provider is not None and provider.group(1).lower() == "iceberg"
        and retained_location is not None and retained_location.group(1) == location
        and retained_partition is not None and normalized(retained_partition.group(1)) == normalized(partition)
        and re.search(r"['\"]format-version['\"]\s*=\s*['\"]2['\"]", ddl) is not None
    )
    if not valid:
        raise FlightRecorderTransformError(f"Flight Recorder table contract differed: {table}")


def commit_in_order(write_events: Callable[[], None], write_hourly: Callable[[], None],
                    write_receipt: Callable[[], None]) -> None:
    """Commit non-atomic writes with the completion receipt last."""
    write_events()
    write_hourly()
    write_receipt()


def replay_is_complete(
    receipts: Sequence[Mapping[str, object]],
    *,
    source_window_id: str,
    raw_sha256: str,
    final_event_count: int,
) -> bool:
    """Validate one retained completion receipt before replay writes."""
    if not receipts:
        return False
    if len(receipts) != 1:
        raise FlightRecorderTransformError("Flight Recorder receipt identity was ambiguous")
    receipt = receipts[0]
    if receipt.get("source_window_id") != source_window_id or receipt.get("raw_sha256") != raw_sha256:
        raise FlightRecorderTransformError("Flight Recorder receipt checksum conflicted")
    if receipt.get("final_event_count") != final_event_count:
        raise FlightRecorderTransformError("Flight Recorder final event count conflicted")
    return True


def _spark_session():
    from pyspark.sql import SparkSession

    access_key, secret_key = os.getenv("AWS_ACCESS_KEY_ID"), os.getenv("AWS_SECRET_ACCESS_KEY")
    if not access_key or not secret_key:
        raise FlightRecorderTransformError("Flight Recorder warehouse credentials are required")
    credential = f"{access_key}:{secret_key}"
    return (
        SparkSession.builder.appName("flight-recorder")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.redaction.regex", SPARK_REDACTION_REGEX)
        .config("spark.redaction.string.regex", re.escape(credential))
        .config(f"spark.sql.catalog.{CATALOG}.credential", credential)
        .config(f"spark.sql.catalog.{CATALOG}", "org.apache.iceberg.spark.SparkCatalog")
        .config(f"spark.sql.catalog.{CATALOG}.catalog-impl", "org.apache.iceberg.rest.RESTCatalog")
        .config(f"spark.sql.catalog.{CATALOG}.uri", os.getenv("ICEBERG_CATALOG_URI"))
        .config(f"spark.sql.catalog.{CATALOG}.warehouse", WAREHOUSE)
        .config(f"spark.sql.catalog.{CATALOG}.io-impl", "org.apache.iceberg.aws.s3.S3FileIO")
        .config(f"spark.sql.catalog.{CATALOG}.s3.endpoint", os.getenv("S3_ENDPOINT"))
        .config(f"spark.sql.catalog.{CATALOG}.s3.path-style-access", "true")
        .config(f"spark.sql.catalog.{CATALOG}.s3.region", "us-east-1")
        .config("spark.sql.extensions", "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions")
        .getOrCreate()
    )


def _create_tables(spark: object) -> None:
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {CATALOG}.{NAMESPACE}")
    for table, schema, partition, location in _TABLES:
        spark.sql(
            f"CREATE TABLE IF NOT EXISTS {table} ({schema}) USING iceberg "
            f"PARTITIONED BY ({partition}) LOCATION '{location}' "
            "TBLPROPERTIES ('format-version'='2')"
        )


def _validate_tables(spark: object) -> None:
    for table, _, _, _ in _TABLES:
        fields = spark.table(table).schema.fields
        columns = tuple((field.name, field.dataType.simpleString()) for field in fields)
        ddl = "\n".join(str(row[0]) for row in spark.sql(f"SHOW CREATE TABLE {table}").collect())
        validate_table_contract(table, columns, ddl)


def _event_dict(row: object, source_window_id: str) -> dict[str, object]:
    event = transform_entry(row.asDict(recursive=True), source_window_id=source_window_id)
    output = asdict(event)
    output["event_timestamp"] = datetime.fromisoformat(event.event_timestamp.replace("Z", "+00:00"))
    output["event_date"] = date.fromisoformat(event.event_date)
    return output


def _write_events(spark: object, events: object) -> None:
    events.createOrReplaceTempView("flight_recorder_incoming_events")
    spark.sql(f"""MERGE INTO {EVENTS_TABLE} target USING flight_recorder_incoming_events source
      ON target.fingerprint = source.fingerprint WHEN MATCHED THEN UPDATE SET *
      WHEN NOT MATCHED THEN INSERT *""")


def _write_hourly(spark: object, events: object) -> None:
    hours = events.selectExpr("date_trunc('hour', event_timestamp) AS hour").distinct().collect()
    if not hours:
        raise FlightRecorderTransformError("Flight Recorder had no affected hourly partition")
    values = ", ".join(f"TIMESTAMP '{row['hour']:%Y-%m-%d %H:%M:%S}'" for row in hours)
    spark.sql(f"DELETE FROM {HOURLY_TABLE} WHERE hour IN ({values})")
    spark.sql(f"""INSERT INTO {HOURLY_TABLE}
      SELECT date_trunc('hour', event.event_timestamp), event.namespace, event.workload_kind,
        event.workload_name, event.severity, count(*),
        sum(CASE WHEN event.rejected THEN 1 ELSE 0 END)
      FROM {EVENTS_TABLE} event WHERE date_trunc('hour', event.event_timestamp) IN ({values})
      GROUP BY date_trunc('hour', event.event_timestamp), event.namespace,
        event.workload_kind, event.workload_name, event.severity""")


def main() -> None:
    from pyspark.sql import functions as F

    config = RuntimeConfig.from_environment(os.environ)
    spark = _spark_session()
    manifest_payload = _read_binary(spark, config.manifest_uri, MAX_MANIFEST_BYTES)
    raw_payload = _read_binary(spark, config.raw_uri, MAX_RAW_BYTES)
    source_entries = validate_source(config, manifest_payload, raw_payload)
    _create_tables(spark)
    _validate_tables(spark)
    retained = [row.asDict() for row in spark.table(RECEIPTS_TABLE).where(
        F.col("source_window_id") == config.source_window_id
    ).select("source_window_id", "raw_sha256", "final_event_count").collect()]
    final_count = spark.table(EVENTS_TABLE).where(F.col("source_window_id") == config.source_window_id).count()
    if replay_is_complete(
        retained,
        source_window_id=config.source_window_id,
        raw_sha256=config.raw_sha256,
        final_event_count=final_count,
    ):
        spark.stop()
        return
    raw = spark.createDataFrame(source_entries, RAW_SCHEMA_DDL)
    source_count = raw.count()
    if source_count < 1:
        raise FlightRecorderTransformError("Flight Recorder source was empty")
    events = spark.createDataFrame(
        raw.rdd.map(lambda row: _event_dict(row, config.source_window_id)), EVENT_SCHEMA_DDL
    ).cache()
    event_count = events.count()
    if event_count != source_count:
        raise FlightRecorderTransformError("Flight Recorder source count changed during transformation")
    rejected_count = events.where(F.col("rejected")).count()

    def write_receipt() -> None:
        completed_at = datetime.now(timezone.utc)
        receipt = {
            "source_window_id": config.source_window_id,
            "raw_sha256": config.raw_sha256,
            "manifest_uri": config.manifest_uri,
            "raw_uri": config.raw_uri,
            "source_count": source_count,
            "accepted_count": event_count - rejected_count,
            "rejected_count": rejected_count,
            "final_event_count": spark.table(EVENTS_TABLE).where(
                F.col("source_window_id") == config.source_window_id
            ).count(),
            "spark_attempt": config.spark_attempt,
            "window_start": config.window_start,
            "window_end": config.window_end,
            "completed_at": completed_at,
            "completion_date": completed_at.date(),
        }
        spark.createDataFrame([receipt], RECEIPT_SCHEMA_DDL).writeTo(RECEIPTS_TABLE).append()

    commit_in_order(
        lambda: _write_events(spark, events),
        lambda: _write_hourly(spark, events),
        write_receipt,
    )
    events.unpersist()
    spark.stop()


if __name__ == "__main__":
    main()
