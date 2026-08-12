"""Manual Workflow Run used to prove isolated KubernetesExecutor task pods."""

from __future__ import annotations

import json
import socket

from airflow.sdk import dag, get_current_context, task

from anton_airflow.spark import foundation_marker


@dag(
    dag_id="airflow_kubernetes_foundation",
    schedule=None,
    catchup=False,
    max_active_runs=1,
    tags=["anton", "lakehouse", "foundation"],
)
def airflow_kubernetes_foundation():
    """Run one bounded task in a KubernetesExecutor worker pod."""

    @task(task_id="prove_kubernetes_task_pod")
    def prove_kubernetes_task_pod() -> dict[str, str]:
        context = get_current_context()
        marker = foundation_marker(
            run_id=context["run_id"],
            pod_name=socket.gethostname(),
        )
        print(json.dumps({"event": "airflow-foundation-pass", **marker}, sort_keys=True))
        return marker

    prove_kubernetes_task_pod()


foundation_dag = airflow_kubernetes_foundation()
