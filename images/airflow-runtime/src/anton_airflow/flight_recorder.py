"""Manual Flight Recorder source capture and Spark submission."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import datetime, timedelta
import json
from typing import Any

from airflow.exceptions import AirflowException

from .loki import DEFAULT_LOKI_QUERY, LokiSnapshotExtractor, LokiWindow, extractor_from_environment, manifest_key
from .spark.identity import AttemptIdentity
from .spark.operator import ApacheSparkApplicationOperator


ExtractorFactory = Callable[[], tuple[LokiSnapshotExtractor, str]]


def _source_window(context: Mapping[str, Any]) -> LokiWindow:
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
    return LokiWindow.ending_at(end)


def _add_env(application_spec: dict[str, Any], values: Mapping[str, str]) -> None:
    spec = application_spec["spec"]
    for role in ("driver", "executor"):
        containers = spec[f"{role}Spec"]["podTemplateSpec"]["spec"]["containers"]
        current = {item["name"]: dict(item) for item in containers[0].get("env", [])}
        current.update({name: {"name": name, "value": value} for name, value in values.items()})
        containers[0]["env"] = list(current.values())


class FlightRecorderSparkOperator(ApacheSparkApplicationOperator):
    """Capture one explicit Loki window before an authoritative Spark Attempt."""

    template_fields = ApacheSparkApplicationOperator.template_fields + ("source_query",)

    def __init__(
        self, *, application_spec: Mapping[str, Any],
        source_query: str = DEFAULT_LOKI_QUERY,
        extractor_factory: ExtractorFactory = extractor_from_environment,
        target: str = "authoritative", **kwargs: Any,
    ) -> None:
        if target != "authoritative":
            raise ValueError("Flight Recorder must use the authoritative writer")
        super().__init__(application_spec=application_spec, target=target, **kwargs)
        self.source_query, self.extractor_factory = source_query, extractor_factory
        self._base_application_spec = deepcopy(dict(application_spec))

    def execute(self, context: Mapping[str, Any]) -> Any:
        window = _source_window(context)
        extractor, bucket = self.extractor_factory()
        manifest = extractor.capture(window=window, query=self.source_query)
        retained_manifest_key = manifest_key(query=self.source_query, window=window)
        window_id = f"{window.start_ns}-{window.end_ns}"
        raw_uri = f"s3a://{bucket}/{manifest.raw_key}"
        retained_manifest_uri = f"s3a://{bucket}/{retained_manifest_key}"
        values = {
            "FLIGHT_RECORDER_RAW_URI": raw_uri,
            "FLIGHT_RECORDER_MANIFEST_URI": retained_manifest_uri,
            "FLIGHT_RECORDER_RAW_SHA256": manifest.raw_sha256,
            "FLIGHT_RECORDER_SOURCE_WINDOW_ID": window_id,
        }
        self.application_spec = deepcopy(self._base_application_spec)
        metadata = self.application_spec.setdefault("metadata", {})
        annotations = metadata.setdefault("annotations", {})
        annotations.update({f"anton.io/{name.lower().replace('_', '-')}": value for name, value in values.items()})
        _add_env(self.application_spec, values)
        identity = AttemptIdentity.from_context(context)
        receipt = manifest.as_dict()
        receipt.update({"attempt": identity.name, "manifest_key": retained_manifest_key})
        self.log.info(
            "flight_recorder_source_receipt %s",
            json.dumps(receipt, sort_keys=True, separators=(",", ":")),
        )
        return super().execute(context)
