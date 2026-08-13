"""Shadow-only recovery plans and bounded live execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import threading
import time
from typing import Any, Callable, Mapping

from airflow_lakehouse_operations import (
    AIRFLOW_NAMESPACE,
    APPROVAL_TOKEN,
    DAG_ID,
    LAKEHOUSE_NAMESPACE,
    LEASE_NAME,
    SPARK_RESOURCE,
    TASK_ID,
    TRINO_NAMESPACE,
    KubectlClient,
    OperationError,
    Runner,
    application_outcome,
    attempt_name,
    build_trigger_command,
    collect_attempt_evidence,
    collect_gate_snapshot,
    evaluate_gate_preflight,
    require_live_approval,
    subprocess_runner,
    validate_run_request,
)


SCENARIOS = (
    "scheduler-restart",
    "triggerer-restart",
    "duplicate-delivery",
    "bounded-retry",
    "cancellation",
    "expired-lease-refusal",
    "precommit-failure",
)


@dataclass(frozen=True, slots=True)
class RecoveryPlan:
    scenario: str
    run_id: str
    attempt: str
    steps: tuple[str, ...]
    stop_condition: str
    rollback: str
    acceptance: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "run_id": self.run_id,
            "attempt": self.attempt,
            "target": "shadow",
            "steps": list(self.steps),
            "stop_condition": self.stop_condition,
            "rollback": self.rollback,
            "acceptance": list(self.acceptance),
        }


def build_recovery_plan(scenario: str, run_id: str) -> RecoveryPlan:
    """Build one stable scenario plan before any live mutation."""
    if scenario not in SCENARIOS:
        raise OperationError(f"unsupported recovery case: {scenario}")
    validate_run_request(run_id)
    attempt = attempt_name(run_id=run_id)
    common = (
        "Pass the read-only gate preflight.",
        "Resolve exact scheduler, triggerer, Spark Attempt, and Lease identities.",
        "Arm the scenario watcher before the Workflow Run.",
        "Create one manual shadow Workflow Run without a future logical date.",
    )
    scenario_steps: dict[str, tuple[str, ...]] = {
        "scheduler-restart": (
            "Delete only the resolved scheduler pod while the attempt is active.",
            "Wait for one ready replacement and the same terminal attempt.",
        ),
        "triggerer-restart": (
            "Stop the exact driver JVM after driver readiness.",
            "Delete only the resolved triggerer pod.",
            "Require a post-start Lease renewal from the replacement triggerer.",
            "Resume the exact driver JVM and wait for the same terminal attempt.",
        ),
        "duplicate-delivery": (
            "Call the production adapter with the same active AttemptIdentity.",
            "Require one SparkApplication and one successful terminal attempt.",
        ),
        "bounded-retry": (
            "Wait for try one to succeed.",
            "Call the production retry seam with prior_output_valid=false.",
            "Require a distinct try-two SparkApplication and terminal success.",
        ),
        "cancellation": (
            "Call production cancellation for the exact active attempt.",
            "Require resource and pod stop before Lease release.",
        ),
        "expired-lease-refusal": (
            "Expire the exact Lease and probe with a new AttemptIdentity in one process.",
            "Require LeaseTakeoverBlocked and no probe SparkApplication.",
            "Wait for the original attempt to renew and finish.",
        ),
        "precommit-failure": (
            "Record the shadow snapshot before the run.",
            "Kill the exact driver JVM immediately after executor creation.",
            "Require retained driver and executor evidence.",
            "Require the shadow snapshot to remain unchanged.",
        ),
    }
    return RecoveryPlan(
        scenario=scenario,
        run_id=run_id,
        attempt=attempt,
        steps=common + scenario_steps[scenario] + ("Collect bounded attempt evidence and verify no active test Lease remains.",),
        stop_condition="Stop on a failed preflight, ambiguous identity, unexpected terminal state, or timeout.",
        rollback="Resume any stopped JVM. Preserve unexpected resources and report the exact cleanup target.",
        acceptance=(
            "The scenario-specific invariant passes.",
            "No active test Workflow Run or shadow Lease remains.",
            "Authoritative writer ownership does not change.",
        ),
    )


@dataclass(slots=True)
class ArmedAction:
    """Run one exact action when a bounded observation becomes true."""

    thread: threading.Thread
    done: threading.Event
    result: dict[str, Any]

    def wait(self, timeout_seconds: float) -> dict[str, Any]:
        if not self.done.wait(timeout_seconds):
            raise OperationError("armed recovery action timed out")
        if self.result.get("error"):
            raise OperationError(str(self.result["error"]))
        return self.result


def _arm_action(
    predicate: Callable[[], Any | None],
    action: Callable[[Any], Any],
    *,
    timeout_seconds: float,
    interval_seconds: float = 0.2,
) -> ArmedAction:
    done = threading.Event()
    result: dict[str, Any] = {}

    def run() -> None:
        deadline = time.monotonic() + timeout_seconds
        try:
            while time.monotonic() < deadline:
                value = predicate()
                if value is not None:
                    result["observed"] = value
                    result["action_result"] = action(value)
                    result["acted_at"] = datetime.now(timezone.utc).isoformat()
                    return
                time.sleep(interval_seconds)
            result["error"] = "armed observation timed out"
        except Exception as error:  # retained in structured scenario output
            result["error"] = f"{type(error).__name__}: {error}"
        finally:
            done.set()

    thread = threading.Thread(target=run, name="airflow-recovery-watcher", daemon=True)
    thread.start()
    return ArmedAction(thread, done, result)


@dataclass(slots=True)
class RecoveryRuntime:
    """Execute exact shadow recovery operations through verified kubectl."""

    root: Path
    kubectl: KubectlClient
    runner: Runner = subprocess_runner
    timeout_seconds: float = 600

    def wait_application(self, name: str, outcomes: set[str]) -> Mapping[str, Any] | None:
        deadline = time.monotonic() + self.timeout_seconds
        last = "absent"
        while time.monotonic() < deadline:
            resource = self.kubectl.spark_application(name)
            last = application_outcome(resource)
            if last in outcomes:
                return resource
            if last == "ambiguous":
                raise OperationError(f"SparkApplication {name} became ambiguous")
            time.sleep(1)
        raise OperationError(f"SparkApplication {name} did not reach {sorted(outcomes)}; last={last}")

    def active_application(self, name: str) -> Mapping[str, Any] | None:
        resource = self.kubectl.spark_application(name)
        return resource if application_outcome(resource) == "active" else None

    def driver_pod(self, name: str, *, require_ready: bool = False) -> str | None:
        for pod in self.kubectl.attempt_pods(name):
            labels = (pod.get("metadata") or {}).get("labels") or {}
            if labels.get("spark-role") != "driver":
                continue
            if require_ready and not _pod_running_ready(pod):
                continue
            return str((pod.get("metadata") or {}).get("name"))
        return None

    def executor_pod(self, name: str) -> str | None:
        for pod in self.kubectl.attempt_pods(name):
            labels = (pod.get("metadata") or {}).get("labels") or {}
            if labels.get("spark-role") == "executor":
                return str((pod.get("metadata") or {}).get("name"))
        return None

    def exec_pod(self, namespace: str, pod: str, container: str, *command: str) -> str:
        result = self.kubectl.command(
            "-n",
            namespace,
            "exec",
            pod,
            "-c",
            container,
            "--",
            *command,
            timeout_seconds=90,
        )
        return result.stdout.strip()

    def component_name(self, component: str) -> str:
        pod = self.kubectl.component_pod(component)
        return str((pod.get("metadata") or {}).get("name"))

    def delete_pod(self, namespace: str, pod: str) -> str:
        result = self.kubectl.command(
            "-n",
            namespace,
            "delete",
            "pod",
            pod,
            "--wait=false",
            timeout_seconds=30,
        )
        return result.stdout.strip()

    def wait_component_replacement(self, component: str, old_pod: str) -> Mapping[str, Any]:
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            try:
                pod = self.kubectl.component_pod(component)
            except OperationError:
                time.sleep(1)
                continue
            name = str((pod.get("metadata") or {}).get("name"))
            if name != old_pod:
                return pod
            time.sleep(1)
        raise OperationError(f"replacement {component} pod did not become ready")

    def wait_no_lease(self) -> None:
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            if self.kubectl.lease() is None:
                return
            time.sleep(1)
        raise OperationError("shadow Lease remained after the scenario")

    def wait_lease_renewal(self, holder: str, after: datetime) -> Mapping[str, Any]:
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            lease = self.kubectl.lease()
            spec = (lease or {}).get("spec") or {}
            renew_time = spec.get("renewTime")
            if spec.get("holderIdentity") == holder and renew_time:
                parsed = datetime.fromisoformat(str(renew_time).replace("Z", "+00:00")).astimezone(timezone.utc)
                if parsed > after:
                    return lease or {}
            time.sleep(1)
        raise OperationError("replacement triggerer did not renew the exact Lease")

    def trigger_only(self, scheduler_pod: str, run_id: str) -> Any:
        command = build_trigger_command(
            self.kubectl.prefix,
            scheduler_pod=scheduler_pod,
            run_id=run_id,
        )
        result = self.runner(command, 60)
        if result.returncode != 0:
            raise OperationError((result.stderr or result.stdout or "Airflow trigger failed")[-1000:])
        return _last_json(result.stdout)

    def run_state(self, run_id: str) -> str | None:
        scheduler = self.component_name("scheduler")
        output = self.exec_pod(
            AIRFLOW_NAMESPACE,
            scheduler,
            "scheduler",
            "airflow",
            "dags",
            "list-runs",
            "-o",
            "json",
            DAG_ID,
        )
        value = _last_json(output)
        if not isinstance(value, list):
            return None
        selected = next((item for item in value if isinstance(item, Mapping) and item.get("run_id") == run_id), None)
        return str(selected.get("state")) if selected else None

    def adapter_probe(self, code: str) -> Any:
        triggerer = self.component_name("triggerer")
        output = self.exec_pod(
            AIRFLOW_NAMESPACE,
            triggerer,
            "triggerer",
            "python",
            "-c",
            code,
        )
        return _last_json(output)

    def trino_snapshot(self) -> str:
        value = self.kubectl.json(
            "-n",
            TRINO_NAMESPACE,
            "get",
            "pods",
            "-l",
            "app.kubernetes.io/component=coordinator,app.kubernetes.io/name=trino",
            "-o",
            "json",
        )
        items = value.get("items", []) if isinstance(value, Mapping) else []
        ready = [item for item in items if _pod_running_ready(item)]
        if len(ready) != 1:
            raise OperationError(f"expected one ready Trino coordinator, found {len(ready)}")
        pod = str((ready[0].get("metadata") or {}).get("name"))
        sql = 'SELECT snapshot_id FROM iceberg_shadow.logs."normalized$snapshots" ORDER BY committed_at DESC LIMIT 1'
        output = self.exec_pod(
            TRINO_NAMESPACE,
            pod,
            "trino-coordinator",
            "trino",
            "--output-format",
            "TSV",
            "--execute",
            sql,
        )
        values = re.findall(r"(?m)^\s*([0-9]+)\s*$", output)
        if not values:
            raise OperationError("Trino did not return a shadow snapshot ID")
        return values[-1]


def _pod_running_ready(pod: Mapping[str, Any]) -> bool:
    status = pod.get("status") or {}
    if status.get("phase") != "Running":
        return False
    containers = status.get("containerStatuses") or []
    return bool(containers) and all(isinstance(item, Mapping) and item.get("ready") is True for item in containers)


def _last_json(value: str) -> Any:
    stripped = value.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        for line in reversed(stripped.splitlines()):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return stripped[-1000:]


def _adapter_setup(run_id: str, try_number: int = 1) -> str:
    return (
        "import json;"
        "from anton_airflow.lakehouse import SHADOW_APPLICATION_SPEC;"
        "from anton_airflow.spark import AttemptIdentity;"
        "from anton_airflow.spark.operator import _airflow_adapter;"
        f"identity=AttemptIdentity({DAG_ID!r},{run_id!r},{TASK_ID!r},-1,{try_number});"
        "adapter=_airflow_adapter(conn_id='kubernetes_default',namespace='lakehouse',target='shadow');"
    )


def _duplicate_probe_code(run_id: str) -> str:
    return _adapter_setup(run_id) + (
        "observation=adapter.submit_or_reattach(identity,application_spec=SHADOW_APPLICATION_SPEC,target='shadow');"
        "print(json.dumps({'result':'reattach','attempt':observation.name,'state':observation.state.value}))"
    )


def _retry_probe_code(run_id: str) -> str:
    return _adapter_setup(run_id, 1) + (
        f"next_identity=AttemptIdentity({DAG_ID!r},{run_id!r},{TASK_ID!r},-1,2);"
        "observation=adapter.retry(identity,next_identity,application_spec=SHADOW_APPLICATION_SPEC,target='shadow',prior_output_valid=lambda resource:False);"
        "print(json.dumps({'result':'retry','attempt':observation.name,'state':observation.state.value}))"
    )


def _release_probe_code(run_id: str, try_number: int) -> str:
    return _adapter_setup(run_id, try_number) + (
        "adapter.leases.release_if_held(identity.name);"
        "print(json.dumps({'result':'released','attempt':identity.name}))"
    )


def _cancellation_probe_code(run_id: str) -> str:
    return _adapter_setup(run_id) + (
        "diagnostics=adapter.cancel_attempt(identity.name,timeout=60);"
        "print(json.dumps({'result':'cancelled','attempt':identity.name,'diagnostics':len(diagnostics)}))"
    )


def _expired_lease_probe_code(run_id: str, probe_run_id: str) -> str:
    expired = "2000-01-01T00:00:00.000000Z"
    return _adapter_setup(run_id) + (
        "from anton_airflow.spark.lease import LeaseTakeoverBlocked;"
        "current=adapter.leases.current();"
        f"current['spec']['renewTime']={expired!r};"
        "adapter.leases.api.replace_namespaced_lease(adapter.leases.lease_name,adapter.leases.namespace,current);"
        f"probe=AttemptIdentity({DAG_ID!r},{probe_run_id!r},{TASK_ID!r},-1,1);"
        "result='unexpected';"
        "\ntry:\n adapter.submit_or_reattach(probe,application_spec=SHADOW_APPLICATION_SPEC,target='shadow')\n"
        "except LeaseTakeoverBlocked:\n result='LeaseTakeoverBlocked'\n"
        "print(json.dumps({'result':result,'probe':probe.name,'original':identity.name}))"
    )


def _preflight_or_raise(runtime: RecoveryRuntime) -> dict[str, Any]:
    result = evaluate_gate_preflight(
        collect_gate_snapshot(runtime.root, runtime.kubectl, runner=runtime.runner)
    )
    if not result["ready"]:
        identifiers = [item["id"] for item in result["blockers"]]
        raise OperationError(f"gate preflight blocked recovery: {', '.join(identifiers)}")
    return result


def execute_recovery_case(
    root: Path,
    kubectl: KubectlClient,
    *,
    scenario: str,
    run_id: str,
    execute: bool = False,
    approval_token: str | None = None,
    timeout_seconds: float = 600,
    runner: Runner = subprocess_runner,
) -> dict[str, Any]:
    """Plan or execute one approved shadow-only recovery scenario."""
    plan = build_recovery_plan(scenario, run_id)
    require_live_approval(execute, approval_token)
    result: dict[str, Any] = {
        "schema_version": 1,
        "mode": "execute" if execute else "dry-run",
        "plan": plan.as_dict(),
    }
    if not execute:
        return result

    runtime = RecoveryRuntime(root, kubectl, runner=runner, timeout_seconds=timeout_seconds)
    result["preflight"] = _preflight_or_raise(runtime)
    if kubectl.spark_application(plan.attempt) is not None:
        raise OperationError(f"SparkApplication already exists for {run_id}")
    scheduler = runtime.component_name("scheduler")
    result["started_at"] = datetime.now(timezone.utc).isoformat()

    if scenario == "scheduler-restart":
        old_scheduler = scheduler
        armed = _arm_action(
            lambda: runtime.active_application(plan.attempt),
            lambda _: runtime.delete_pod(AIRFLOW_NAMESPACE, old_scheduler),
            timeout_seconds=120,
        )
        result["trigger"] = runtime.trigger_only(scheduler, run_id)
        result["mutation"] = armed.wait(150)
        replacement = runtime.wait_component_replacement("scheduler", old_scheduler)
        resource = runtime.wait_application(plan.attempt, {"succeeded"})
        runtime.wait_no_lease()
        result["replacement_pod"] = (replacement.get("metadata") or {}).get("name")
        result["spark_outcome"] = application_outcome(resource)

    elif scenario == "triggerer-restart":
        old_triggerer = runtime.component_name("triggerer")
        stopped: dict[str, str] = {}

        def stop_driver(_: Any) -> str:
            driver = runtime.driver_pod(plan.attempt, require_ready=True)
            if not driver:
                raise OperationError("ready driver pod disappeared")
            stopped["pod"] = driver
            return runtime.exec_pod(LAKEHOUSE_NAMESPACE, driver, "spark-kubernetes-driver", "pkill", "-STOP", "java")

        armed = _arm_action(
            lambda: runtime.driver_pod(plan.attempt, require_ready=True),
            stop_driver,
            timeout_seconds=120,
        )
        result["trigger"] = runtime.trigger_only(scheduler, run_id)
        result["driver_hold"] = armed.wait(150)
        lease_before = kubectl.lease()
        try:
            runtime.delete_pod(AIRFLOW_NAMESPACE, old_triggerer)
            replacement = runtime.wait_component_replacement("triggerer", old_triggerer)
            replacement_started = datetime.fromisoformat(
                str((replacement.get("status") or {}).get("startTime")).replace("Z", "+00:00")
            ).astimezone(timezone.utc)
            lease_after = runtime.wait_lease_renewal(plan.attempt, replacement_started)
        finally:
            if stopped.get("pod"):
                runtime.exec_pod(
                    LAKEHOUSE_NAMESPACE,
                    stopped["pod"],
                    "spark-kubernetes-driver",
                    "pkill",
                    "-CONT",
                    "java",
                )
        resource = runtime.wait_application(plan.attempt, {"succeeded"})
        runtime.wait_no_lease()
        result["old_triggerer"] = old_triggerer
        result["replacement_triggerer"] = (replacement.get("metadata") or {}).get("name")
        result["lease_before"] = ((lease_before or {}).get("spec") or {}).get("renewTime")
        result["lease_after"] = (lease_after.get("spec") or {}).get("renewTime")
        result["spark_outcome"] = application_outcome(resource)

    elif scenario in {"duplicate-delivery", "cancellation", "expired-lease-refusal"}:
        probe_run_id = f"{run_id}-probe"
        if scenario == "duplicate-delivery":
            action = lambda _: runtime.adapter_probe(_duplicate_probe_code(run_id))
        elif scenario == "cancellation":
            action = lambda _: runtime.adapter_probe(_cancellation_probe_code(run_id))
        else:
            action = lambda _: runtime.adapter_probe(_expired_lease_probe_code(run_id, probe_run_id))
        armed = _arm_action(
            lambda: runtime.active_application(plan.attempt),
            action,
            timeout_seconds=120,
        )
        result["trigger"] = runtime.trigger_only(scheduler, run_id)
        result["probe"] = armed.wait(150)
        if scenario == "duplicate-delivery":
            resource = runtime.wait_application(plan.attempt, {"succeeded"})
            count = len(
                [
                    item
                    for item in (kubectl.json("-n", LAKEHOUSE_NAMESPACE, "get", SPARK_RESOURCE, "-o", "json").get("items") or [])
                    if ((item.get("metadata") or {}).get("annotations") or {}).get("anton.io/run-id") == run_id
                ]
            )
            if count != 1:
                raise OperationError(f"duplicate delivery created {count} SparkApplications")
            result["resource_count"] = count
            result["spark_outcome"] = application_outcome(resource)
        elif scenario == "cancellation":
            runtime.wait_application(plan.attempt, {"absent"})
            runtime.wait_no_lease()
            if kubectl.attempt_pods(plan.attempt):
                raise OperationError("cancellation left attempt pods")
            result["spark_outcome"] = "absent"
        else:
            probe_name = attempt_name(run_id=probe_run_id)
            probe_result = result["probe"].get("action_result")
            if not isinstance(probe_result, Mapping) or probe_result.get("result") != "LeaseTakeoverBlocked":
                raise OperationError("expired Lease probe did not return LeaseTakeoverBlocked")
            if kubectl.spark_application(probe_name) is not None:
                raise OperationError("expired Lease probe created a SparkApplication")
            resource = runtime.wait_application(plan.attempt, {"succeeded"})
            runtime.wait_no_lease()
            result["probe_attempt"] = probe_name
            result["spark_outcome"] = application_outcome(resource)

    elif scenario == "bounded-retry":
        result["trigger"] = runtime.trigger_only(scheduler, run_id)
        first = runtime.wait_application(plan.attempt, {"succeeded"})
        probe = runtime.adapter_probe(_retry_probe_code(run_id))
        second_name = attempt_name(run_id=run_id, try_number=2)
        second = runtime.wait_application(second_name, {"succeeded"})
        runtime.adapter_probe(_release_probe_code(run_id, 2))
        runtime.wait_no_lease()
        result["probe"] = probe
        result["attempts"] = [
            {"name": plan.attempt, "outcome": application_outcome(first)},
            {"name": second_name, "outcome": application_outcome(second)},
        ]

    elif scenario == "precommit-failure":
        snapshot_before = runtime.trino_snapshot()

        def kill_driver(_: Any) -> str:
            driver = runtime.driver_pod(plan.attempt)
            if not driver:
                raise OperationError("driver pod is missing at executor creation")
            return runtime.exec_pod(
                LAKEHOUSE_NAMESPACE,
                driver,
                "spark-kubernetes-driver",
                "pkill",
                "-9",
                "java",
            )

        armed = _arm_action(
            lambda: runtime.executor_pod(plan.attempt),
            kill_driver,
            timeout_seconds=120,
            interval_seconds=0.1,
        )
        result["trigger"] = runtime.trigger_only(scheduler, run_id)
        result["mutation"] = armed.wait(150)
        resource = runtime.wait_application(plan.attempt, {"failed"})
        snapshot_after = runtime.trino_snapshot()
        runtime.wait_no_lease()
        pods = kubectl.attempt_pods(plan.attempt)
        roles = {
            ((pod.get("metadata") or {}).get("labels") or {}).get("spark-role")
            for pod in pods
        }
        if not {"driver", "executor"} <= roles:
            raise OperationError("pre-commit failure did not retain driver and executor pods")
        if snapshot_before != snapshot_after:
            raise OperationError("pre-commit failure changed the shadow snapshot")
        result["spark_outcome"] = application_outcome(resource)
        result["snapshot_before"] = snapshot_before
        result["snapshot_after"] = snapshot_after
        result["retained_roles"] = sorted(str(role) for role in roles if role)

    result["airflow_run_state"] = runtime.run_state(run_id)
    result["evidence"] = collect_attempt_evidence(kubectl, run_id=run_id)
    result["completed_at"] = datetime.now(timezone.utc).isoformat()
    result["passed"] = True
    return result
