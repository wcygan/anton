"""Deferrable trigger that observes SparkApplication and renews its Lease."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from airflow.triggers.base import BaseTrigger, TriggerEvent

from .receipts import ReceiptBuffer
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
        startup_timeout: float = 60.0,
    ) -> None:
        super().__init__()
        self.attempt_name = attempt_name
        self.target = target
        self.namespace = namespace
        self.kubernetes_conn_id = kubernetes_conn_id
        self.poll_interval = poll_interval
        self.startup_timeout = startup_timeout
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
                "startup_timeout": self.startup_timeout,
            },
        )

    async def run(self):
        # Import lazily so Airflow can deserialize this trigger without importing
        # the operator's provider hook in the triggerer process.
        from .operator import _airflow_adapter

        receipt_buffer = ReceiptBuffer()
        adapter = _airflow_adapter(
            conn_id=self.kubernetes_conn_id,
            namespace=self.namespace,
            target=self.target,
            receipt_logger=logging.getLogger("anton_airflow.spark.trigger"),
            receipt_sink=receipt_buffer,
        )
        monitor = adapter.monitor_attempt(
            self.attempt_name,
            interval=self.poll_interval,
            startup_timeout=self.startup_timeout,
        )
        while True:
            observation = await asyncio.to_thread(monitor.advance)
            if observation.state is AttemptState.ACTIVE:
                continue
            if observation.state is AttemptState.SUCCEEDED:
                self._finished = True
                yield TriggerEvent(
                    {"state": "succeeded", "attempt": self.attempt_name, "receipts": receipt_buffer.items[-50:]}
                )
                return
            if observation.state is AttemptState.FAILED:
                self._finished = True
                yield TriggerEvent(
                    {
                        "state": "failed",
                        "attempt": self.attempt_name,
                        "diagnostics": observation.diagnostics,
                        "receipts": receipt_buffer.items[-50:],
                    }
                )
                return
            self._finished = True
            yield TriggerEvent(
                {
                    "state": "ambiguous",
                    "attempt": self.attempt_name,
                    "diagnostics": observation.diagnostics,
                    "receipts": receipt_buffer.items[-50:],
                }
            )
            return

    async def cleanup(self) -> None:
        """Cancel deferred work when Airflow removes the trigger before completion."""
        if self._finished:
            return
        from .operator import _airflow_adapter

        adapter = _airflow_adapter(
            conn_id=self.kubernetes_conn_id,
            namespace=self.namespace,
            target=self.target,
            receipt_logger=logging.getLogger("anton_airflow.spark.trigger"),
        )
        await asyncio.to_thread(adapter.cancel_attempt, self.attempt_name)
