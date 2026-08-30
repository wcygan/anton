"""Airflow deferrable operator for generic Apache SparkApplication resources."""

from __future__ import annotations

import logging
from typing import Any, Mapping

from airflow.exceptions import AirflowException
from airflow.models import BaseOperator

from .adapter import KubernetesSparkApplicationClient, SparkApplicationAdapter
from .identity import AttemptIdentity
from .lease import LeaseCoordinator
from .receipts import LoggingReceiptSink, ReceiptSink
from .trigger import SparkApplicationTrigger


def _airflow_adapter(
    *,
    conn_id: str,
    namespace: str,
    target: str,
    receipt_logger: Any | None = None,
    receipt_sink: ReceiptSink | None = None,
) -> SparkApplicationAdapter:
    from kubernetes import client
    from airflow.providers.cncf.kubernetes.hooks.kubernetes import KubernetesHook

    hook = KubernetesHook(conn_id=conn_id)
    api_client = hook.get_conn()
    custom = client.CustomObjectsApi(api_client)
    coordination = client.CoordinationV1Api(api_client)
    core = client.CoreV1Api(api_client)

    def lease_dict(value: Any) -> dict[str, Any]:
        """Convert the Python client's Lease model to Kubernetes JSON field names."""
        metadata = getattr(value, "metadata", None)
        spec = getattr(value, "spec", None)
        return {
            "metadata": {
                "name": getattr(metadata, "name", None),
                "namespace": getattr(metadata, "namespace", None),
                "resourceVersion": getattr(metadata, "resource_version", None),
                "uid": getattr(metadata, "uid", None),
            },
            "spec": {
                "holderIdentity": getattr(spec, "holder_identity", None),
                "leaseDurationSeconds": getattr(spec, "lease_duration_seconds", None),
                "renewTime": getattr(spec, "renew_time", None),
            },
        }

    class LeaseApi:
        def get_namespaced_lease(self, name: str, namespace: str) -> Mapping[str, Any]:
            return lease_dict(coordination.read_namespaced_lease(name, namespace))

        def create_namespaced_lease(self, namespace: str, body: Mapping[str, Any]) -> Mapping[str, Any]:
            return coordination.create_namespaced_lease(namespace, body).to_dict()

        def replace_namespaced_lease(self, name: str, namespace: str, body: Mapping[str, Any]) -> Mapping[str, Any]:
            return coordination.replace_namespaced_lease(name, namespace, body).to_dict()

        def delete_namespaced_lease(
            self,
            name: str,
            namespace: str,
            *,
            body: Mapping[str, Any] | None = None,
        ) -> Any:
            return coordination.delete_namespaced_lease(
                name,
                namespace,
                body=body,
            )

    class Pods:
        def list_pods(self, *, namespace: str, label_selector: str) -> list[Mapping[str, Any]]:
            return [item.to_dict() for item in core.list_namespaced_pod(namespace, label_selector=label_selector).items]

        def read_log(self, *, namespace: str, name: str, container: str) -> str:
            return core.read_namespaced_pod_log(name, namespace, container=container, tail_lines=200)

        def list_events(self, *, namespace: str, field_selector: str) -> list[Mapping[str, Any]]:
            return [item.to_dict() for item in core.list_namespaced_event(namespace, field_selector=field_selector).items]

    return SparkApplicationAdapter(
        applications=KubernetesSparkApplicationClient(custom),
        leases=LeaseCoordinator(LeaseApi(), namespace=namespace, target=target),
        pods=Pods(),
        namespace=namespace,
        receipts=receipt_sink or LoggingReceiptSink(receipt_logger or logging.getLogger("anton_airflow.spark")),
    )


class ApacheSparkApplicationOperator(BaseOperator):
    """Create one idempotent SparkApplication and defer while it runs."""

    template_fields = ("application_spec", "target")

    def __init__(
        self,
        *,
        application_spec: Mapping[str, Any],
        target: str = "shadow",
        namespace: str = "lakehouse",
        kubernetes_conn_id: str = "kubernetes_default",
        prior_output_validator: Any | None = None,
        poll_interval: float = 10.0,
        deferrable: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.application_spec = dict(application_spec)
        self.target = target
        self.namespace = namespace
        self.kubernetes_conn_id = kubernetes_conn_id
        self.prior_output_validator = prior_output_validator
        self.poll_interval = poll_interval
        self.deferrable = deferrable
        self._identity: AttemptIdentity | None = None

    def execute(self, context: Mapping[str, Any]) -> Any:
        self._identity = AttemptIdentity.from_context(context)
        adapter = _airflow_adapter(
            conn_id=self.kubernetes_conn_id,
            namespace=self.namespace,
            target=self.target,
            receipt_logger=self.log,
        )
        previous_identity = AttemptIdentity(
            self._identity.dag_id,
            self._identity.run_id,
            self._identity.task_id,
            self._identity.map_index,
            self._identity.try_number - 1,
            self._identity.logical_date,
        ) if self._identity.try_number > 1 else None
        if previous_identity is not None:
            observation = adapter.retry(
                previous_identity,
                self._identity,
                application_spec=self.application_spec,
                target=self.target,
                prior_output_valid=self.prior_output_validator,
            )
        else:
            observation = adapter.submit_or_reattach(
                self._identity,
                application_spec=self.application_spec,
                target=self.target,
            )
        if observation.state.value in {"succeeded", "failed"}:
            return self._complete(observation.state.value, observation.diagnostics, observation.name)
        if observation.state.value == "ambiguous":
            raise AirflowException(f"ambiguous SparkApplication state for {self._identity.name}")
        if self.deferrable:
            self.defer(
                trigger=SparkApplicationTrigger(
                    attempt_name=self._identity.name,
                    target=self.target,
                    namespace=self.namespace,
                    kubernetes_conn_id=self.kubernetes_conn_id,
                    poll_interval=self.poll_interval,
                ),
                method_name="execute_complete",
            )
        completed = adapter.wait_for_completion(self._identity.name, interval=self.poll_interval)
        return self._complete(completed.state.value, completed.diagnostics, completed.name)

    def _complete(self, state: str, diagnostics: Any, attempt_name: str | None = None) -> Any:
        if state != "succeeded":
            detail = "\n".join(diagnostics or ())
            raise AirflowException(f"SparkApplication failed: {detail[-4000:]}")
        return {"state": state, "attempt": attempt_name or (self._identity.name if self._identity else None)}

    def execute_complete(self, context: Mapping[str, Any], event: Mapping[str, Any] | None = None) -> Any:
        event = event or {}
        diagnostics = tuple(event.get("diagnostics", ()) or ())
        attempt_name = str(event.get("attempt")) if event.get("attempt") else None
        task_receipts = list(event.get("receipts", ()) or ())
        sink = LoggingReceiptSink(self.log)
        for receipt in task_receipts[-50:]:
            sink.record(receipt)
        sink.record(
            {
                "event": "task_completion",
                "attempt": attempt_name,
                "state": str(event.get("state", "ambiguous")),
                "diagnostics": "\n".join(diagnostics)[-4000:],
                "receipt_count": len(task_receipts),
            }
        )
        return self._complete(
            str(event.get("state", "ambiguous")),
            diagnostics,
            attempt_name,
        )

    def on_kill(self) -> None:
        if self._identity is None:
            return
        adapter = _airflow_adapter(
            conn_id=self.kubernetes_conn_id,
            namespace=self.namespace,
            target=self.target,
            receipt_logger=self.log,
        )
        adapter.cancel(self._identity)
