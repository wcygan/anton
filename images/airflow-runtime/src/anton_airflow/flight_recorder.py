"""Manual Flight Recorder source capture and Spark submission."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from typing import Any

from airflow.exceptions import AirflowException

from .loki import (
    COMPONENT_QUERIES,
    LokiHour,
    LokiSnapshotExtractor,
    LokiSourceError,
    extractor_from_environment,
    hour_manifest_key,
)
from .spark.identity import AttemptIdentity
from .spark.operator import ApacheSparkApplicationOperator


ExtractorFactory = Callable[[], tuple[LokiSnapshotExtractor, str]]


def _source_hour(context: Mapping[str, Any]) -> LokiHour:
    dag_run = context.get("dag_run")
    conf = getattr(dag_run, "conf", None)
    value = conf.get("source_window_end") if isinstance(conf, Mapping) else None
    if not isinstance(value, str):
        raise AirflowException("dag_run.conf.source_window_end must be an ISO-8601 UTC string")
    try:
        end = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise AirflowException("dag_run.conf.source_window_end was not valid ISO-8601") from error
    if end.tzinfo is None or end.utcoffset() != timedelta(0):
        raise AirflowException("dag_run.conf.source_window_end must use UTC")
    try:
        hour = LokiHour.ending_at(end)
    except ValueError as error:
        raise AirflowException("dag_run.conf.source_window_end must be a UTC hour boundary") from error
    latest_closed_end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    if hour.end > latest_closed_end:
        raise AirflowException("dag_run.conf.source_window_end must select a closed UTC hour")
    return hour


def _add_env(application_spec: dict[str, Any], values: Mapping[str, str]) -> None:
    spec = application_spec["spec"]
    for role in ("driver", "executor"):
        containers = spec[f"{role}Spec"]["podTemplateSpec"]["spec"]["containers"]
        current = {item["name"]: dict(item) for item in containers[0].get("env", [])}
        current.update({name: {"name": name, "value": value} for name, value in values.items()})
        containers[0]["env"] = list(current.values())


class FlightRecorderSparkOperator(ApacheSparkApplicationOperator):
    """Capture one complete platform hour before an authoritative Spark Attempt."""

    template_fields = ApacheSparkApplicationOperator.template_fields

    def __init__(
        self, *, application_spec: Mapping[str, Any],
        extractor_factory: ExtractorFactory = extractor_from_environment,
        target: str = "authoritative", **kwargs: Any,
    ) -> None:
        if target != "authoritative":
            raise ValueError("Flight Recorder must use the authoritative writer")
        super().__init__(application_spec=application_spec, target=target, **kwargs)
        self.extractor_factory = extractor_factory
        self._base_application_spec = deepcopy(dict(application_spec))

    def execute(self, context: Mapping[str, Any]) -> Any:
        hour = _source_hour(context)
        extractor, bucket = self.extractor_factory()
        identity = AttemptIdentity.from_context(context)
        try:
            manifest = extractor.capture_hour(hour=hour)
        except LokiSourceError as error:
            rejection = {
                "source_hour_id": f"{hour.start_ns}-{hour.end_ns}",
                "attempt": identity.name,
                "component": getattr(error, "component", "complete_manifest"),
                "chunk_index": getattr(error, "chunk_index", -1),
                "completed_queries": getattr(error, "completed_queries", len(COMPONENT_QUERIES) * 12),
                "complete_manifest_published": getattr(error, "complete_manifest_published", False),
            }
            self.log.info(
                "flight_recorder_hour_rejection %s",
                json.dumps(rejection, sort_keys=True, separators=(",", ":")),
            )
            raise AirflowException("Flight Recorder rejected the complete source hour") from error
        retained_manifest_key = hour_manifest_key(hour=hour, checksum=manifest.manifest_sha256)
        values = {
            "FLIGHT_RECORDER_COMPLETE_MANIFEST_URI": f"s3a://{bucket}/{retained_manifest_key}",
            "FLIGHT_RECORDER_COMPLETE_MANIFEST_SHA256": manifest.manifest_sha256,
            "FLIGHT_RECORDER_SOURCE_HOUR_ID": manifest.source_hour_id,
        }
        self.application_spec = deepcopy(self._base_application_spec)
        metadata = self.application_spec.setdefault("metadata", {})
        annotations = metadata.setdefault("annotations", {})
        annotations.update({f"anton.io/{name.lower().replace('_', '-')}": value for name, value in values.items()})
        _add_env(self.application_spec, values)
        receipt = {
            name: getattr(manifest, name)
            for name in (
                "schema_version", "kind", "status", "hour_start", "hour_end",
                "source_hour_id", "catalog_sha256", "component_count", "chunk_count",
                "source_count", "raw_bytes",
            )
        }
        receipt.update({
            "attempt": identity.name,
            "manifest_key": retained_manifest_key,
            "manifest_sha256": manifest.manifest_sha256,
        })
        self.log.info(
            "flight_recorder_hour_receipt %s",
            json.dumps(receipt, sort_keys=True, separators=(",", ":")),
        )
        return super().execute(context)
