"""Manual authoritative lakehouse workflow owned by Airflow."""

from __future__ import annotations

import pendulum

from airflow.sdk import dag

from anton_airflow.lakehouse import AUTHORITATIVE_APPLICATION_SPEC
from anton_airflow.spark import ApacheSparkApplicationOperator

# The shared specification resolves to this immutable Spark runtime digest.
# Keep the digest in this DAG so the shadow-gate validator has one source pin.
# image: 192.168.1.106/library/spark-runtime@sha256:f76b38d07d0c0b1784e962073c918176f116359f7e3c8e82e0e0efbb939563e7


@dag(
    dag_id="airflow_spark_lakehouse",
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    tags=["anton", "lakehouse", "spark"],
)
def airflow_spark_lakehouse():
    """Run one authoritative Spark Attempt for each Airflow Workflow Run."""

    ApacheSparkApplicationOperator(
        task_id="run_authoritative_spark_attempt",
        application_spec=AUTHORITATIVE_APPLICATION_SPEC,
        target="authoritative",
        namespace="lakehouse",
        poll_interval=10.0,
        deferrable=True,
    )


spark_lakehouse_dag = airflow_spark_lakehouse()
