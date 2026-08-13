"""Generic Kubernetes adapter for Apache Spark Operator custom resources."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import time
from typing import Any, Callable, Mapping, Protocol

from .identity import AttemptIdentity
from .lease import LeaseCoordinator
from .receipts import ReceiptSink
from .state import AttemptState, classify_application, state_transition_history


GROUP = "spark.apache.org"
VERSION = "v1"
PLURAL = "sparkapplications"


class SparkApplicationClient(Protocol):
    def get(self, *, namespace: str, name: str) -> Mapping[str, Any]: ...

    def create(self, *, namespace: str, body: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def list(self, *, namespace: str, label_selector: str) -> list[Mapping[str, Any]]: ...

    def delete(self, *, namespace: str, name: str) -> Any: ...

    def watch(self, *, namespace: str, name: str, timeout_seconds: int) -> list[Mapping[str, Any]]: ...


class PodDiagnostics(Protocol):
    def list_pods(self, *, namespace: str, label_selector: str) -> list[Mapping[str, Any]]: ...

    def read_log(self, *, namespace: str, name: str, container: str) -> str: ...

    def list_events(self, *, namespace: str, field_selector: str) -> list[Mapping[str, Any]]: ...


@dataclass(frozen=True, slots=True)
class AttemptObservation:
    name: str
    state: AttemptState
    resource: Mapping[str, Any] | None = None
    diagnostics: tuple[str, ...] = ()


def _merge_env(existing: Any, correlation: Mapping[str, str]) -> list[dict[str, str]]:
    values = [dict(item) for item in existing or [] if isinstance(item, Mapping) and item.get("name")]
    by_name = {item["name"]: item for item in values}
    for name, value in correlation.items():
        by_name[name] = {"name": name, "value": value}
    return list(by_name.values())


# Container names the Apache operator's submission worker expects in the
# driver/executor PodTemplateSpec. Matching them lets Spark pick up the image,
# env, envFrom, and volumeMounts from the pod template file.
DRIVER_CONTAINER = "spark-kubernetes-driver"
EXECUTOR_CONTAINER = "spark-kubernetes-executor"


def build_spark_application(
    identity: AttemptIdentity,
    *,
    application_spec: Mapping[str, Any],
    namespace: str,
    target: str,
) -> dict[str, Any]:
    """Build one generic ``spark.apache.org/v1`` SparkApplication resource.

    The Apache operator expresses the driver and executor as full Kubernetes
    ``podTemplateSpec`` objects, restarts under ``applicationTolerations``, and
    passes the container image and service account through ``sparkConf``.
    """
    if target not in {"shadow", "authoritative"}:
        raise ValueError("target must be shadow or authoritative")
    resource = deepcopy(dict(application_spec))
    metadata = dict(resource.get("metadata") or {})
    metadata.update(
        {
            "name": identity.name,
            "namespace": namespace,
            "labels": {**(metadata.get("labels") or {}), **identity.labels(target=target)},
            "annotations": {**(metadata.get("annotations") or {}), **identity.annotations()},
        }
    )
    resource.update({"apiVersion": f"{GROUP}/{VERSION}", "kind": "SparkApplication", "metadata": metadata})
    spec = dict(resource.get("spec") or {})

    # Never restart: the Airflow operator owns bounded, identity-aware retries.
    tolerations = dict(spec.get("applicationTolerations") or {})
    restart = dict(tolerations.get("restartConfig") or {})
    restart["restartPolicy"] = "Never"
    tolerations["restartConfig"] = restart
    spec["applicationTolerations"] = tolerations

    correlation = {
        "ANTON_SPARK_ATTEMPT": identity.name,
        "ANTON_SPARK_IDENTITY_HASH": identity.hash,
        "ANTON_AIRFLOW_DAG_ID": identity.dag_id,
        "ANTON_AIRFLOW_RUN_ID": identity.run_id,
        "ANTON_AIRFLOW_TASK_ID": identity.task_id,
        "ANTON_AIRFLOW_MAP_INDEX": str(identity.map_index),
        "ANTON_AIRFLOW_TRY_NUMBER": str(identity.try_number),
        "ANTON_LAKEHOUSE_TARGET": target,
    }
    for role, container_name in (
        ("driver", DRIVER_CONTAINER),
        ("executor", EXECUTOR_CONTAINER),
    ):
        role_spec = dict(spec.get(f"{role}Spec") or {})
        template = dict(role_spec.get("podTemplateSpec") or {})
        meta = dict(template.get("metadata") or {})
        meta["labels"] = {
            **(meta.get("labels") or {}),
            **identity.labels(target=target),
            "anton.io/attempt-name": identity.name,
        }
        meta["annotations"] = {**(meta.get("annotations") or {}), **identity.annotations()}
        template["metadata"] = meta
        pod = dict(template.get("spec") or {})
        containers = list(pod.get("containers") or [])
        for index, container in enumerate(containers):
            merged = dict(container)
            merged["env"] = _merge_env(merged.get("env"), correlation)
            containers[index] = merged
        pod["containers"] = containers
        template["spec"] = pod
        role_spec["podTemplateSpec"] = template
        spec[f"{role}Spec"] = role_spec
    resource["spec"] = spec
    return resource


class SparkApplicationAdapter:
    """Create, observe, recover, and cancel SparkApplication attempts."""

    def __init__(
        self,
        *,
        applications: SparkApplicationClient,
        leases: LeaseCoordinator,
        pods: PodDiagnostics | None = None,
        namespace: str = "lakehouse",
        diagnostics_limit: int = 2000,
        receipts: ReceiptSink | None = None,
    ) -> None:
        self.applications = applications
        self.leases = leases
        self.pods = pods
        self.namespace = namespace
        self.diagnostics_limit = diagnostics_limit
        self.receipts = receipts
        self._last_states: dict[str, AttemptState] = {}
        self._last_histories: dict[str, tuple[tuple[str, str], ...]] = {}
        self._terminal_receipts: set[str] = set()

    def record_receipt(
        self,
        event: str,
        name: str,
        *,
        state: AttemptState | None = None,
        identity: Mapping[str, Any] | None = None,
        **details: Any,
    ) -> None:
        """Write one bounded structured record without exposing Secret data."""
        if self.receipts is None:
            return
        record: dict[str, Any] = {
            "event": event,
            "attempt": name,
            "namespace": self.namespace,
        }
        if state is not None:
            record["state"] = state.value
        if identity:
            record["identity"] = dict(identity)
        record.update(details)
        self.receipts.record(record)

    @staticmethod
    def _resource_identity(resource: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
        metadata = resource.get("metadata") if isinstance(resource, Mapping) else None
        annotations = metadata.get("annotations") if isinstance(metadata, Mapping) else None
        return annotations if isinstance(annotations, Mapping) else None

    def _record_observation(self, observation: AttemptObservation) -> None:
        """Record state and transition history once per changed observation."""
        name = observation.name
        identity = self._resource_identity(observation.resource)
        previous = self._last_states.get(name)
        if previous is not observation.state:
            self.record_receipt(
                "state_change",
                name,
                state=observation.state,
                identity=identity,
                previous_state=previous.value if previous else None,
            )
            self._last_states[name] = observation.state

        history = tuple(
            (
                str(item.get("state", "")),
                str(item.get("transitionTime") or item.get("timestamp") or ""),
            )
            for item in state_transition_history(observation.resource or {})
        )
        if history and self._last_histories.get(name) != history:
            self._last_histories[name] = history
            self.record_receipt(
                "state_transition",
                name,
                state=observation.state,
                identity=identity,
                transitions=[{"state": state, "at": at} for state, at in history[-20:]],
            )
        if observation.state in {AttemptState.SUCCEEDED, AttemptState.FAILED} and name not in self._terminal_receipts:
            self._terminal_receipts.add(name)
            self.record_receipt(
                "terminal_state",
                name,
                state=observation.state,
                identity=identity,
            )

    def observe(self, name: str) -> AttemptObservation:
        try:
            resource = self.applications.get(namespace=self.namespace, name=name)
        except Exception as error:
            if getattr(error, "status", None) == 404:
                observation = AttemptObservation(name, AttemptState.ABSENT)
                self._record_observation(observation)
                return observation
            raise
        observation = AttemptObservation(name, classify_application(resource), resource)
        self._record_observation(observation)
        return observation

    def submit_or_reattach(
        self,
        identity: AttemptIdentity,
        *,
        application_spec: Mapping[str, Any],
        target: str,
    ) -> AttemptObservation:
        """Create one attempt, or reattach to the exact same attempt after recovery."""
        existing = self.observe(identity.name)
        if existing.state is not AttemptState.ABSENT:
            if existing.state is AttemptState.AMBIGUOUS:
                raise RuntimeError(f"ambiguous SparkApplication state for {identity.name}")
            if existing.state is AttemptState.SUCCEEDED:
                self.record_receipt("reattach_terminal", identity.name, state=existing.state, identity=identity.annotations())
                self.leases.release_if_held(identity.name)
            elif existing.state is AttemptState.FAILED:
                self.record_receipt("reattach_failed", identity.name, state=existing.state, identity=identity.annotations())
                diagnostics = self.collect_diagnostics(identity.name)
                self.leases.release_if_held(identity.name)
                return AttemptObservation(
                    identity.name,
                    existing.state,
                    existing.resource,
                    diagnostics,
                )
            else:
                self.record_receipt("reattach", identity.name, state=existing.state, identity=identity.annotations())
            return existing
        prior_application_active = False
        current_lease = self.leases.current()
        current_holder = (current_lease.get("spec") or {}).get("holderIdentity") if current_lease else None
        if current_holder and current_holder != identity.name:
            prior_application_active = self.prior_attempt_active(str(current_holder))
        self.leases.acquire(identity.name, prior_application_active=prior_application_active)
        self.record_receipt(
            "lease_acquired",
            identity.name,
            identity=identity.annotations(),
            target=target,
            prior_application_active=prior_application_active,
        )
        body = build_spark_application(
            identity,
            application_spec=application_spec,
            namespace=self.namespace,
            target=target,
        )
        try:
            created = self.applications.create(namespace=self.namespace, body=body)
        except Exception as error:
            # A duplicate delivery races only with the same deterministic name.
            if getattr(error, "status", None) != 409:
                self.leases.release(identity.name)
                raise
            self.record_receipt("duplicate_delivery", identity.name, identity=identity.annotations())
            return self.observe(identity.name)
        # A new custom resource can have no status until Spark Operator accepts it.
        # Creation itself is the submission boundary, so defer as an active attempt.
        observation = AttemptObservation(identity.name, AttemptState.ACTIVE, created)
        self._record_observation(observation)
        self.record_receipt(
            "submission",
            identity.name,
            state=observation.state,
            identity=identity.annotations(),
            api_version=f"{GROUP}/{VERSION}",
            target=target,
        )
        return observation

    def prior_attempt_active(self, name: str) -> bool:
        """Require both a settled CR and no running pods before Lease takeover."""
        prior = self.observe(name)
        if prior.state not in {AttemptState.ABSENT, AttemptState.SUCCEEDED, AttemptState.FAILED}:
            return True
        if self.pods is None:
            # No pod evidence is not proof of inactivity.
            return True
        for pod in self.pods.list_pods(namespace=self.namespace, label_selector=f"anton.io/attempt-name={name}"):
            phase = str((pod.get("status") or {}).get("phase", "Unknown"))
            if phase not in {"Succeeded", "Failed"}:
                return True
        return False

    def retry(
        self,
        previous_identity: AttemptIdentity,
        next_identity: AttemptIdentity,
        *,
        application_spec: Mapping[str, Any],
        target: str,
        prior_output_valid: Callable[[Mapping[str, Any]], bool] | None = None,
    ) -> AttemptObservation:
        """Create a new try only after the previous attempt has a settled outcome."""
        previous = self.observe(previous_identity.name)
        if previous.state is AttemptState.ACTIVE:
            raise RuntimeError(f"cannot retry active SparkApplication {previous_identity.name}")
        if previous.state is AttemptState.AMBIGUOUS:
            raise RuntimeError(f"cannot retry ambiguous SparkApplication {previous_identity.name}")
        prior_valid = False
        if previous.state is AttemptState.SUCCEEDED and prior_output_valid and previous.resource:
            prior_valid = bool(prior_output_valid(previous.resource))
        self.record_receipt(
            "retry_evaluation",
            previous_identity.name,
            state=previous.state,
            identity=previous_identity.annotations(),
            prior_output_valid=prior_valid,
            next_attempt=next_identity.name,
        )
        if prior_valid:
            self.record_receipt(
                "prior_output_reused",
                previous.name,
                state=AttemptState.SUCCEEDED,
                identity=previous_identity.annotations(),
            )
            self.leases.release_if_held(previous_identity.name)
            return AttemptObservation(
                previous.name,
                AttemptState.SUCCEEDED,
                previous.resource,
                previous.diagnostics,
            )
        self.record_receipt(
            "retry_submission",
            next_identity.name,
            identity=next_identity.annotations(),
            previous_attempt=previous_identity.name,
        )
        self.leases.release_if_held(previous_identity.name)
        return self.submit_or_reattach(next_identity, application_spec=application_spec, target=target)

    def collect_diagnostics(self, name: str) -> tuple[str, ...]:
        """Collect bounded pod tails and events without reading Secret data."""
        if self.pods is None:
            return ()
        lines: list[str] = []
        tails: list[dict[str, str]] = []
        selector = f"anton.io/attempt-name={name}"
        for pod in self.pods.list_pods(namespace=self.namespace, label_selector=selector):
            pod_name = str((pod.get("metadata") or {}).get("name", "unknown"))
            containers = (pod.get("spec") or {}).get("containers") or []
            for container in containers:
                container_name = str(container.get("name", ""))
                if not container_name:
                    continue
                try:
                    output = self.pods.read_log(namespace=self.namespace, name=pod_name, container=container_name)
                except Exception as error:  # diagnostics must not mask the terminal state
                    output = f"log read failed: {type(error).__name__}"
                tail = output[-self.diagnostics_limit :]
                role = str(
                    ((pod.get("metadata") or {}).get("labels") or {}).get("spark-role")
                    or ((pod.get("metadata") or {}).get("labels") or {}).get("sparkoperator.k8s.io/spark-role")
                    or "unknown"
                )
                lines.append(f"pod/{pod_name} container/{container_name}:\n{tail}")
                tails.append({"pod": pod_name, "container": container_name, "role": role, "tail": tail})
        events: list[dict[str, str]] = []
        for event in self.pods.list_events(
            namespace=self.namespace,
            field_selector=f"involvedObject.name={name}",
        ):
            reason = event.get("reason", "")
            message = event.get("message", "")
            lines.append(f"event {reason}: {message}"[-self.diagnostics_limit :])
            events.append({"reason": str(reason), "message": str(message)[-self.diagnostics_limit :]})
        self.record_receipt(
            "failure_diagnostics",
            name,
            driver_tails=[item for item in tails if item["role"] == "driver"][-5:],
            executor_tails=[item for item in tails if item["role"] == "executor"][-5:],
            diagnostics=lines[-20:],
            events=events[-20:],
        )
        return tuple(lines)[-20:]

    def wait_for_completion(
        self,
        name: str,
        *,
        timeout: float = 3600.0,
        interval: float = 10.0,
    ) -> AttemptObservation:
        """Support the explicit non-deferrable mode without leaking ownership."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            observation = self.observe(name)
            if observation.state is AttemptState.ACTIVE:
                time.sleep(interval)
                continue
            if observation.state is AttemptState.AMBIGUOUS:
                raise RuntimeError(f"ambiguous SparkApplication state for {name}")
            if observation.state in {AttemptState.SUCCEEDED, AttemptState.FAILED}:
                self.leases.release(name)
                if observation.state is AttemptState.FAILED:
                    return AttemptObservation(
                        name,
                        observation.state,
                        observation.resource,
                        self.collect_diagnostics(name),
                    )
                return observation
            raise RuntimeError(f"SparkApplication {name} disappeared before completion")
        raise TimeoutError(f"SparkApplication {name} did not complete within {timeout:g}s")

    def wait_for_stop(self, name: str, *, timeout: float = 30.0, interval: float = 1.0) -> AttemptObservation:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            observation = self.observe(name)
            if observation.state is AttemptState.ABSENT:
                if self.pods is not None:
                    active_pods = [
                        pod
                        for pod in self.pods.list_pods(
                            namespace=self.namespace,
                            label_selector=f"anton.io/attempt-name={name}",
                        )
                        if str((pod.get("status") or {}).get("phase", "Unknown"))
                        not in {"Succeeded", "Failed"}
                    ]
                    if active_pods:
                        time.sleep(interval)
                        continue
                return observation
            time.sleep(interval)
        raise TimeoutError(f"SparkApplication {name} did not stop within {timeout:g}s")

    def cancel(self, identity: AttemptIdentity, *, timeout: float = 30.0) -> tuple[str, ...]:
        """Delete the exact CR, verify stop, then release its target Lease."""
        return self.cancel_attempt(identity.name, timeout=timeout)

    def cancel_attempt(self, name: str, *, timeout: float = 30.0) -> tuple[str, ...]:
        """Cancel by the exact persisted Spark Attempt name."""
        self.record_receipt("cancellation_requested", name)
        diagnostics = self.collect_diagnostics(name)
        try:
            self.applications.delete(namespace=self.namespace, name=name)
        except Exception as error:
            if getattr(error, "status", None) != 404:
                raise
        self.wait_for_stop(name, timeout=timeout)
        # Releasing before stop could permit a second writer to overlap.
        self.leases.release(name)
        self.record_receipt("cancellation_stopped", name, state=AttemptState.ABSENT)
        return diagnostics


class KubernetesSparkApplicationClient:
    """Small generic custom-resource client used by the operator and trigger."""

    def __init__(self, api: Any) -> None:
        self.api = api

    def get(self, *, namespace: str, name: str) -> Mapping[str, Any]:
        return self.api.get_namespaced_custom_object(GROUP, VERSION, namespace, PLURAL, name)

    def create(self, *, namespace: str, body: Mapping[str, Any]) -> Mapping[str, Any]:
        return self.api.create_namespaced_custom_object(GROUP, VERSION, namespace, PLURAL, body)

    def list(self, *, namespace: str, label_selector: str) -> list[Mapping[str, Any]]:
        response = self.api.list_namespaced_custom_object(
            GROUP,
            VERSION,
            namespace,
            PLURAL,
            label_selector=label_selector,
        )
        return list(response.get("items", []))

    def delete(self, *, namespace: str, name: str) -> Any:
        return self.api.delete_namespaced_custom_object(GROUP, VERSION, namespace, PLURAL, name)

    def watch(self, *, namespace: str, name: str, timeout_seconds: int) -> list[Mapping[str, Any]]:
        """Read bounded custom-resource watch events from the generic Kubernetes API."""
        from kubernetes import watch

        stream = watch.Watch().stream(
            self.api.get_namespaced_custom_object,
            GROUP,
            VERSION,
            namespace,
            PLURAL,
            name,
            timeout_seconds=timeout_seconds,
        )
        return [event for event in stream if isinstance(event, Mapping)]
