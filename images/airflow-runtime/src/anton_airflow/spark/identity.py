"""Stable identity and correlation metadata for Airflow Spark Attempts."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re
from typing import Any, Mapping


_INVALID_NAME = re.compile(r"[^a-z0-9-]+")


def bounded_identity(value: str, *, limit: int = 8) -> str:
    """Return a deterministic DNS-safe prefix with a bounded length."""
    normalized = _INVALID_NAME.sub("-", value.lower()).strip("-") or "unknown"
    return normalized[:limit].strip("-") or "unknown"


def identity_hash(*, dag_id: str, run_id: str, task_id: str, map_index: int | str) -> str:
    """Hash the four Airflow identity fields with NUL separators."""
    payload = "\0".join((dag_id, run_id, task_id, str(map_index))).encode("utf-8")
    return sha256(payload).hexdigest()[:12]


@dataclass(frozen=True, slots=True)
class AttemptIdentity:
    """The identity of one Airflow task attempt."""

    dag_id: str
    run_id: str
    task_id: str
    map_index: int
    try_number: int
    logical_date: str | None = None

    @property
    def hash(self) -> str:
        return identity_hash(
            dag_id=self.dag_id,
            run_id=self.run_id,
            task_id=self.task_id,
            map_index=self.map_index,
        )

    @property
    def name(self) -> str:
        return (
            f"lh-{bounded_identity(self.dag_id)}-{bounded_identity(self.task_id)}-"
            f"{self.hash}-a{self.try_number}"
        )

    @classmethod
    def from_context(cls, context: Mapping[str, Any]) -> "AttemptIdentity":
        """Build an identity from an Airflow task context without using logical date."""
        ti = context.get("ti") or context.get("task_instance")
        task = context.get("task")
        dag = context.get("dag")
        dag_id = str(context.get("dag_id") or getattr(dag, "dag_id", ""))
        task_id = str(context.get("task_id") or getattr(task, "task_id", ""))
        run_id = str(context.get("run_id") or getattr(context.get("dag_run"), "run_id", ""))
        map_index = int(context.get("map_index", getattr(ti, "map_index", -1)))
        try_number = int(context.get("try_number", getattr(ti, "try_number", 1)))
        logical_date = context.get("logical_date")
        if logical_date is not None:
            logical_date = logical_date.isoformat() if hasattr(logical_date, "isoformat") else str(logical_date)
        missing = [name for name, value in (("dag_id", dag_id), ("run_id", run_id), ("task_id", task_id)) if not value]
        if missing:
            raise ValueError(f"Airflow context is missing {', '.join(missing)}")
        if try_number < 1:
            raise ValueError("try_number must be positive")
        return cls(dag_id, run_id, task_id, map_index, try_number, logical_date)

    def labels(self, *, target: str) -> dict[str, str]:
        """Return bounded Kubernetes labels suitable for indexing."""
        return {
            "app.kubernetes.io/name": "lakehouse-spark",
            "app.kubernetes.io/part-of": "lakehouse",
            "anton.io/lakehouse-target": target,
            "anton.io/retain-failed-pod": "true",
            "anton.io/dag-id": bounded_identity(self.dag_id),
            "anton.io/task-id": bounded_identity(self.task_id),
            "anton.io/run-id": sha256(self.run_id.encode("utf-8")).hexdigest()[:12],
            "anton.io/identity-hash": self.hash,
            "anton.io/try-number": str(self.try_number),
        }

    def annotations(self) -> dict[str, str]:
        """Return complete Airflow identity annotations."""
        values = {
            "anton.io/dag-id": self.dag_id,
            "anton.io/run-id": self.run_id,
            "anton.io/task-id": self.task_id,
            "anton.io/map-index": str(self.map_index),
            "anton.io/try-number": str(self.try_number),
            "anton.io/identity-hash": self.hash,
            "anton.io/attempt-name": self.name,
        }
        if self.logical_date is not None:
            values["anton.io/logical-date"] = self.logical_date
        return values


def attempt_name(*, dag_id: str, run_id: str, task_id: str, map_index: int, try_number: int) -> str:
    """Return the stable custom-resource name for an Airflow attempt."""
    return AttemptIdentity(dag_id, run_id, task_id, map_index, try_number).name
