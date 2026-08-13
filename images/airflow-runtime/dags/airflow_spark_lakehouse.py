"""Scheduled shadow lakehouse workflow owned by Airflow."""

from __future__ import annotations

import pendulum

from airflow.sdk import dag

from anton_airflow.lakehouse import SHADOW_APPLICATION_SPEC
from anton_airflow.shadow_validation import prior_shadow_output_is_valid
from anton_airflow.spark import ApacheSparkApplicationOperator

# The shared specification resolves to this immutable Spark runtime digest.
# Keep the digest in this DAG so the shadow-gate validator has one source pin.
# image: 192.168.1.106/library/spark-runtime@sha256:28efc7381ed7560ee806aeead8ba864daf989126bdb8f0f5b7d668beeafcb056


@dag(
    dag_id="airflow_spark_lakehouse",
    schedule="23 * * * *",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    tags=["anton", "lakehouse", "spark"],
)
def airflow_spark_lakehouse():
    """Run one shadow Spark Attempt for each Airflow Workflow Run."""

    ApacheSparkApplicationOperator(
        task_id="run_shadow_spark_attempt",
        application_spec=SHADOW_APPLICATION_SPEC,
        target="shadow",
        namespace="lakehouse",
        prior_output_validator=prior_shadow_output_is_valid,
        poll_interval=10.0,
        deferrable=True,
    )


spark_lakehouse_dag = airflow_spark_lakehouse()
