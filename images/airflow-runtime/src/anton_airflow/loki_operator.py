"""Airflow operator for one bounded Loki-to-shadow Spark Workflow Run."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from typing import Any, Callable, Mapping

from airflow.exceptions import AirflowException

from .loki import (
    DEFAULT_LOKI_QUERY,
    DEFAULT_WINDOW_SECONDS,
    LokiSnapshotExtractor,
    LokiWindow,
    extractor_from_environment,
)
from .shadow_validation import prior_shadow_output_is_valid
from .spark.identity import AttemptIdentity
from .spark.operator import ApacheSparkApplicationOperator


def _context_end(context: Mapping[str, Any]) -> Any:
    for key in ("data_interval_end", "logical_date", "execution_date"):
        value = context.get(key)
        if value is not None:
            return value
    dag_run = context.get("dag_run")
    run_after = getattr(dag_run, "run_after", None)
    if run_after is not None:
        return run_after
    raise AirflowException("Loki source Workflow Run requires an Airflow logical end time")


def _env_with(existing: Any, values: Mapping[str, str]) -> list[dict[str, str]]:
    result = [dict(item) for item in existing or [] if isinstance(item, Mapping) and item.get("name")]
    by_name = {item["name"]: item for item in result}
    for name, value in values.items():
        by_name[name] = {"name": name, "value": value}
    return list(by_name.values())


class LokiSourceSparkOperator(ApacheSparkApplicationOperator):
    """Extract a bounded Loki window, then submit the exact shadow Spark Attempt."""

    template_fields = ApacheSparkApplicationOperator.template_fields + ("source_query",)

    def __init__(
        self,
        *,
        application_spec: Mapping[str, Any],
        target: str = "shadow",
        source_query: str = DEFAULT_LOKI_QUERY,
        source_window_seconds: int = DEFAULT_WINDOW_SECONDS,
        source_max_entries: int = 1000,
        extractor_factory: Callable[..., LokiSnapshotExtractor] = extractor_from_environment,
        **kwargs: Any,
    ) -> None:
        if target != "shadow":
            raise ValueError("Loki source validation is shadow-only")
        super().__init__(
            application_spec=application_spec,
            target=target,
            prior_output_validator=prior_shadow_output_is_valid,
            **kwargs,
        )
        self.source_query = source_query
        self.source_window_seconds = source_window_seconds
        self.source_max_entries = source_max_entries
        self.extractor_factory = extractor_factory
        self._source_base_application_spec = deepcopy(dict(application_spec))

    def execute(self, context: Mapping[str, Any]) -> Any:
        if self.target != "shadow":
            raise AirflowException("Loki source cannot submit an authoritative Spark Attempt")
        window = LokiWindow.ending_at(_context_end(context), seconds=self.source_window_seconds)
        extractor = self.extractor_factory(max_entries=self.source_max_entries)
        snapshot = extractor.capture(query=self.source_query, window=window)
        identity = AttemptIdentity.from_context(context)
        source_hash = sha256(
            f"{self.source_query}\0{window.start_ns}\0{window.end_ns}".encode("utf-8")
        ).hexdigest()[:16]
        self.application_spec = deepcopy(self._source_base_application_spec)
        metadata = dict(self.application_spec.get("metadata") or {})
        annotations = dict(metadata.get("annotations") or {})
        annotations.update(
            {
                "anton.io/source-kind": "loki",
                "anton.io/source-window-start": window.start.isoformat(),
                "anton.io/source-window-end": window.end.isoformat(),
                "anton.io/source-window-hash": source_hash,
                "anton.io/source-snapshot-key": snapshot.key,
            }
        )
        metadata["annotations"] = annotations
        self.application_spec["metadata"] = metadata
        spec = dict(self.application_spec.get("spec") or {})
        loki_env = {
            "LOKI_INPUT_URI": snapshot.uri,
            "LOKI_SOURCE_WINDOW_START": window.start.isoformat(),
            "LOKI_SOURCE_WINDOW_END": window.end.isoformat(),
            "LOKI_SOURCE_WINDOW_HASH": source_hash,
        }
        for role in ("driver", "executor"):
            role_spec = dict(spec.get(f"{role}Spec") or {})
            template = dict(role_spec.get("podTemplateSpec") or {})
            pod = dict(template.get("spec") or {})
            containers = [dict(item) for item in pod.get("containers") or []]
            if containers:
                containers[0]["env"] = _env_with(containers[0].get("env"), loki_env)
            pod["containers"] = containers
            template["spec"] = pod
            role_spec["podTemplateSpec"] = template
            spec[f"{role}Spec"] = role_spec
        self.application_spec["spec"] = spec
        self.log.info(
            "loki_source_receipt %s",
            json.dumps(
                {
                    "event": "loki_source_snapshot",
                    "attempt": identity.name,
                    "query": self.source_query,
                    "window_start": window.start.isoformat(),
                    "window_end": window.end.isoformat(),
                    "window_hash": source_hash,
                    "snapshot_key": snapshot.key,
                    "snapshot_uri": snapshot.uri,
                    "entries": snapshot.entries,
                    "bytes": snapshot.bytes_written,
                    "sha256": snapshot.sha256,
                    "target": "shadow",
                },
                sort_keys=True,
            ),
        )
        return super().execute(context)
