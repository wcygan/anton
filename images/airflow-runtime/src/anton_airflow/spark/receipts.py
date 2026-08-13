"""Durable, bounded receipts for Airflow-owned Spark Attempts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol


class ReceiptSink(Protocol):
    """Store one structured attempt receipt at an external logging boundary."""

    def record(self, receipt: Mapping[str, Any]) -> None: ...


class ReceiptBuffer:
    """Collect bounded structured receipts for one deferred trigger event."""

    def __init__(self, *, limit: int = 50) -> None:
        self.limit = limit
        self.items: list[dict[str, Any]] = []

    def record(self, receipt: Mapping[str, Any]) -> None:
        self.items.append(dict(receipt))
        del self.items[:-self.limit]


class LoggingReceiptSink:
    """Write JSON receipts to the Airflow task or triggerer log."""

    def __init__(self, logger: Any) -> None:
        self.logger = logger

    def record(self, receipt: Mapping[str, Any]) -> None:
        payload = {
            "receipt_schema": 1,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            **dict(receipt),
        }
        self.logger.info("spark_attempt_receipt %s", json.dumps(payload, sort_keys=True, default=str))
