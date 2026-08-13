"""Deferrable trigger that observes SparkApplication and renews its Lease."""

from __future__ import annotations

import asyncio
from typing import Any

from airflow.triggers.base import BaseTrigger, TriggerEvent

from .state import AttemptState


class SparkApplicationTrigger(BaseTrigger):
    """Poll the generic custom resource while renewing its exact writer Lease."""

    def __init__(
        self,
        *,
        attempt_name: str,
        target: str,
        namespace: str = "lakehouse",
        kubernetes_conn_id: str = "kubernetes_default",
        poll_interval: float = 10.0,
    ) -> None:
        super().__init__()
        self.attempt_name = attempt_name
        self.target = target
        self.namespace = namespace
        self.kubernetes_conn_id = kubernetes_conn_id
        self.poll_interval = poll_interval
        self._finished = False

    def serialize(self) -> tuple[str, dict[str, Any]]:
        return (
            "anton_airflow.spark.trigger.SparkApplicationTrigger",
            {
                "attempt_name": self.attempt_name,
                "target": self.target,
                "namespace": self.namespace,
                "kubernetes_conn_id": self.kubernetes_conn_id,
                "poll_interval": self.poll_interval,
            },
        )

    async def run(self):
        # Import lazily so Airflow can deserialize this trigger without importing
        # the operator's provider hook in the triggerer process.
        from .operator import _airflow_adapter

        adapter = _airflow_adapter(conn_id=self.kubernetes_conn_id, namespace=self.namespace, target=self.target)
        while True:
            observation = await asyncio.to_thread(adapter.observe, self.attempt_name)
            if observation.state is AttemptState.ACTIVE:
                await asyncio.to_thread(adapter.leases.renew, self.attempt_name)
                watcher = getattr(adapter.applications, "watch", None)
                if watcher is None:
                    await asyncio.sleep(self.poll_interval)
                else:
                    await asyncio.to_thread(
                        watcher,
                        namespace=self.namespace,
                        name=self.attempt_name,
                        timeout_seconds=max(1, int(self.poll_interval)),
                    )
                continue
            if observation.state is AttemptState.SUCCEEDED:
                await asyncio.to_thread(adapter.leases.release, self.attempt_name)
                self._finished = True
                yield TriggerEvent({"state": "succeeded", "attempt": self.attempt_name})
                return
            if observation.state is AttemptState.FAILED:
                diagnostics = await asyncio.to_thread(adapter.collect_diagnostics, self.attempt_name)
                await asyncio.to_thread(adapter.leases.release, self.attempt_name)
                self._finished = True
                yield TriggerEvent({"state": "failed", "attempt": self.attempt_name, "diagnostics": diagnostics})
                return
            diagnostics = await asyncio.to_thread(adapter.collect_diagnostics, self.attempt_name)
            self._finished = True
            yield TriggerEvent({"state": "ambiguous", "attempt": self.attempt_name, "diagnostics": diagnostics})
            return

    async def cleanup(self) -> None:
        """Cancel deferred work when Airflow removes the trigger before completion."""
        if self._finished:
            return
        from .operator import _airflow_adapter

        adapter = _airflow_adapter(conn_id=self.kubernetes_conn_id, namespace=self.namespace, target=self.target)
        await asyncio.to_thread(adapter.cancel_attempt, self.attempt_name)
