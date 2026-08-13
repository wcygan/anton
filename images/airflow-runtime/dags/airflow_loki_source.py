"""Manual, bounded Loki-source Workflow Run for the shadow lakehouse."""

from __future__ import annotations

import pendulum

from airflow.sdk import dag
from kubernetes.client import models as k8s

from anton_airflow.lakehouse import LOKI_APPLICATION_SPEC
from anton_airflow.loki import DEFAULT_LOKI_QUERY
from anton_airflow.loki_operator import LokiSourceSparkOperator


# The raw credential is scoped to iceberg-raw and is needed only by the
# Airflow worker that performs the bounded snapshot PUT. Spark receives a
# separate lakehouse Secret with bucket-specific S3A credentials.
LOKI_SOURCE_AIRFLOW_EXECUTOR_CONFIG = {
    "pod_override": k8s.V1Pod(
        spec=k8s.V1PodSpec(
            containers=[
                k8s.V1Container(
                    name="base",
                    env_from=[
                        k8s.V1EnvFromSource(
                            secret_ref=k8s.V1SecretEnvSource(name="loki-source-raw")
                        )
                    ],
                )
            ]
        )
    )
}


@dag(
    dag_id="airflow_loki_source",
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    tags=["anton", "lakehouse", "loki", "shadow"],
)
def airflow_loki_source():
    """Capture one five-minute Loki window and process it in shadow tables."""

    LokiSourceSparkOperator(
        task_id="run_loki_source_spark_attempt",
        application_spec=LOKI_APPLICATION_SPEC,
        source_query=DEFAULT_LOKI_QUERY,
        source_window_seconds=300,
        source_max_entries=1000,
        target="shadow",
        namespace="lakehouse",
        executor_config=LOKI_SOURCE_AIRFLOW_EXECUTOR_CONFIG,
        poll_interval=10.0,
        deferrable=True,
    )


loki_source_dag = airflow_loki_source()
