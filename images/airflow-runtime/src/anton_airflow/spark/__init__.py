"""Airflow adapter for Apache Spark Operator custom resources."""

from __future__ import annotations

import platform
from importlib.metadata import version

import airflow


PACKAGE_VERSION = "0.2.0"

from .adapter import AttemptObservation, SparkApplicationAdapter, build_spark_application
from .identity import AttemptIdentity, attempt_name, identity_hash
from .operator import ApacheSparkApplicationOperator
from .state import AttemptState, classify_application
from .trigger import SparkApplicationTrigger


def foundation_marker(*, run_id: str, pod_name: str) -> dict[str, str]:
    """Return the runtime identity used by the ticket 04 task-pod probe."""
    return {
        "adapter_package": PACKAGE_VERSION,
        "airflow": airflow.__version__,
        "kubernetes_provider": version("apache-airflow-providers-cncf-kubernetes"),
        "pod_name": pod_name,
        "python": platform.python_version(),
        "run_id": run_id,
    }
