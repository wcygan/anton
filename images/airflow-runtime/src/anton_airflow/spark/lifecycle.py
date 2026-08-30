"""One lifecycle policy for synchronous and deferred Spark Attempt waits."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable, Mapping, Protocol

from .lease import LeaseCoordinator
from .receipts import ReceiptSink
from .state import AttemptState, classify_application, state_transition_history


class SparkApplicationObserver(Protocol):
    """Read and watch one Apache Spark Operator custom resource."""

    def get(self, *, namespace: str, name: str) -> Mapping[str, Any]: ...

    def watch(
        self,
        *,
        namespace: str,
        name: str,
        timeout_seconds: int,
    ) -> list[Mapping[str, Any]]: ...


class PodDiagnostics(Protocol):
    """Read bounded pod and event evidence for one Spark Attempt."""

    def list_pods(
        self,
        *,
        namespace: str,
        label_selector: str,
    ) -> list[Mapping[str, Any]]: ...

    def read_log(self, *, namespace: str, name: str, container: str) -> str: ...

    def list_events(
        self,
        *,
        namespace: str,
        field_selector: str,
    ) -> list[Mapping[str, Any]]: ...


@dataclass(frozen=True, slots=True)
class AttemptObservation:
    """One normalized and bounded Spark Attempt observation."""

    name: str
    state: AttemptState
    resource: Mapping[str, Any] | None = None
    diagnostics: tuple[str, ...] = ()

    @property
    def status_pending(self) -> bool:
        """Return true before the Apache operator writes its first status."""
        if not isinstance(self.resource, Mapping):
            return False
        status = self.resource.get("status")
        return status is None or status == {}


class SparkAttemptMonitor:
    """Advance one attempt through the shared lifecycle policy."""

    def __init__(
        self,
        lifecycle: SparkAttemptLifecycle,
        *,
        name: str,
        interval: float,
        startup_timeout: float,
    ) -> None:
        self._lifecycle = lifecycle
        self.name = name
        self.interval = interval
        self._startup_deadline = lifecycle.monotonic() + startup_timeout

    def advance(self) -> AttemptObservation:
        """Observe once, apply ownership policy, and wait for the next change."""
        observation = self._lifecycle.observe(self.name)
        if observation.status_pending:
            if self._lifecycle.monotonic() >= self._startup_deadline:
                return AttemptObservation(
                    self.name,
                    AttemptState.AMBIGUOUS,
                    observation.resource,
                    self._lifecycle.collect_diagnostics(self.name),
                )
            self._lifecycle.renew_and_wait(
                self.name,
                interval=self.interval,
                event="status_pending",
            )
            return AttemptObservation(
                self.name,
                AttemptState.ACTIVE,
                observation.resource,
            )
        if observation.state is AttemptState.ACTIVE:
            self._lifecycle.renew_and_wait(
                self.name,
                interval=self.interval,
                event="lease_renewed",
            )
            return observation
        if observation.state is AttemptState.SUCCEEDED:
            self._lifecycle.release(self.name, state=observation.state)
            return observation
        if observation.state is AttemptState.FAILED:
            diagnostics = self._lifecycle.collect_terminal_diagnostics(self.name)
            self._lifecycle.release(self.name, state=observation.state)
            return AttemptObservation(
                self.name,
                observation.state,
                observation.resource,
                diagnostics,
            )
        return AttemptObservation(
            self.name,
            observation.state,
            observation.resource,
            self._lifecycle.collect_diagnostics(self.name),
        )

    def run(self, *, timeout: float) -> AttemptObservation:
        """Run the lifecycle synchronously until one terminal result."""
        deadline = self._lifecycle.monotonic() + timeout
        while self._lifecycle.monotonic() < deadline:
            observation = self.advance()
            if observation.state is AttemptState.ACTIVE:
                continue
            if observation.state is AttemptState.AMBIGUOUS:
                raise RuntimeError(
                    f"ambiguous SparkApplication state for {self.name}"
                )
            if observation.state in {AttemptState.SUCCEEDED, AttemptState.FAILED}:
                return observation
            if observation.state is AttemptState.ABSENT:
                raise RuntimeError(
                    f"SparkApplication {self.name} disappeared before completion"
                )
        raise TimeoutError(
            f"SparkApplication {self.name} did not complete within {timeout:g}s"
        )


class SparkAttemptLifecycle:
    """Own observation, waiting, evidence, and Lease terminal policy."""

    def __init__(
        self,
        *,
        applications: SparkApplicationObserver,
        leases: LeaseCoordinator,
        pods: PodDiagnostics | None = None,
        namespace: str = "lakehouse",
        diagnostics_limit: int = 2000,
        receipts: ReceiptSink | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._applications = applications
        self._leases = leases
        self._pods = pods
        self.namespace = namespace
        self.diagnostics_limit = diagnostics_limit
        self.receipts = receipts
        self.monotonic = monotonic
        self._sleep = sleeper
        self._last_states: dict[str, AttemptState] = {}
        self._last_histories: dict[str, tuple[tuple[str, str], ...]] = {}
        self._terminal_receipts: set[str] = set()

    def monitor(
        self,
        name: str,
        *,
        interval: float,
        startup_timeout: float = 60.0,
    ) -> SparkAttemptMonitor:
        """Create one bounded lifecycle monitor for an exact attempt."""
        return SparkAttemptMonitor(
            self,
            name=name,
            interval=interval,
            startup_timeout=startup_timeout,
        )

    def record_receipt(
        self,
        event: str,
        name: str,
        *,
        state: AttemptState | None = None,
        identity: Mapping[str, Any] | None = None,
        **details: Any,
    ) -> None:
        """Write one bounded structured record without Secret data."""
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
    def _resource_identity(
        resource: Mapping[str, Any] | None,
    ) -> Mapping[str, Any] | None:
        metadata = resource.get("metadata") if isinstance(resource, Mapping) else None
        annotations = metadata.get("annotations") if isinstance(metadata, Mapping) else None
        return annotations if isinstance(annotations, Mapping) else None

    def _record_observation(self, observation: AttemptObservation) -> None:
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
                transitions=[
                    {"state": state, "at": at} for state, at in history[-20:]
                ],
            )
        if (
            observation.state in {AttemptState.SUCCEEDED, AttemptState.FAILED}
            and name not in self._terminal_receipts
        ):
            self._terminal_receipts.add(name)
            self.record_receipt(
                "terminal_state",
                name,
                state=observation.state,
                identity=identity,
            )

    def record_observation(self, observation: AttemptObservation) -> None:
        """Record one observation created outside the monitor."""
        self._record_observation(observation)

    def observe(self, name: str) -> AttemptObservation:
        """Read and normalize one exact Spark Attempt."""
        try:
            resource = self._applications.get(
                namespace=self.namespace,
                name=name,
            )
        except Exception as error:
            if getattr(error, "status", None) == 404:
                observation = AttemptObservation(name, AttemptState.ABSENT)
                self._record_observation(observation)
                return observation
            raise
        state = classify_application(resource)
        status = resource.get("status")
        if status is None or status == {}:
            state = AttemptState.ACTIVE
        observation = AttemptObservation(name, state, resource)
        self._record_observation(observation)
        return observation

    def renew_and_wait(
        self,
        name: str,
        *,
        interval: float,
        event: str,
    ) -> None:
        """Renew ownership, then use one bounded watch or polling fallback."""
        self._leases.renew(name)
        self.record_receipt(event, name, state=AttemptState.ACTIVE)
        watcher = getattr(self._applications, "watch", None)
        if watcher is None:
            self.record_receipt(
                "watch_fallback",
                name,
                state=AttemptState.ACTIVE,
                reason="unavailable",
            )
            self._sleep(interval)
            return
        try:
            watcher(
                namespace=self.namespace,
                name=name,
                timeout_seconds=max(1, int(interval)),
            )
        except Exception as error:
            self.record_receipt(
                "watch_fallback",
                name,
                state=AttemptState.ACTIVE,
                reason=type(error).__name__,
            )

    def release(self, name: str, *, state: AttemptState) -> None:
        """Release the writer Lease after one terminal outcome."""
        already_absent = self._leases.release_idempotent(name)
        self.record_receipt(
            "lease_released",
            name,
            state=state,
            already_absent=already_absent,
        )

    def collect_diagnostics(self, name: str) -> tuple[str, ...]:
        """Collect bounded diagnostics and fail on source access errors."""
        return self._collect_diagnostics(name, tolerate_source_errors=False)

    def collect_terminal_diagnostics(self, name: str) -> tuple[str, ...]:
        """Collect bounded diagnostics without masking a terminal failure."""
        return self._collect_diagnostics(name, tolerate_source_errors=True)

    def _collect_diagnostics(
        self,
        name: str,
        *,
        tolerate_source_errors: bool,
    ) -> tuple[str, ...]:
        if self._pods is None:
            return ()
        lines: list[str] = []
        tails: list[dict[str, str]] = []
        source_errors: list[dict[str, str]] = []
        selector = f"anton.io/attempt-name={name}"
        try:
            pods = self._pods.list_pods(
                namespace=self.namespace,
                label_selector=selector,
            )
        except Exception as error:
            if not tolerate_source_errors:
                raise
            error_type = type(error).__name__
            lines.append(f"pod diagnostics unavailable: {error_type}")
            source_errors.append({"source": "pods", "error": error_type})
            pods = []
        for pod in pods:
            pod_name = str((pod.get("metadata") or {}).get("name", "unknown"))
            containers = (pod.get("spec") or {}).get("containers") or []
            for container in containers:
                container_name = str(container.get("name", ""))
                if not container_name:
                    continue
                try:
                    output = self._pods.read_log(
                        namespace=self.namespace,
                        name=pod_name,
                        container=container_name,
                    )
                except Exception as error:
                    output = f"log read failed: {type(error).__name__}"
                tail = output[-self.diagnostics_limit :]
                role = str(
                    ((pod.get("metadata") or {}).get("labels") or {}).get(
                        "spark-role"
                    )
                    or ((pod.get("metadata") or {}).get("labels") or {}).get(
                        "sparkoperator.k8s.io/spark-role"
                    )
                    or "unknown"
                )
                lines.append(
                    f"pod/{pod_name} container/{container_name}:\n{tail}"
                )
                tails.append(
                    {
                        "pod": pod_name,
                        "container": container_name,
                        "role": role,
                        "tail": tail,
                    }
                )
        events: list[dict[str, str]] = []
        try:
            event_items = self._pods.list_events(
                namespace=self.namespace,
                field_selector=f"involvedObject.name={name}",
            )
        except Exception as error:
            if not tolerate_source_errors:
                raise
            error_type = type(error).__name__
            lines.append(f"event diagnostics unavailable: {error_type}")
            source_errors.append({"source": "events", "error": error_type})
            event_items = []
        for item in event_items:
            reason = item.get("reason", "")
            message = item.get("message", "")
            lines.append(
                f"event {reason}: {message}"[-self.diagnostics_limit :]
            )
            events.append(
                {
                    "reason": str(reason),
                    "message": str(message)[-self.diagnostics_limit :],
                }
            )
        self.record_receipt(
            "failure_diagnostics",
            name,
            driver_tails=[
                item for item in tails if item["role"] == "driver"
            ][-5:],
            executor_tails=[
                item for item in tails if item["role"] == "executor"
            ][-5:],
            diagnostics=lines[-20:],
            events=events[-20:],
            source_errors=source_errors,
        )
        return tuple(lines)[-20:]
