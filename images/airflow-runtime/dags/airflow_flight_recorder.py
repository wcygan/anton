"""Manual authoritative Flight Recorder workflow."""

from __future__ import annotations

import pendulum

from airflow.sdk import dag
from kubernetes.client import models as k8s

from anton_airflow.flight_recorder import FlightRecorderSparkOperator
from anton_airflow.lakehouse import FLIGHT_RECORDER_APPLICATION_SPEC


_RAW_SECRET = k8s.V1EnvFromSource(
    secret_ref=k8s.V1SecretEnvSource(name="flight-recorder-raw-s3")
)
_RAW_CONTAINER = k8s.V1Container(name="base", env_from=[_RAW_SECRET])
FLIGHT_RECORDER_EXECUTOR_CONFIG = {
    "pod_override": k8s.V1Pod(spec=k8s.V1PodSpec(containers=[_RAW_CONTAINER]))
}


@dag(
    dag_id="airflow_flight_recorder",
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    tags=["anton", "lakehouse", "flight-recorder"],
)
def airflow_flight_recorder():
    """Capture one complete closed hour and submit one Spark Attempt."""
    FlightRecorderSparkOperator(
        task_id="run_flight_recorder_spark_attempt",
        application_spec=FLIGHT_RECORDER_APPLICATION_SPEC,
        target="authoritative",
        namespace="lakehouse",
        executor_config=FLIGHT_RECORDER_EXECUTOR_CONFIG,
        poll_interval=10.0,
        deferrable=True,
    )


flight_recorder_dag = airflow_flight_recorder()
