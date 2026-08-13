"""Validate retained evidence for the five-run Airflow shadow gate."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any, Mapping


LEDGER_SCHEMA_VERSION = 2
EVIDENCE_SCHEMA_VERSION = 1
CREDENTIAL_RECEIPT_SCHEMA_VERSION = 1
REQUIRED_RUNS = 5
SPARK_API_VERSION = "spark.apache.org/v1"
REQUIRED_TRINO_CHECKS = (
    "schema",
    "counts",
    "partitions",
    "snapshots",
    "locations",
    "time_travel",
    "write_denial_authoritative",
    "write_denial_shadow",
)
REQUIRED_KUBERNETES_CHECKS = (
    "task_pods",
    "custom_resource_observation",
    "spark_workloads",
)
REQUIRED_RUNTIME_EVIDENCE = (
    "runtime_identity",
    "classpath",
    "s3fileio",
    "s3a",
    "loki",
    "history_server",
)
REQUIRED_EVIDENCE_ARTIFACTS = (
    "workflow_run",
    "spark_application",
    "trino",
    "authoritative_state",
    "runtime",
    "kubernetes",
    "loki",
    "history_server",
)
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_HOST_COMMAND = re.compile(
    r"(?:^|[\s;&|()'\"!`])"
    r"(?P<executable>"
    r"(?:(?:/(?:[A-Za-z0-9_.+-]+/)*)|(?:\./(?:[A-Za-z0-9_.+-]+/)*)|"
    r"(?:\.\./(?:[A-Za-z0-9_.+-]+/)*))?"
    r"(?:docker|flux|kubectl|task))"
    r"(?=$|[\s;&|()'\"!`])"
)
_MISE_PREFIX = re.compile(r"(?:^|[;&|()'\"`\n])\s*mise\s+exec\s+--\s*$")


class ShadowGateError(ValueError):
    """The shadow gate ledger is malformed or unsafe to evaluate."""


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ShadowGateError(f"{field} must be an object")
    return value


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ShadowGateError(f"{field} must be a non-empty string")
    return value


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ShadowGateError(f"{field} must be true or false")
    return value


def _positive_integer(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ShadowGateError(f"{field} must be a positive integer")
    return value


def _timestamp(value: Any, field: str) -> datetime:
    timestamp = _string(value, field)
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as error:
        raise ShadowGateError(f"{field} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise ShadowGateError(f"{field} must include a timezone")
    return parsed


def _source_command(value: Any, field: str) -> str:
    command = _string(value, field)
    for match in _HOST_COMMAND.finditer(command):
        prefix = command[: match.start("executable")]
        if not _MISE_PREFIX.search(prefix):
            raise ShadowGateError(f"{field} host commands must use mise exec --")
    return command


def _true_checks(value: Any, field: str, required: tuple[str, ...]) -> None:
    checks = _mapping(value, field)
    for name in required:
        if not _boolean(checks.get(name), f"{field}.{name}"):
            raise ShadowGateError(f"{field}.{name} must be true")


def _artifact_path(root: Path | None, value: Any, field: str) -> Path:
    relative = _string(value, field)
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ShadowGateError(f"{field} must be a relative path without parent traversal")
    if root is None:
        raise ShadowGateError("evidence_root is required to verify retained artifacts")
    resolved_root = root.resolve()
    resolved = (resolved_root / path).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as error:
        raise ShadowGateError(f"{field} is outside evidence_root") from error
    if not resolved.is_file():
        raise ShadowGateError(f"{field} does not identify a retained file")
    if resolved.stat().st_size > 1024 * 1024:
        raise ShadowGateError(f"{field} exceeds the 1 MiB evidence limit")
    return resolved


def _retained_json(root: Path | None, value: Any, field: str) -> Mapping[str, Any]:
    path = _artifact_path(root, value, field)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ShadowGateError(f"{field} is not valid JSON evidence") from error
    return _mapping(payload, field)


def _artifact_payload(root: Path | None, value: Any, field: str, *, run_id: str, artifact: str) -> Mapping[str, Any]:
    envelope = _retained_json(root, value, field)
    if envelope.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        raise ShadowGateError(f"{field}.schema_version is unsupported")
    if envelope.get("run_id") != run_id:
        raise ShadowGateError(f"{field}.run_id does not match the Workflow Run")
    if envelope.get("artifact") != artifact:
        raise ShadowGateError(f"{field}.artifact must be {artifact}")
    if envelope.get("passed") is not True:
        raise ShadowGateError(f"{field}.passed must be true")
    _timestamp(envelope.get("observed_at"), f"{field}.observed_at")
    source = _mapping(envelope.get("source"), f"{field}.source")
    _source_command(source.get("command"), f"{field}.source.command")
    result = source.get("result")
    if result in (None, "", [], {}):
        raise ShadowGateError(f"{field}.source.result must contain retained output")
    return _mapping(envelope.get("details"), f"{field}.details")


def _artifacts(value: Any, *, root: Path | None, run_id: str, field: str = "evidence") -> dict[str, Mapping[str, Any]]:
    artifacts = _mapping(value, field)
    details: dict[str, Mapping[str, Any]] = {}
    for name in REQUIRED_EVIDENCE_ARTIFACTS:
        details[name] = _artifact_payload(root, artifacts.get(name), f"{field}.{name}", run_id=run_id, artifact=name)
    return details


def _validate_credential_rotation(
    candidate: Mapping[str, Any],
    runs: list[dict[str, Any]],
    *,
    evidence_root: Path | None,
) -> None:
    field = "candidate.credential_rotation_receipt"
    receipt = _retained_json(
        evidence_root,
        candidate.get("credential_rotation_receipt"),
        field,
    )
    if receipt.get("schema_version") != CREDENTIAL_RECEIPT_SCHEMA_VERSION:
        raise ShadowGateError(f"{field}.schema_version is unsupported")
    if receipt.get("status") != "accepted":
        raise ShadowGateError(f"{field}.status must be accepted")
    if receipt.get("candidate_revision") != candidate.get("source_revision"):
        raise ShadowGateError(f"{field}.candidate_revision does not match the candidate")
    if receipt.get("credential_version") != candidate.get("credential_version"):
        raise ShadowGateError(f"{field}.credential_version does not match the candidate")
    if receipt.get("credential_owner") != candidate.get("credential_owner"):
        raise ShadowGateError(f"{field}.credential_owner does not match the candidate")
    if receipt.get("credential_epoch") != candidate.get("credential_epoch"):
        raise ShadowGateError(f"{field}.credential_epoch does not match the candidate")
    first_run = _mapping(runs[0], "runs[1]")
    first_run_id = _string(first_run.get("run_id"), "runs[1].run_id")
    if receipt.get("rotation_completed_before_run_id") != first_run_id:
        raise ShadowGateError(
            f"{field}.rotation_completed_before_run_id must identify the first ledger run"
        )
    rotation_completed_at = _timestamp(
        receipt.get("rotation_completed_at"),
        f"{field}.rotation_completed_at",
    )
    first_run_observed_at = _timestamp(
        first_run.get("observed_at"),
        "runs[1].observed_at",
    )
    if rotation_completed_at >= first_run_observed_at:
        raise ShadowGateError(f"{field}.rotation_completed_at must precede the first run")
    source = _mapping(receipt.get("source"), f"{field}.source")
    source_observed_at = _timestamp(
        source.get("observed_at"),
        f"{field}.source.observed_at",
    )
    if source_observed_at < rotation_completed_at:
        raise ShadowGateError(f"{field}.source.observed_at predates the rotation")
    _source_command(source.get("command"), f"{field}.source.command")
    result = _mapping(source.get("result"), f"{field}.source.result")
    if result.get("version") != candidate.get("credential_version"):
        raise ShadowGateError(f"{field}.source.result.version does not match the candidate")
    result_updated_at = _timestamp(
        result.get("updated_at"),
        f"{field}.source.result.updated_at",
    )
    if result_updated_at != rotation_completed_at:
        raise ShadowGateError(
            f"{field}.source.result.updated_at does not match rotation_completed_at"
        )


def _validate_compatibility(value: Any, field: str) -> None:
    compatibility = _mapping(value, field)
    fallback_used = _boolean(compatibility.get("fallback_used"), f"{field}.fallback_used")
    if not fallback_used:
        return
    ladder = _mapping(compatibility.get("ladder"), f"{field}.ladder")
    _boolean(ladder.get("minimal_reproduction"), f"{field}.ladder.minimal_reproduction")
    _boolean(ladder.get("configuration_excluded"), f"{field}.ladder.configuration_excluded")
    _boolean(ladder.get("credentials_excluded"), f"{field}.ladder.credentials_excluded")
    _boolean(ladder.get("object_storage_excluded"), f"{field}.ladder.object_storage_excluded")
    _boolean(ladder.get("application_excluded"), f"{field}.ladder.application_excluded")
    _boolean(ladder.get("architecture_preserved"), f"{field}.ladder.architecture_preserved")
    attempts = ladder.get("repair_attempts")
    if not isinstance(attempts, int) or isinstance(attempts, bool) or attempts < 2:
        raise ShadowGateError(f"{field}.ladder.repair_attempts must be at least 2")
    selected_operator = _string(ladder.get("selected_operator"), f"{field}.ladder.selected_operator")
    selected_spark = _string(ladder.get("selected_spark"), f"{field}.ladder.selected_spark")
    options = ladder.get("options_tested")
    if not isinstance(options, list) or not options:
        raise ShadowGateError(f"{field}.ladder.options_tested must be a non-empty list")
    allowed = {
        ("1.0.0", "4.0.4", "1.11.0"),
        ("0.9.0", "3.5.3", "1.5.2"),
    }
    normalized: list[tuple[str, str, str]] = []
    for index, option in enumerate(options):
        item = _mapping(option, f"{field}.ladder.options_tested[{index}]")
        triple = (
            _string(item.get("operator"), f"{field}.ladder.options_tested[{index}].operator"),
            _string(item.get("spark"), f"{field}.ladder.options_tested[{index}].spark"),
            _string(item.get("iceberg"), f"{field}.ladder.options_tested[{index}].iceberg"),
        )
        if triple not in allowed:
            raise ShadowGateError(f"{field}.ladder.options_tested contains an unsupported runtime")
        normalized.append(triple)
    if (selected_operator, selected_spark, normalized[-1][2]) not in allowed:
        raise ShadowGateError(f"{field}.ladder selected runtime is unsupported")
    if normalized[-1][:2] != (selected_operator, selected_spark):
        raise ShadowGateError(f"{field}.ladder selected runtime must be the last tested option")
    if normalized[-1] == ("0.9.0", "3.5.3", "1.5.2") and normalized[:2] != [
        ("1.0.0", "4.0.4", "1.11.0"),
        ("0.9.0", "3.5.3", "1.5.2"),
    ]:
        raise ShadowGateError(f"{field}.ladder must test Spark 4.0.4 before Spark 3.5.3")


def _validate_passed_run(run: Mapping[str, Any], expected_digest: str, *, evidence_root: Path | None) -> None:
    _string(run.get("run_id"), "run_id")
    _timestamp(run.get("observed_at"), "observed_at")
    if run.get("status") != "passed":
        raise ShadowGateError("passed run status must be passed")
    _string(run.get("workflow_run"), "workflow_run")
    if run.get("target") != "shadow":
        raise ShadowGateError("target must be shadow")

    spark = _mapping(run.get("spark"), "spark")
    if spark.get("image_digest") != expected_digest:
        raise ShadowGateError("spark.image_digest does not match the candidate digest")
    if spark.get("api_version") != SPARK_API_VERSION:
        raise ShadowGateError(f"spark.api_version must be {SPARK_API_VERSION}")
    if spark.get("kind") != "SparkApplication":
        raise ShadowGateError("spark.kind must be SparkApplication")
    _string(spark.get("attempt_name"), "spark.attempt_name")

    trino = _mapping(run.get("trino"), "trino")
    _true_checks(trino, "trino", REQUIRED_TRINO_CHECKS)
    if trino.get("normalized_count") != 5 or trino.get("hourly_count") != 5 or trino.get("hourly_event_count_sum") != 5:
        raise ShadowGateError("trino counts must be 5 / 5 / 5")
    if not _boolean(run.get("authoritative_unchanged"), "authoritative_unchanged"):
        raise ShadowGateError("authoritative_unchanged must be true")
    _true_checks(run.get("kubernetes"), "kubernetes", REQUIRED_KUBERNETES_CHECKS)
    kubernetes = _mapping(run["kubernetes"], "kubernetes")
    if kubernetes.get("version") != "1.36":
        raise ShadowGateError("kubernetes.version must be 1.36")
    _true_checks(run.get("runtime_evidence"), "runtime_evidence", REQUIRED_RUNTIME_EVIDENCE)
    details = _artifacts(run.get("evidence"), root=evidence_root, run_id=str(run["run_id"]))
    spark_details = details["spark_application"]
    if spark_details.get("kind") != "SparkApplication" or spark_details.get("api_version") != SPARK_API_VERSION:
        raise ShadowGateError("spark_application evidence must identify SparkApplication")
    if spark_details.get("image_digest") != expected_digest or spark_details.get("attempt_name") != spark["attempt_name"]:
        raise ShadowGateError("spark_application evidence identity does not match the run")
    if spark_details.get("state") != "COMPLETED":
        raise ShadowGateError("spark_application evidence must show COMPLETED")
    workflow_details = details["workflow_run"]
    if workflow_details.get("dag_id") != "airflow_spark_lakehouse" or workflow_details.get("status") != "success":
        raise ShadowGateError("workflow_run evidence must show the accepted DAG success")
    trino_details = details["trino"]
    if (
        trino_details.get("normalized_count"),
        trino_details.get("hourly_count"),
        trino_details.get("hourly_event_count_sum"),
    ) != (5, 5, 5):
        raise ShadowGateError("trino evidence must contain 5 / 5 / 5 counts")
    if trino_details.get("write_denial_authoritative") is not True or trino_details.get("write_denial_shadow") is not True:
        raise ShadowGateError("trino evidence must show write denial for both catalogs")
    authoritative = details["authoritative_state"]
    if authoritative.get("before") != authoritative.get("after"):
        raise ShadowGateError("authoritative state changed during the shadow run")
    runtime = details["runtime"]
    for key, expected in {
        "spark_version": "4.1.3",
        "scala_version": "2.13",
        "java_version": "21",
        "python_version": "3.12",
        "hadoop_version": "3.4.2",
        "iceberg_version": "1.11.0",
    }.items():
        if runtime.get(key) != expected:
            raise ShadowGateError(f"runtime evidence {key} does not match the selected runtime")
    kubernetes_details = details["kubernetes"]
    if kubernetes_details.get("version") != "1.36" or not all(
        kubernetes_details.get(key) is True for key in REQUIRED_KUBERNETES_CHECKS
    ):
        raise ShadowGateError("kubernetes evidence is incomplete")
    loki_details = details["loki"]
    if not isinstance(loki_details.get("unique_markers"), list) or not loki_details["unique_markers"]:
        raise ShadowGateError("loki evidence must contain unique markers")
    if loki_details.get("containers_exited") is not True:
        raise ShadowGateError("loki evidence must cover exited containers")
    history_details = details["history_server"]
    _string(history_details.get("application_id"), "history_server.application_id")
    if history_details.get("event_log_source") != "seaweedfs":
        raise ShadowGateError("history_server evidence must use SeaweedFS event logs")
    _validate_compatibility(run.get("compatibility"), "compatibility")


def _validate_failed_run(run: Mapping[str, Any]) -> None:
    _string(run.get("run_id"), "run_id")
    _timestamp(run.get("observed_at"), "observed_at")
    if run.get("status") != "failed":
        raise ShadowGateError("run status must be passed or failed")
    _string(run.get("failure_reason"), "failure_reason")
    _string(run.get("failure_evidence"), "failure_evidence")


def load_shadow_gate(path: Path) -> dict[str, Any]:
    """Read one JSON evidence ledger without modifying it."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ShadowGateError("shadow gate ledger cannot be read") from error
    return load_shadow_gate_from_mapping(value)


def expected_spark_image_digest(dag_path: Path) -> str:
    """Read the single immutable Spark image digest from the DAG source."""
    source = dag_path.read_text(encoding="utf-8")
    digests = sorted(set(re.findall(r"@(?P<digest>sha256:[0-9a-f]{64})", source)))
    if len(digests) != 1:
        raise ShadowGateError("DAG must contain exactly one Spark image digest")
    return digests[0]


def evaluate_shadow_gate(
    ledger: Mapping[str, Any],
    *,
    expected_digest: str,
    evidence_root: Path | None = None,
) -> dict[str, Any]:
    """Return a falsifiable gate result for the latest consecutive run suffix."""
    if not _DIGEST.fullmatch(expected_digest):
        raise ShadowGateError("expected digest must be a SHA-256 digest")
    loaded = load_shadow_gate_from_mapping(ledger)
    candidate = loaded["candidate"]
    credential_epoch = str(candidate["credential_epoch"])
    errors: list[str] = []
    if candidate["spark_image_digest"] != expected_digest:
        errors.append("candidate digest does not match the expected digest")
    try:
        _validate_credential_rotation(candidate, loaded["runs"], evidence_root=evidence_root)
    except ShadowGateError as error:
        errors.append(str(error))
    seen_run_ids: set[str] = set()
    seen_workflow_runs: set[str] = set()
    seen_attempts: set[str] = set()
    consecutive: list[str] = []
    suffix_errors: list[str] = []
    previous_observed_at: datetime | None = None
    for index, run in enumerate(loaded["runs"], start=1):
        try:
            run_id = _string(run.get("run_id"), f"runs[{index}].run_id")
            if run_id in seen_run_ids:
                raise ShadowGateError("run_id is duplicated")
            seen_run_ids.add(run_id)
            observed = _timestamp(run.get("observed_at"), f"runs[{index}].observed_at")
            if previous_observed_at and observed <= previous_observed_at:
                raise ShadowGateError("observed_at values must increase")
            previous_observed_at = observed
            if run.get("credential_epoch") != credential_epoch:
                raise ShadowGateError("credential_epoch does not match the candidate epoch")
            if run.get("status") == "passed":
                workflow_run = _string(run.get("workflow_run"), f"runs[{index}].workflow_run")
                if workflow_run in seen_workflow_runs:
                    raise ShadowGateError("workflow_run is duplicated")
                seen_workflow_runs.add(workflow_run)
                _validate_passed_run(run, expected_digest, evidence_root=evidence_root)
                if suffix_errors:
                    suffix_errors = []
                attempt_name = str(run["spark"]["attempt_name"])
                if attempt_name in seen_attempts:
                    raise ShadowGateError("spark.attempt_name is duplicated")
                seen_attempts.add(attempt_name)
                consecutive.append(run_id)
            elif run.get("status") == "failed":
                workflow_run = _string(run.get("workflow_run", run_id), f"runs[{index}].workflow_run")
                if workflow_run in seen_workflow_runs:
                    raise ShadowGateError("workflow_run is duplicated")
                seen_workflow_runs.add(workflow_run)
                _validate_failed_run(run)
                consecutive = []
                suffix_errors = []
            else:
                raise ShadowGateError("run status must be passed or failed")
        except (KeyError, TypeError, ValueError, ShadowGateError) as error:
            suffix_errors = [f"runs[{index}]: {error}"]
            consecutive = []
    suffix_valid = len(consecutive) >= REQUIRED_RUNS
    errors.extend(suffix_errors)
    eligible = not errors and suffix_valid
    if not suffix_valid:
        errors.append(f"only {len(consecutive)} consecutive passed runs; need {REQUIRED_RUNS}")
    return {
        "eligible": eligible,
        "required_runs": REQUIRED_RUNS,
        "consecutive_passes": len(consecutive),
        "run_ids": consecutive[-REQUIRED_RUNS:],
        "errors": errors,
        "candidate": dict(candidate),
    }


def load_shadow_gate_from_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate an in-memory ledger with the same schema as the file reader."""
    envelope = _mapping(value, "ledger")
    if envelope.get("schema_version") != LEDGER_SCHEMA_VERSION:
        raise ShadowGateError("unsupported shadow gate schema version")
    candidate = _mapping(envelope.get("candidate"), "candidate")
    digest = _string(candidate.get("spark_image_digest"), "candidate.spark_image_digest")
    if not _DIGEST.fullmatch(digest):
        raise ShadowGateError("candidate.spark_image_digest must be a SHA-256 digest")
    if candidate.get("spark_api_version") != SPARK_API_VERSION:
        raise ShadowGateError(f"candidate.spark_api_version must be {SPARK_API_VERSION}")
    _string(candidate.get("source_revision"), "candidate.source_revision")
    airflow_digest = _string(candidate.get("airflow_image_digest"), "candidate.airflow_image_digest")
    if not _DIGEST.fullmatch(airflow_digest):
        raise ShadowGateError("candidate.airflow_image_digest must be a SHA-256 digest")
    _positive_integer(candidate.get("credential_version"), "candidate.credential_version")
    _string(candidate.get("credential_owner"), "candidate.credential_owner")
    _string(candidate.get("credential_epoch"), "candidate.credential_epoch")
    _string(candidate.get("credential_rotation_receipt"), "candidate.credential_rotation_receipt")
    runs = envelope.get("runs")
    if not isinstance(runs, list) or not runs:
        raise ShadowGateError("runs must be a non-empty list")
    if any(not isinstance(run, Mapping) for run in runs):
        raise ShadowGateError("runs must contain objects")
    return {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "candidate": dict(candidate),
        "runs": [dict(run) for run in runs],
    }
