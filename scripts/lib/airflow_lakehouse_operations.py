"""Bounded operational helpers for Anton's Airflow Spark lakehouse."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Callable, Mapping, Protocol, Sequence
from urllib.parse import quote


DAG_ID = "airflow_spark_lakehouse"
SHADOW_TASK_ID = "run_shadow_spark_attempt"
AUTHORITATIVE_TASK_ID = "run_authoritative_spark_attempt"
FLIGHT_RECORDER_DAG_ID = "airflow_flight_recorder"
FLIGHT_RECORDER_TASK_ID = "run_flight_recorder_spark_attempt"
AIRFLOW_NAMESPACE = "airflow"
LAKEHOUSE_NAMESPACE = "lakehouse"
TRINO_NAMESPACE = "iceberg-demo"
OBSERVABILITY_NAMESPACE = "observability"
SPARK_RESOURCE = "sparkapplications.spark.apache.org"
SPARK_API_VERSION = "spark.apache.org/v1"
SHADOW_LEASE_NAME = "lakehouse-shadow-writer"
AUTHORITATIVE_LEASE_NAME = "lakehouse-authoritative-writer"
EVIDENCE_TARGETS = {
    "shadow": (SHADOW_TASK_ID, SHADOW_LEASE_NAME),
    "authoritative": (AUTHORITATIVE_TASK_ID, AUTHORITATIVE_LEASE_NAME),
}
APPROVAL_TOKEN = "shadow-live-mutation"
SAFE_RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:+-]{0,255}")
MANUAL_RUN_ID_PATTERN = re.compile(r"manual__[A-Za-z0-9][A-Za-z0-9_.:+-]{0,248}")
IMAGE_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
ACTIVE_STATES = {
    "SUBMITTED",
    "SCHEDULEDTORESTART",
    "DRIVERREQUESTED",
    "DRIVERSTARTED",
    "DRIVERREADY",
    "INITIALIZEDBELOWTHRESHOLDEXECUTORS",
    "RUNNINGHEALTHY",
    "RUNNINGWITHPARTIALCAPACITY",
    "RUNNINGWITHBELOWTHRESHOLDEXECUTORS",
}
SUCCESS_STATES = {"SUCCEEDED"}
FAILURE_STATES = {
    "FAILED",
    "SCHEDULINGFAILURE",
    "DRIVERSTARTTIMEDOUT",
    "EXECUTORSSTARTTIMEDOUT",
    "DRIVERREADYTIMEDOUT",
    "DRIVEREVICTED",
}


class OperationError(RuntimeError):
    """An operational check or bounded command failed."""


class Runner(Protocol):
    def __call__(
        self,
        argv: Sequence[str],
        timeout_seconds: float,
    ) -> subprocess.CompletedProcess[str]: ...


def subprocess_runner(
    argv: Sequence[str],
    timeout_seconds: float,
) -> subprocess.CompletedProcess[str]:
    """Run one command without a shell."""
    return subprocess.run(
        tuple(argv),
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )


def _run(
    runner: Runner,
    argv: Sequence[str],
    *,
    timeout_seconds: float = 30,
    allow_failure: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
        result = runner(tuple(argv), timeout_seconds)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise OperationError(f"command failed to run: {argv[0]}") from error
    if result.returncode != 0 and not allow_failure:
        message = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise OperationError(message[-1000:])
    return result


def _json_output(result: subprocess.CompletedProcess[str], label: str) -> Any:
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise OperationError(f"{label} returned invalid JSON") from error
    return value


def _state(value: Any) -> str:
    return str(value or "").upper().replace("-", "_")


def _history_states(resource: Mapping[str, Any]) -> list[str]:
    status = resource.get("status")
    if not isinstance(status, Mapping):
        return []
    raw = status.get("stateTransitionHistory")
    entries: list[tuple[tuple[bool, Any], Mapping[str, Any]]] = []
    if isinstance(raw, Mapping):
        for key, item in raw.items():
            if not isinstance(item, Mapping):
                continue
            try:
                order = (False, int(key))
            except (TypeError, ValueError):
                order = (True, str(key))
            entries.append((order, item))
        entries.sort(key=lambda item: item[0])
    elif isinstance(raw, list):
        entries = [((False, index), item) for index, item in enumerate(raw) if isinstance(item, Mapping)]
    return [
        _state(item.get("currentStateSummary") or item.get("state"))
        for _, item in entries
    ]


def application_outcome(resource: Mapping[str, Any] | None) -> str:
    """Return active, succeeded, failed, absent, or ambiguous."""
    if resource is None:
        return "absent"
    history = _history_states(resource)
    for state in reversed(history):
        if state in SUCCESS_STATES:
            return "succeeded"
        if state in FAILURE_STATES:
            return "failed"
    status = resource.get("status")
    current = ""
    if isinstance(status, Mapping):
        current_state = status.get("currentState")
        if isinstance(current_state, Mapping):
            current = _state(current_state.get("currentStateSummary"))
    if current in ACTIVE_STATES:
        return "active"
    return "ambiguous"


def resource_released_after_success(resource: Mapping[str, Any] | None) -> bool:
    """Return true when Spark released resources after a success state."""
    if resource is None:
        return False
    states = _history_states(resource)
    try:
        succeeded = states.index("SUCCEEDED")
    except ValueError:
        return False
    return "RESOURCERELEASED" in states[succeeded + 1:]


def parse_utc(value: str, field: str) -> datetime:
    """Parse one timezone-aware timestamp."""
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise OperationError(f"{field} must be an ISO timestamp") from error
    if parsed.tzinfo is None:
        raise OperationError(f"{field} must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def validate_run_request(
    run_id: str,
    *,
    logical_date: str | None = None,
    source_window_end: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate one manual shadow Workflow Run request."""
    if MANUAL_RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise OperationError("run ID must start with manual__ and use bounded safe characters")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    parsed_logical: datetime | None = None
    if logical_date:
        parsed_logical = parse_utc(logical_date, "logical date")
        if parsed_logical > current:
            raise OperationError("logical date cannot be in the future")
    parsed_window: datetime | None = None
    if source_window_end:
        parsed_window = parse_utc(source_window_end, "source window end")
        if parsed_window > current:
            raise OperationError("source window end cannot be in the future")
    return {
        "run_id": run_id,
        "logical_date": parsed_logical.isoformat() if parsed_logical else None,
        "source_window_end": parsed_window.isoformat() if parsed_window else None,
        "attempt_name": attempt_name(run_id=run_id, try_number=1),
    }


def validate_evidence_run_id(run_id: str) -> None:
    """Validate a safe Airflow run identity for read-only evidence lookup."""
    if SAFE_RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise OperationError("run ID must use bounded safe characters")


def _bounded_identity(value: str, limit: int = 8) -> str:
    normalized = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-") or "unknown"
    return normalized[:limit].strip("-") or "unknown"


def attempt_name(
    *,
    run_id: str,
    try_number: int = 1,
    map_index: int = -1,
    task_id: str = SHADOW_TASK_ID,
    dag_id: str = DAG_ID,
) -> str:
    """Return the deployed Spark Attempt identity."""
    if try_number < 1:
        raise OperationError("try number must be positive")
    payload = "\0".join((dag_id, run_id, task_id, str(map_index))).encode("utf-8")
    identity_hash = sha256(payload).hexdigest()[:12]
    return (
        f"lh-{_bounded_identity(dag_id)}-{_bounded_identity(task_id)}-"
        f"{identity_hash}-a{try_number}"
    )


def require_live_approval(execute: bool, approval_token: str | None) -> None:
    """Require two explicit controls before a live mutation."""
    if not execute:
        return
    if approval_token != APPROVAL_TOKEN:
        raise OperationError(f"live execution requires --approval-token {APPROVAL_TOKEN}")


@dataclass(slots=True)
class KubectlClient:
    """Run exact commands through one verified kubectl prefix."""

    prefix: tuple[str, ...]
    runner: Runner = subprocess_runner

    def command(
        self,
        *arguments: str,
        timeout_seconds: float = 30,
        allow_failure: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        return _run(
            self.runner,
            (*self.prefix, *arguments),
            timeout_seconds=timeout_seconds,
            allow_failure=allow_failure,
        )

    def json(
        self,
        *arguments: str,
        timeout_seconds: float = 30,
        allow_absent: bool = False,
    ) -> Mapping[str, Any] | None:
        result = self.command(
            *arguments,
            timeout_seconds=timeout_seconds,
            allow_failure=allow_absent,
        )
        if allow_absent and result.returncode != 0:
            combined = f"{result.stdout}\n{result.stderr}".lower()
            if "notfound" in combined or "not found" in combined:
                return None
            raise OperationError((result.stderr or result.stdout or "kubectl failed")[-1000:])
        if allow_absent and not result.stdout.strip():
            return None
        value = _json_output(result, "kubectl")
        if not isinstance(value, Mapping):
            raise OperationError("kubectl returned a non-object JSON value")
        return value

    def get_raw(self, path: str, *, timeout_seconds: float = 30) -> Any:
        result = self.command("get", "--raw", path, timeout_seconds=timeout_seconds)
        return _json_output(result, "Kubernetes service proxy")

    def component_pod(self, component: str) -> Mapping[str, Any]:
        value = self.json(
            "-n",
            AIRFLOW_NAMESPACE,
            "get",
            "pods",
            "-l",
            f"component={component}",
            "-o",
            "json",
        )
        items = value.get("items", []) if isinstance(value, Mapping) else []
        ready = [item for item in items if _pod_ready(item)]
        if len(ready) != 1:
            raise OperationError(f"expected one ready {component} pod, found {len(ready)}")
        return ready[0]

    def spark_application(self, name: str) -> Mapping[str, Any] | None:
        return self.json(
            "-n",
            LAKEHOUSE_NAMESPACE,
            "get",
            SPARK_RESOURCE,
            name,
            "-o",
            "json",
            timeout_seconds=15,
            allow_absent=True,
        )

    def lease(self, name: str = SHADOW_LEASE_NAME) -> Mapping[str, Any] | None:
        return self.json(
            "-n",
            LAKEHOUSE_NAMESPACE,
            "get",
            "lease.coordination.k8s.io",
            name,
            "-o",
            "json",
            timeout_seconds=15,
            allow_absent=True,
        )

    def attempt_pods(self, name: str) -> list[Mapping[str, Any]]:
        value = self.json(
            "-n",
            LAKEHOUSE_NAMESPACE,
            "get",
            "pods",
            "-l",
            f"anton.io/attempt-name={name}",
            "-o",
            "json",
        )
        return list(value.get("items", [])) if isinstance(value, Mapping) else []

    def airflow_task_pods(
        self, *, dag_id: str, run_id: str, task_id: str, try_number: int,
    ) -> list[Mapping[str, Any]]:
        selector = ",".join((
            f"dag_id={dag_id}", f"task_id={task_id}", "kubernetes_executor=True",
        ))
        value = self.json(
            "-n", AIRFLOW_NAMESPACE, "get", "pods", "-l", selector, "-o", "json",
        )
        items = value.get("items", []) if isinstance(value, Mapping) else []
        return [item for item in items if isinstance(item, Mapping) and
                str(((item.get("metadata") or {}).get("annotations") or {}).get("run_id")) == run_id and
                str(((item.get("metadata") or {}).get("annotations") or {}).get("try_number")) == str(try_number)]


def _pod_ready(value: Mapping[str, Any]) -> bool:
    status = value.get("status")
    if not isinstance(status, Mapping) or status.get("phase") != "Running":
        return False
    statuses = status.get("containerStatuses")
    return isinstance(statuses, list) and bool(statuses) and all(
        isinstance(item, Mapping) and item.get("ready") is True for item in statuses
    )


def _image_digest(path: Path) -> str:
    matches = IMAGE_DIGEST_PATTERN.findall(path.read_text(encoding="utf-8"))
    if not matches:
        raise OperationError(f"image digest is missing from {path}")
    return matches[0]


def _git_value(root: Path, runner: Runner, *arguments: str) -> str:
    result = _run(runner, ("git", "-C", str(root), *arguments), timeout_seconds=15)
    return result.stdout.strip()


def collect_gate_snapshot(
    root: Path,
    kubectl: KubectlClient,
    *,
    runner: Runner = subprocess_runner,
) -> dict[str, Any]:
    """Collect the bounded read-only state used by the gate preflight."""
    airflow_source = root / "kubernetes/apps/airflow/airflow/app/helmrelease.yaml"
    spark_source = root / "images/airflow-runtime/dags/airflow_spark_lakehouse.py"
    trino_source = root / "kubernetes/apps/iceberg-demo/trino/app/helmrelease.yaml"
    reader_source = root / "kubernetes/apps/iceberg-demo/trino/app/externalsecret.yaml"
    trino_text = trino_source.read_text(encoding="utf-8")
    reader_text = reader_source.read_text(encoding="utf-8")

    deployments = kubectl.json("-n", AIRFLOW_NAMESPACE, "get", "deployments", "-o", "json")
    airflow_pods = kubectl.json("-n", AIRFLOW_NAMESPACE, "get", "pods", "-o", "json")
    applications = kubectl.json("-n", LAKEHOUSE_NAMESPACE, "get", SPARK_RESOURCE, "-o", "json")
    kustomizations = kubectl.json("get", "kustomizations.kustomize.toolkit.fluxcd.io", "-A", "-o", "json")
    services = kubectl.json("get", "services", "-A", "-o", "json")
    trino_pods = kubectl.json(
        "-n",
        TRINO_NAMESPACE,
        "get",
        "pods",
        "-l",
        "app.kubernetes.io/name=trino",
        "-o",
        "json",
    )
    external_secret = kubectl.json(
        "-n",
        TRINO_NAMESPACE,
        "get",
        "externalsecret.external-secrets.io",
        "trino-iceberg-credentials",
        "-o",
        "json",
        allow_absent=True,
    )
    api_resources = kubectl.command("api-resources", "--api-group=spark.apache.org", "-o", "name").stdout.splitlines()

    branch = _git_value(root, runner, "branch", "--show-current")
    head = _git_value(root, runner, "rev-parse", "HEAD")
    origin_main = _git_value(root, runner, "rev-parse", "origin/main")
    dirty = bool(_git_value(root, runner, "status", "--porcelain"))

    airflow_items = deployments.get("items", []) if isinstance(deployments, Mapping) else []
    live_airflow_images: list[str] = []
    for item in airflow_items:
        metadata = item.get("metadata") if isinstance(item, Mapping) else None
        if not isinstance(metadata, Mapping) or not str(metadata.get("name", "")).startswith("airflow-"):
            continue
        containers = (((item.get("spec") or {}).get("template") or {}).get("spec") or {}).get("containers", [])
        for container in containers:
            image = container.get("image") if isinstance(container, Mapping) else None
            if isinstance(image, str) and "airflow-runtime" in image:
                live_airflow_images.append(image)

    app_items = applications.get("items", []) if isinstance(applications, Mapping) else []
    active_apps = [
        str((item.get("metadata") or {}).get("name", ""))
        for item in app_items
        if isinstance(item, Mapping) and application_outcome(item) in {"active", "ambiguous"}
    ]

    required_components = {"api-server", "scheduler", "dag-processor", "triggerer"}
    component_ready: dict[str, bool] = {}
    pod_items = airflow_pods.get("items", []) if isinstance(airflow_pods, Mapping) else []
    for component in required_components:
        matches = [
            item
            for item in pod_items
            if isinstance(item, Mapping)
            and ((item.get("metadata") or {}).get("labels") or {}).get("component") == component
        ]
        component_ready[component] = len([item for item in matches if _pod_ready(item)]) == 1

    service_items = services.get("items", []) if isinstance(services, Mapping) else []
    service_names = {
        f"{(item.get('metadata') or {}).get('namespace')}/{(item.get('metadata') or {}).get('name')}"
        for item in service_items
        if isinstance(item, Mapping)
    }

    required_kustomizations = {
        "airflow",
        "spark-operator",
        "shadow-fixture",
        "spark-history-server",
        "trino",
        "loki",
        "otel-collector",
    }
    flux_ready: dict[str, bool] = {}
    flux_revisions: dict[str, str] = {}
    ks_items = kustomizations.get("items", []) if isinstance(kustomizations, Mapping) else []
    for item in ks_items:
        if not isinstance(item, Mapping):
            continue
        metadata = item.get("metadata") or {}
        name = str(metadata.get("name", ""))
        if name not in required_kustomizations:
            continue
        status = item.get("status") or {}
        conditions = status.get("conditions") or []
        ready = any(
            isinstance(condition, Mapping)
            and condition.get("type") == "Ready"
            and condition.get("status") == "True"
            for condition in conditions
        )
        flux_ready[name] = ready
        revision = status.get("lastAppliedRevision") or status.get("lastAttemptedRevision")
        if revision:
            flux_revisions[name] = str(revision)

    es_ready = False
    if isinstance(external_secret, Mapping):
        conditions = ((external_secret.get("status") or {}).get("conditions") or [])
        es_ready = any(
            isinstance(condition, Mapping)
            and condition.get("type") == "Ready"
            and condition.get("status") == "True"
            for condition in conditions
        )

    trino_items = trino_pods.get("items", []) if isinstance(trino_pods, Mapping) else []
    lease = kubectl.lease()
    return {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "repo": {
            "branch": branch,
            "head": head,
            "origin_main": origin_main,
            "dirty": dirty,
        },
        "source": {
            "airflow_image_digest": _image_digest(airflow_source),
            "spark_image_digest": _image_digest(spark_source),
            "spark_api_version": SPARK_API_VERSION,
            "trino_catalogs_read_only": (
                "iceberg:" in trino_text
                and "iceberg_shadow:" in trino_text
                and trino_text.count("iceberg.security=READ_ONLY") >= 2
            ),
            "reader_identities": (
                "seaweedfs-iceberg-reader/reader-access-key" in reader_text
                and "seaweedfs-iceberg-shadow-reader/reader-access-key" in reader_text
            ),
        },
        "runtime": {
            "api_resources": sorted(api_resources),
            "airflow_images": sorted(set(live_airflow_images)),
            "airflow_components_ready": component_ready,
            "trino_ready_pods": len([item for item in trino_items if _pod_ready(item)]),
            "trino_reader_external_secret_ready": es_ready,
            "active_spark_applications": sorted(active_apps),
            "lease_exists": lease is not None,
            "lease_holder": ((lease or {}).get("spec") or {}).get("holderIdentity"),
            "services": sorted(service_names),
            "flux_ready": flux_ready,
            "flux_revisions": flux_revisions,
        },
    }


def evaluate_gate_preflight(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate a preflight snapshot without changing live state."""
    repo = snapshot.get("repo") if isinstance(snapshot.get("repo"), Mapping) else {}
    source = snapshot.get("source") if isinstance(snapshot.get("source"), Mapping) else {}
    runtime = snapshot.get("runtime") if isinstance(snapshot.get("runtime"), Mapping) else {}
    checks: list[dict[str, Any]] = []

    def check(identifier: str, passed: bool, evidence: Any, *, severity: str = "blocker") -> None:
        checks.append(
            {
                "id": identifier,
                "status": "passed" if passed else "failed",
                "severity": severity,
                "evidence": evidence,
            }
        )

    check("repo-main", repo.get("branch") == "main", repo.get("branch"))
    check("repo-clean", repo.get("dirty") is False, {"dirty": repo.get("dirty")})
    check("origin-current", repo.get("head") == repo.get("origin_main"), {"head": repo.get("head"), "origin_main": repo.get("origin_main")})
    check(
        "spark-api",
        "sparkapplications.spark.apache.org" in set(runtime.get("api_resources") or []),
        runtime.get("api_resources"),
    )
    airflow_digest = source.get("airflow_image_digest")
    airflow_images = list(runtime.get("airflow_images") or [])
    check(
        "airflow-image",
        bool(airflow_digest) and bool(airflow_images) and all(str(image).endswith(str(airflow_digest)) for image in airflow_images),
        {"expected_digest": airflow_digest, "images": airflow_images},
    )
    check("trino-read-only-catalogs", source.get("trino_catalogs_read_only") is True, source.get("trino_catalogs_read_only"))
    check("trino-reader-identities", source.get("reader_identities") is True, source.get("reader_identities"))
    check("trino-reader-secret-ready", runtime.get("trino_reader_external_secret_ready") is True, runtime.get("trino_reader_external_secret_ready"))
    check("trino-ready", int(runtime.get("trino_ready_pods") or 0) >= 2, runtime.get("trino_ready_pods"))
    components = runtime.get("airflow_components_ready") or {}
    check("airflow-components-ready", bool(components) and all(components.values()), components)
    check("no-active-spark-attempt", not runtime.get("active_spark_applications"), runtime.get("active_spark_applications"))
    check(
        "no-shadow-lease",
        runtime.get("lease_exists") is False and not runtime.get("lease_holder"),
        {
            "exists": runtime.get("lease_exists"),
            "holder": runtime.get("lease_holder"),
        },
    )

    services = set(runtime.get("services") or [])
    required_services = {
        "observability/loki",
        "lakehouse/spark-history-server",
        "iceberg-demo/trino",
    }
    check("evidence-services", required_services <= services, {"required": sorted(required_services), "present": sorted(required_services & services)})

    flux_ready = runtime.get("flux_ready") or {}
    required_flux = {"airflow", "spark-operator", "shadow-fixture", "spark-history-server", "trino", "loki", "otel-collector"}
    check(
        "flux-ready",
        required_flux <= set(flux_ready) and all(flux_ready.get(name) is True for name in required_flux),
        flux_ready,
    )
    revisions = runtime.get("flux_revisions") or {}
    head = str(repo.get("head") or "")
    check(
        "flux-current",
        bool(head)
        and required_flux <= set(revisions)
        and all(str(revisions.get(name, "")).endswith(f"@sha1:{head}") for name in required_flux),
        {"repo_head": head, "revisions": revisions},
    )
    check(
        "workflow-conflict-coverage",
        True,
        {
            "method": "single-writer guard",
            "coverage": "active SparkApplication and shadow Lease",
            "limitation": "Airflow REST needs credentials; queued runs are not observed directly",
        },
        severity="warning",
    )

    blockers = [item for item in checks if item["status"] == "failed" and item["severity"] == "blocker"]
    warnings = [item for item in checks if item["severity"] == "warning"]
    return {
        "schema_version": 1,
        "ready": not blockers,
        "observed_at": snapshot.get("observed_at"),
        "candidate": {
            "repo_head": repo.get("head"),
            "flux_revisions": revisions,
            "airflow_image_digest": source.get("airflow_image_digest"),
            "spark_image_digest": source.get("spark_image_digest"),
            "spark_api_version": source.get("spark_api_version"),
            "target": "shadow",
        },
        "checks": checks,
        "blockers": blockers,
        "warnings": warnings,
    }


def build_trigger_command(
    kubectl_prefix: Sequence[str],
    *,
    scheduler_pod: str,
    run_id: str,
    logical_date: str | None = None,
    source_window_end: str | None = None,
) -> tuple[str, ...]:
    """Build one exact-target Airflow trigger command."""
    command = [
        *kubectl_prefix,
        "-n",
        AIRFLOW_NAMESPACE,
        "exec",
        scheduler_pod,
        "-c",
        "scheduler",
        "--",
        "airflow",
        "dags",
        "trigger",
        "-r",
        run_id,
        "-o",
        "json",
    ]
    if logical_date:
        command.extend(("-l", logical_date))
    if source_window_end:
        command.extend(("-c", json.dumps({"source_window_end": source_window_end}, separators=(",", ":"))))
    command.append(DAG_ID)
    return tuple(command)


def trigger_shadow_run(
    kubectl: KubectlClient,
    *,
    run_id: str,
    logical_date: str | None = None,
    source_window_end: str | None = None,
    execute: bool = False,
    approval_token: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Plan or create one guarded shadow Workflow Run."""
    request = validate_run_request(
        run_id,
        logical_date=logical_date,
        source_window_end=source_window_end,
        now=now,
    )
    require_live_approval(execute, approval_token)
    scheduler = kubectl.component_pod("scheduler")
    scheduler_name = str((scheduler.get("metadata") or {}).get("name"))
    argv = build_trigger_command(
        kubectl.prefix,
        scheduler_pod=scheduler_name,
        run_id=run_id,
        logical_date=request["logical_date"],
        source_window_end=request["source_window_end"],
    )
    result: dict[str, Any] = {
        "schema_version": 1,
        "mode": "execute" if execute else "dry-run",
        "target": "shadow",
        "request": request,
        "scheduler_pod": scheduler_name,
        "command": list(argv),
        "task_instance_confirmed": False,
    }
    if not execute:
        return result
    response = _run(kubectl.runner, argv, timeout_seconds=60)
    result["trigger_output"] = _safe_json_or_text(response.stdout)
    task_state = wait_for_task_instance(kubectl, scheduler_name, run_id, timeout_seconds=90)
    result["task_instance_confirmed"] = True
    result["task_instance"] = task_state
    return result


def wait_for_task_instance(
    kubectl: KubectlClient,
    scheduler_pod: str,
    run_id: str,
    *,
    timeout_seconds: float,
) -> Any:
    """Wait until Airflow reports one task instance for the run."""
    deadline = time.monotonic() + timeout_seconds
    command = (
        *kubectl.prefix,
        "-n",
        AIRFLOW_NAMESPACE,
        "exec",
        scheduler_pod,
        "-c",
        "scheduler",
        "--",
        "airflow",
        "tasks",
        "states-for-dag-run",
        "-o",
        "json",
        DAG_ID,
        run_id,
    )
    last: Any = None
    while time.monotonic() < deadline:
        result = _run(kubectl.runner, command, timeout_seconds=30, allow_failure=True)
        if result.returncode == 0:
            value = _safe_json_or_text(result.stdout)
            last = value
            if isinstance(value, list) and value:
                return value
            if isinstance(value, Mapping) and value:
                return value
        time.sleep(2)
    raise OperationError(f"Airflow did not create a task instance for {run_id}; last={last!r}")


def _safe_json_or_text(value: str) -> Any:
    stripped = value.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        lines = [line for line in stripped.splitlines() if line.strip()]
        for line in reversed(lines):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
        return stripped[-1000:]


def _loki_summary(kubectl: KubectlClient, query: str, start: datetime, end: datetime) -> dict[str, Any]:
    start_ns = int(start.timestamp() * 1_000_000_000)
    end_ns = int(end.timestamp() * 1_000_000_000)
    encoded = quote(query, safe="")
    path = (
        f"/api/v1/namespaces/{OBSERVABILITY_NAMESPACE}/services/http:loki:3100/proxy"
        f"/loki/api/v1/query_range?query={encoded}&start={start_ns}&end={end_ns}"
        "&limit=5000&direction=forward"
    )
    response = kubectl.get_raw(path)
    data = response.get("data") if isinstance(response, Mapping) else None
    result = data.get("result", []) if isinstance(data, Mapping) else []
    samples = sum(len(stream.get("values", [])) for stream in result if isinstance(stream, Mapping))
    receipt_events: set[str] = set()
    receipt_attempts: set[str] = set()
    prior_application_active: set[bool] = set()
    receipts: list[dict[str, Any]] = []
    source_receipts: list[dict[str, Any]] = []
    for stream in result:
        if not isinstance(stream, Mapping):
            continue
        labels = stream.get("stream")
        event = labels.get("event") if isinstance(labels, Mapping) else None
        if not isinstance(event, str):
            continue
        if event.startswith("flight_recorder_source_receipt "):
            try:
                source_receipt = json.loads(event.removeprefix("flight_recorder_source_receipt "))
            except json.JSONDecodeError:
                continue
            if isinstance(source_receipt, Mapping):
                retained_fields = (
                    "schema_version", "query", "window_start", "window_end", "entry_count",
                    "raw_bytes", "raw_key", "raw_sha256", "attempt", "manifest_key",
                )
                source_receipts.append({
                    key: source_receipt.get(key) for key in retained_fields if key in source_receipt
                })
            continue
        if not event.startswith("spark_attempt_receipt "):
            continue
        try:
            receipt = json.loads(event.removeprefix("spark_attempt_receipt "))
        except json.JSONDecodeError:
            continue
        if not isinstance(receipt, Mapping):
            continue
        if receipt.get("event"):
            receipt_events.add(str(receipt["event"]))
        if receipt.get("attempt"):
            receipt_attempts.add(str(receipt["attempt"]))
        if isinstance(receipt.get("prior_application_active"), bool):
            prior_application_active.add(bool(receipt["prior_application_active"]))
        receipts.append(
            {
                key: receipt.get(key)
                for key in ("event", "attempt", "state", "target", "prior_application_active")
                if key in receipt
            }
        )
    return {
        "query": query,
        "streams": len(result),
        "samples": samples,
        "receipt_events": sorted(receipt_events),
        "receipt_attempts": sorted(receipt_attempts),
        "prior_application_active": sorted(prior_application_active),
        "receipts": receipts,
        "source_receipts": source_receipts,
    }


def airflow_loki_query(run_id: str) -> str:
    """Return the bounded Airflow receipt query for one Workflow Run."""
    return f'{{k8s_namespace_name="airflow"}} |= "{run_id}" |= "spark_attempt_receipt"'


def flight_recorder_source_loki_query(attempt_name: str) -> str:
    """Return the source receipt query for one exact Flight Recorder Attempt."""
    return (
        f'{{k8s_namespace_name="airflow"}} |= "{attempt_name}" '
        '|= "flight_recorder_source_receipt"'
    )


def pod_loki_query(pod_name: str) -> str:
    """Return a query that uses the promoted pod metadata field."""
    return f'{{k8s_namespace_name="lakehouse"}} | k8s_pod_name="{pod_name}"'


def attempt_pod_loki_query(attempt_name: str, *, errors_only: bool = False) -> str:
    """Return a query for all driver and executor pods in one attempt."""
    selector = '{k8s_namespace_name="lakehouse"'
    if errors_only:
        selector += ', severity=~"fatal|error"'
    return f'{selector}}} | k8s_pod_name=~"{attempt_name}.*"'


def _resource_pod_names(resource: Mapping[str, Any] | None, pods: Sequence[Mapping[str, Any]]) -> list[str]:
    names = {
        str((pod.get("metadata") or {}).get("name"))
        for pod in pods
        if (pod.get("metadata") or {}).get("name")
    }
    status = resource.get("status") if isinstance(resource, Mapping) else None
    if isinstance(status, Mapping):
        driver = status.get("driverInfo")
        if isinstance(driver, Mapping) and driver.get("podName"):
            names.add(str(driver["podName"]))
        executors = status.get("executorState")
        if isinstance(executors, Mapping):
            names.update(str(name) for name in executors)
    return sorted(names)


def _retained_evidence(ledger_path: Path | None, run_id: str) -> dict[str, Any] | None:
    if ledger_path is None:
        return None
    try:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise OperationError("retained ledger cannot be read") from error
    runs = ledger.get("runs") if isinstance(ledger, Mapping) else None
    if not isinstance(runs, list):
        raise OperationError("retained ledger has no runs")
    selected = next((run for run in runs if isinstance(run, Mapping) and run.get("run_id") == run_id), None)
    if selected is None:
        raise OperationError(f"retained ledger does not contain {run_id}")
    evidence = selected.get("evidence")
    if not isinstance(evidence, Mapping):
        return {"candidate": ledger.get("candidate"), "run": selected, "artifacts": {}}
    artifacts: dict[str, Any] = {}
    for name, relative in evidence.items():
        if not isinstance(relative, str):
            continue
        path = ledger_path.parent / relative
        try:
            artifacts[str(name)] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            artifacts[str(name)] = {"error": "artifact cannot be read", "path": relative}
    return {"candidate": ledger.get("candidate"), "run": selected, "artifacts": artifacts}


def _retained_artifact_passed(retained: Mapping[str, Any] | None, name: str) -> bool:
    if not isinstance(retained, Mapping):
        return False
    artifacts = retained.get("artifacts")
    artifact = artifacts.get(name) if isinstance(artifacts, Mapping) else None
    return isinstance(artifact, Mapping) and artifact.get("passed") is True


def _retained_runtime_artifact_passed(
    retained: Mapping[str, Any] | None,
    *,
    name: str,
    run_id: str,
    attempt_name: str,
) -> bool:
    if not isinstance(retained, Mapping):
        return False
    artifacts = retained.get("artifacts")
    artifact = artifacts.get(name) if isinstance(artifacts, Mapping) else None
    details = artifact.get("details") if isinstance(artifact, Mapping) else None
    if (
        not isinstance(artifact, Mapping)
        or artifact.get("passed") is not True
        or artifact.get("run_id") != run_id
        or not isinstance(details, Mapping)
    ):
        return False
    if name == "loki":
        markers = details.get("unique_markers")
        return (
            isinstance(markers, list)
            and run_id in markers
            and attempt_name in markers
            and details.get("containers_exited") is True
            and details.get("error_sample_count") == 0
        )
    if name == "history_server":
        application_id = str(details.get("application_id", ""))
        return details.get("completed") is True and (
            application_id == attempt_name or application_id.startswith(f"{attempt_name}-")
        )
    return False


def _retained_attempt_passed(
    retained: Mapping[str, Any] | None,
    *,
    run_id: str,
    target: str,
    attempt_name: str,
) -> bool:
    if not isinstance(retained, Mapping):
        return False
    run = retained.get("run")
    artifacts = retained.get("artifacts")
    trino = artifacts.get("trino") if isinstance(artifacts, Mapping) else None
    spark = run.get("spark") if isinstance(run, Mapping) else None
    base_passed = (
        isinstance(run, Mapping)
        and run.get("run_id") == run_id
        and run.get("status") == "passed"
        and run.get("target") == target
        and isinstance(spark, Mapping)
        and spark.get("attempt_name") == attempt_name
        and isinstance(trino, Mapping)
        and trino.get("artifact") == "trino"
        and trino.get("run_id") == run_id
        and trino.get("passed") is True
    )
    if not base_passed:
        return False
    if target == "shadow":
        return True
    details = trino.get("details")
    snapshots_before = details.get("snapshots_before") if isinstance(details, Mapping) else None
    snapshots_after = details.get("snapshots_after") if isinstance(details, Mapping) else None
    snapshots_changed = (
        isinstance(snapshots_before, Mapping)
        and isinstance(snapshots_after, Mapping)
        and all(
            snapshots_before.get(table)
            and snapshots_after.get(table)
            and snapshots_before.get(table) != snapshots_after.get(table)
            for table in ("normalized", "hourly")
        )
    )
    return (
        isinstance(details, Mapping)
        and details.get("normalized_count") == 5
        and details.get("hourly_count") == 5
        and details.get("hourly_event_count_sum") == 5
        and all(details.get(check) is True for check in ("schema", "partitions", "snapshots", "locations"))
        and snapshots_changed
    )


def _retained_workflow_passed(
    retained: Mapping[str, Any] | None,
    *,
    run_id: str,
    task_id: str,
    try_number: int,
    attempt_name: str,
) -> bool:
    if not isinstance(retained, Mapping):
        return False
    run = retained.get("run")
    artifacts = retained.get("artifacts")
    artifact = artifacts.get("workflow_run") if isinstance(artifacts, Mapping) else None
    details = artifact.get("details") if isinstance(artifact, Mapping) else None
    candidate = retained.get("candidate")
    spark = run.get("spark") if isinstance(run, Mapping) else None
    airflow_digest = details.get("airflow_image_digest") if isinstance(details, Mapping) else None
    spark_digest = details.get("spark_image_digest") if isinstance(details, Mapping) else None
    deadline_passed = False
    if isinstance(details, Mapping):
        try:
            expected_start = parse_utc(str(details.get("expected_start")), "expected start")
            end_date = parse_utc(str(details.get("end_date")), "Workflow Run end date")
            deadline_passed = expected_start <= end_date <= expected_start + timedelta(minutes=20)
        except OperationError:
            deadline_passed = False
    return (
        isinstance(artifact, Mapping)
        and artifact.get("artifact") == "workflow_run"
        and artifact.get("run_id") == run_id
        and artifact.get("passed") is True
        and isinstance(details, Mapping)
        and details.get("dag_id") == DAG_ID
        and details.get("run_id") == run_id
        and details.get("task_id") == task_id
        and details.get("try_number") == try_number
        and details.get("attempt_name") == attempt_name
        and details.get("run_type") == "scheduled"
        and details.get("status") == "success"
        and details.get("task_status") == "success"
        and details.get("schedule_enabled") is True
        and isinstance(details.get("schedule"), str)
        and deadline_passed
        and isinstance(details.get("dag_digest"), str)
        and isinstance(airflow_digest, str)
        and IMAGE_DIGEST_PATTERN.fullmatch(airflow_digest) is not None
        and isinstance(spark_digest, str)
        and IMAGE_DIGEST_PATTERN.fullmatch(spark_digest) is not None
        and isinstance(candidate, Mapping)
        and candidate.get("airflow_image_digest") == airflow_digest
        and candidate.get("spark_image_digest") == spark_digest
        and candidate.get("dag_digest") == details.get("dag_digest")
        and isinstance(spark, Mapping)
        and spark.get("image_digest") == spark_digest
    )


def _retained_resources_passed(
    retained: Mapping[str, Any] | None,
    *,
    run_id: str,
    attempt_name: str,
) -> bool:
    if not isinstance(retained, Mapping):
        return False
    artifacts = retained.get("artifacts")
    artifact = artifacts.get("resources") if isinstance(artifacts, Mapping) else None
    details = artifact.get("details") if isinstance(artifact, Mapping) else None
    measurements = details.get("measurements") if isinstance(details, Mapping) else None
    peak_memory = measurements.get("peak_memory_bytes") if isinstance(measurements, Mapping) else None
    memory_ceiling = measurements.get("memory_ceiling_bytes") if isinstance(measurements, Mapping) else None
    return (
        isinstance(artifact, Mapping)
        and artifact.get("artifact") == "resources"
        and artifact.get("run_id") == run_id
        and artifact.get("attempt_name") == attempt_name
        and artifact.get("passed") is True
        and isinstance(details, Mapping)
        and details.get("within_learning_ceilings") is True
        and isinstance(measurements, Mapping)
        and isinstance(peak_memory, int)
        and not isinstance(peak_memory, bool)
        and peak_memory > 0
        and isinstance(memory_ceiling, int)
        and not isinstance(memory_ceiling, bool)
        and peak_memory <= memory_ceiling
    )


def _resource_summary(resource: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if resource is None:
        return None
    metadata = resource.get("metadata") if isinstance(resource.get("metadata"), Mapping) else {}
    spec = resource.get("spec") if isinstance(resource.get("spec"), Mapping) else {}
    status = resource.get("status") if isinstance(resource.get("status"), Mapping) else {}
    current = status.get("currentState") if isinstance(status.get("currentState"), Mapping) else {}
    spark_conf = spec.get("sparkConf") if isinstance(spec.get("sparkConf"), Mapping) else {}
    return {
        "api_version": resource.get("apiVersion"),
        "kind": resource.get("kind"),
        "name": metadata.get("name"),
        "namespace": metadata.get("namespace"),
        "uid": metadata.get("uid"),
        "generation": metadata.get("generation"),
        "resource_version": metadata.get("resourceVersion"),
        "created_at": metadata.get("creationTimestamp"),
        "annotations": metadata.get("annotations"),
        "current_state": current.get("currentStateSummary"),
        "state_history": _history_states(resource),
        "image": spark_conf.get("spark.kubernetes.container.image"),
    }


def _pod_summary(pod: Mapping[str, Any]) -> dict[str, Any]:
    metadata = pod.get("metadata") if isinstance(pod.get("metadata"), Mapping) else {}
    spec = pod.get("spec") if isinstance(pod.get("spec"), Mapping) else {}
    status = pod.get("status") if isinstance(pod.get("status"), Mapping) else {}
    labels = metadata.get("labels") if isinstance(metadata.get("labels"), Mapping) else {}
    containers = status.get("containerStatuses") if isinstance(status.get("containerStatuses"), list) else []
    requested = spec.get("containers") if isinstance(spec.get("containers"), list) else []
    return {
        "name": metadata.get("name"),
        "role": labels.get("spark-role"),
        "phase": status.get("phase"),
        "start_time": status.get("startTime"),
        "containers": [
            {
                "name": item.get("name"),
                "ready": item.get("ready"),
                "restart_count": item.get("restartCount"),
                "image": item.get("image"),
                "image_id": item.get("imageID"),
            }
            for item in containers
            if isinstance(item, Mapping)
        ],
        "requested_images": [item.get("image") for item in requested if isinstance(item, Mapping)],
    }


def _evidence_identity(workflow: str, target: str) -> tuple[str, str, str, bool]:
    if workflow == "flight-recorder":
        if target != "authoritative":
            raise OperationError("Flight Recorder evidence requires the authoritative target")
        return FLIGHT_RECORDER_DAG_ID, FLIGHT_RECORDER_TASK_ID, AUTHORITATIVE_LEASE_NAME, False
    if workflow != "lakehouse":
        raise OperationError(f"unsupported evidence workflow: {workflow}")
    if target not in EVIDENCE_TARGETS:
        raise OperationError(f"unsupported evidence target: {target}")
    task_id, lease_name = EVIDENCE_TARGETS[target]
    return DAG_ID, task_id, lease_name, target == "authoritative"


def _task_pod_image_matches(pods: Sequence[Mapping[str, Any]], digest: str | None) -> bool:
    if not pods or IMAGE_DIGEST_PATTERN.fullmatch(str(digest or "")) is None:
        return False
    summaries = [_pod_summary(pod) for pod in pods]
    return all(
        any(digest in str(image) for image in summary["requested_images"])
        and any(digest in str(item.get("image_id")) for item in summary["containers"])
        for summary in summaries
    )


def collect_attempt_evidence(
    kubectl: KubectlClient,
    *,
    run_id: str,
    try_number: int = 1,
    target: str = "shadow",
    workflow: str = "lakehouse",
    expected_airflow_digest: str | None = None,
    ledger_path: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Collect bounded live and retained evidence for one exact attempt."""
    validate_evidence_run_id(run_id)
    dag_id, task_id, lease_name, require_scheduled = _evidence_identity(workflow, target)
    observed_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    name = attempt_name(run_id=run_id, try_number=try_number, task_id=task_id, dag_id=dag_id)
    resource = kubectl.spark_application(name)
    pods = kubectl.attempt_pods(name)
    task_pods = (
        kubectl.airflow_task_pods(
            dag_id=dag_id, run_id=run_id, task_id=task_id, try_number=try_number,
        )
        if workflow == "flight-recorder" else []
    )
    retained = _retained_evidence(ledger_path, run_id)
    created_text = ((resource or {}).get("metadata") or {}).get("creationTimestamp")
    start = parse_utc(str(created_text), "SparkApplication creation time") - timedelta(minutes=5) if created_text else observed_at - timedelta(hours=1)
    pod_names = _resource_pod_names(resource, pods)
    airflow_loki = _loki_summary(
        kubectl,
        airflow_loki_query(run_id),
        start,
        observed_at + timedelta(minutes=1),
    )
    flight_recorder_source_loki = (
        _loki_summary(
            kubectl,
            flight_recorder_source_loki_query(name),
            start,
            observed_at + timedelta(minutes=1),
        )
        if workflow == "flight-recorder" else None
    )
    pod_loki = [
        _loki_summary(
            kubectl,
            pod_loki_query(pod_name),
            start,
            observed_at + timedelta(minutes=1),
        )
        for pod_name in pod_names
    ]
    pod_error_loki = [
        _loki_summary(
            kubectl,
            f'{pod_loki_query(pod_name)} |~ "(?i)(error|exception|traceback)"',
            start,
            observed_at + timedelta(minutes=1),
        )
        for pod_name in pod_names
    ]
    attempt_loki = _loki_summary(
        kubectl,
        attempt_pod_loki_query(name),
        start,
        observed_at + timedelta(minutes=1),
    )
    attempt_error_loki = _loki_summary(
        kubectl,
        attempt_pod_loki_query(name, errors_only=True),
        start,
        observed_at + timedelta(minutes=1),
    )
    history_path = (
        f"/api/v1/namespaces/{LAKEHOUSE_NAMESPACE}/services/http:spark-history-server:18080"
        "/proxy/api/v1/applications?limit=20&status=completed"
    )
    history_response = kubectl.get_raw(history_path)
    history_items = history_response if isinstance(history_response, list) else history_response.get("applications", [])
    if not isinstance(history_items, list):
        history_items = []
    history_matches = [
        {
            "id": item.get("id"),
            "name": item.get("name"),
            "attempts": len(item.get("attempts", [])) if isinstance(item.get("attempts"), list) else None,
            "completed": any(
                isinstance(attempt, Mapping) and attempt.get("completed") is True
                for attempt in item.get("attempts", [])
            )
            if isinstance(item.get("attempts"), list)
            else False,
        }
        for item in history_items
        if isinstance(item, Mapping)
        and (
            item.get("name") == name
            or item.get("id") == name
            or str(item.get("id", "")).startswith(f"{name}-")
        )
    ]
    lease = kubectl.lease(lease_name)
    spark_outcome = application_outcome(resource)
    lease_holder = ((lease or {}).get("spec") or {}).get("holderIdentity")
    missing: list[str] = []
    if resource is None:
        missing.append("spark_application")
    if airflow_loki["samples"] == 0:
        missing.append("airflow_loki")
    receipts = airflow_loki["receipts"]
    selected_receipts = [item for item in receipts if item.get("attempt") == name]
    selected_events = {str(item.get("event")) for item in selected_receipts}
    required_receipts = {"lease_acquired", "task_completion", "terminal_state"}
    if not required_receipts.issubset(selected_events):
        missing.append("airflow_receipts")
    if not selected_receipts:
        missing.append("airflow_attempt_identity")
    lease_receipts = [item for item in selected_receipts if item.get("event") == "lease_acquired"]
    if not lease_receipts or not all(
        item.get("attempt") == name
        and item.get("target") == target
        and item.get("prior_application_active") is False
        for item in lease_receipts
    ):
        missing.append("lease_acquisition")
    for event in ("terminal_state", "task_completion"):
        states = {
            str(item.get("state", "")).lower()
            for item in selected_receipts
            if item.get("event") == event
        }
        if states != {"succeeded"}:
            missing.append(f"{event}_succeeded")
    if lease_holder not in (None, name):
        missing.append("conflicting_lease_holder")
    if spark_outcome != "succeeded":
        missing.append("spark_succeeded")
    if require_scheduled and not run_id.startswith("scheduled__"):
        missing.append("scheduled_run_identity")
    if workflow == "flight-recorder" and not _task_pod_image_matches(task_pods, expected_airflow_digest):
        missing.append("airflow_worker_image")
    if workflow == "flight-recorder" and any((pod.get("status") or {}).get("phase") != "Succeeded" for pod in task_pods):
        missing.append("airflow_task_pod_incomplete")
    if workflow == "flight-recorder" and lease_holder is not None:
        missing.append("active_writer_lease")
    if workflow == "flight-recorder" and not resource_released_after_success(resource):
        missing.append("spark_resource_release")
    if workflow == "flight-recorder" and any((pod.get("status") or {}).get("phase") in {"Pending", "Running"} for pod in pods):
        missing.append("active_spark_pods")
    if not any(item["samples"] > 0 for item in pod_loki) and attempt_loki["samples"] == 0 and not _retained_runtime_artifact_passed(
        retained,
        name="loki",
        run_id=run_id,
        attempt_name=name,
    ):
        missing.append("pod_loki")
    if any(item["samples"] > 0 for item in pod_error_loki) or attempt_error_loki["samples"] > 0:
        missing.append("pod_loki_errors")
    if not any(item["completed"] for item in history_matches) and not _retained_runtime_artifact_passed(
        retained,
        name="history_server",
        run_id=run_id,
        attempt_name=name,
    ):
        missing.append("history_server")
    if workflow == "lakehouse" and retained is None:
        missing.append("retained_gate_evidence")
    elif workflow == "lakehouse":
        if not _retained_attempt_passed(
            retained,
            run_id=run_id,
            target=target,
            attempt_name=name,
        ):
            missing.append("trino")
        if target == "authoritative":
            if not _retained_workflow_passed(
                retained,
                run_id=run_id,
                task_id=task_id,
                try_number=try_number,
                attempt_name=name,
            ):
                missing.append("workflow_run")
            if not _retained_resources_passed(
                retained,
                run_id=run_id,
                attempt_name=name,
            ):
                missing.append("resources")
    return {
        "schema_version": 1,
        "status": "complete" if not missing else "incomplete",
        "observed_at": observed_at.isoformat(),
        "identity": {
            "dag_id": dag_id,
            "run_id": run_id,
            "task_id": task_id,
            "try_number": try_number,
            "attempt_name": name,
            "target": target,
            "run_type": "scheduled" if run_id.startswith("scheduled__") else "manual_or_other",
        },
        "live": {
            "spark_application": _resource_summary(resource),
            "spark_outcome": spark_outcome,
            "pods": [_pod_summary(pod) for pod in pods],
            "airflow_task_pods": [_pod_summary(pod) for pod in task_pods],
            "expected_airflow_digest": expected_airflow_digest,
            "lease_holder": lease_holder,
            "airflow_loki": airflow_loki,
            "flight_recorder_source_loki": flight_recorder_source_loki,
            "pod_loki": pod_loki,
            "pod_error_loki": pod_error_loki,
            "attempt_loki": attempt_loki,
            "attempt_error_loki": attempt_error_loki,
            "history_server": history_matches,
        },
        "retained": retained,
        "missing": missing,
    }
