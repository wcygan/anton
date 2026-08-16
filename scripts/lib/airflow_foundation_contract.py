"""Structured source contract for the Airflow foundation and Spark adapter."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
AIRFLOW_ROOT = REPO / "kubernetes" / "apps" / "airflow"
DATABASE_APP = AIRFLOW_ROOT / "airflow-database" / "app"
DATABASE_KS = AIRFLOW_ROOT / "airflow-database" / "ks.yaml"
RELEASE_APP = AIRFLOW_ROOT / "airflow" / "app"
IMAGE_ROOT = REPO / "images" / "airflow-runtime"
LONGHORN_RELEASE = (
    REPO / "kubernetes" / "apps" / "storage" / "longhorn" / "app" / "helmrelease.yaml"
)
LONGHORN_KS = REPO / "kubernetes" / "apps" / "storage" / "longhorn" / "ks.yaml"
STORAGE_ROOT = REPO / "kubernetes" / "apps" / "storage" / "kustomization.yaml"
RETIRED_BACKUP_APP = REPO / "kubernetes" / "apps" / "storage" / "longhorn-backup-config"

IMAGE_TAG = "3.2.2-apache.11"
IMAGE_DIGEST = "sha256:dbbfdfdf958c0cc7fc0ebbdeac802cd7619de231d304c4af94cd532ba4636881"
IMAGE_DIGEST_HEX = IMAGE_DIGEST.removeprefix("sha256:")
AIRFLOW_SPARK_RBAC = REPO / "kubernetes" / "apps" / "lakehouse" / "airflow-spark-rbac.yaml"


def load_yaml(path: Path) -> dict[str, Any]:
    result = subprocess.run(
        ["yq", "-o=json", "-I=0", ".", str(path)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise ValueError(result.stderr.strip())
    document = json.loads(result.stdout)
    if not isinstance(document, dict):
        raise ValueError(f"expected one YAML object in {path}")
    return document


def load_yaml_text(source: str, owner: str) -> list[dict[str, Any]]:
    result = subprocess.run(
        ["yq", "-o=json", "-I=0", "."],
        input=source,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise ValueError(f"{owner}: {result.stderr.strip()}")
    document = json.loads(result.stdout)
    documents = document if isinstance(document, list) else [document]
    if not documents or not all(isinstance(item, dict) for item in documents):
        raise ValueError(f"{owner}: expected one or more YAML objects")
    return documents


def nested(value: Any, *path: str) -> Any:
    current = value
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def expect_equal(
    failures: list[str],
    owner: str,
    actual: Any,
    expected: Any,
) -> None:
    if actual != expected:
        failures.append(f"{owner}: expected {expected!r}, found {actual!r}")


def expect_absent(failures: list[str], owner: str, mapping: Any, key: str) -> None:
    if isinstance(mapping, dict) and key in mapping:
        failures.append(f"{owner}: {key!r} must be absent")


def validate_release(release: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    expect_equal(failures, "Airflow kind", release.get("kind"), "HelmRelease")
    expect_equal(failures, "Airflow name", nested(release, "metadata", "name"), "airflow")
    expect_equal(
        failures,
        "Airflow chart version",
        nested(release, "spec", "chart", "spec", "version"),
        "1.22.0",
    )

    values = nested(release, "spec", "values")
    if not isinstance(values, dict):
        return failures + ["Airflow HelmRelease: spec.values must be an object"]

    expect_equal(failures, "Airflow version", values.get("airflowVersion"), "3.2.2")
    expect_equal(failures, "Airflow executor", values.get("executor"), "KubernetesExecutor")
    expect_equal(failures, "Airflow pod launch", values.get("allowPodLaunching"), True)
    expect_equal(failures, "Airflow namespace mode", values.get("multiNamespaceMode"), False)

    expected_images = {
        "airflow": {
            "repository": "192.168.1.106/library/airflow-runtime",
            "tag": IMAGE_TAG,
            "digest": IMAGE_DIGEST,
            "pullPolicy": "IfNotPresent",
        },
        "pod_template": {
            "repository": "192.168.1.106/library/airflow-runtime@sha256",
            "tag": IMAGE_DIGEST_HEX,
            "pullPolicy": "IfNotPresent",
        },
    }
    expect_equal(failures, "Airflow immutable images", values.get("images"), expected_images)

    expect_equal(
        failures,
        "Airflow metadata Secret",
        nested(values, "data", "metadataSecretName"),
        "airflow-postgres-bootstrap",
    )
    expect_equal(
        failures,
        "Airflow built-in database URI variable",
        nested(values, "enableBuiltInSecretEnvVars", "AIRFLOW__DATABASE__SQL_ALCHEMY_CONN"),
        False,
    )
    expect_equal(
        failures,
        "Airflow built-in database connection variable",
        nested(values, "enableBuiltInSecretEnvVars", "AIRFLOW_CONN_AIRFLOW_DB"),
        False,
    )

    expected_database_environment = [
        {
            "name": "AIRFLOW__DATABASE__SQL_ALCHEMY_CONN",
            "valueFrom": {
                "secretKeyRef": {
                    "name": "airflow-postgres-bootstrap",
                    "key": "connection",
                }
            },
        },
        {
            "name": "AIRFLOW_CONN_AIRFLOW_DB",
            "valueFrom": {
                "secretKeyRef": {
                    "name": "airflow-postgres-bootstrap",
                    "key": "connection",
                }
            },
        },
    ]
    extra_environment = values.get("extraEnv")
    if not isinstance(extra_environment, str):
        failures.append("Airflow database environment: extraEnv must be YAML text")
    else:
        try:
            parsed_environment = load_yaml_text(extra_environment, "Airflow database environment")
        except (json.JSONDecodeError, ValueError) as error:
            failures.append(str(error))
        else:
            expect_equal(
                failures,
                "Airflow database environment",
                parsed_environment,
                expected_database_environment,
            )

    expect_equal(
        failures,
        "Airflow Fernet Secret",
        values.get("fernetKeySecretName"),
        "airflow-postgres-bootstrap",
    )
    expect_equal(
        failures,
        "Airflow JWT Secret",
        values.get("jwtSecretName"),
        "airflow-postgres-bootstrap",
    )

    expected_components = {
        "apiServer": {
            "requests": {"cpu": "100m", "memory": "512Mi"},
            "limits": {"cpu": "500m", "memory": "1Gi"},
        },
        "scheduler": {
            "requests": {"cpu": "250m", "memory": "768Mi"},
            "limits": {"cpu": "1", "memory": "1536Mi"},
        },
        "dagProcessor": {
            "requests": {"cpu": "100m", "memory": "512Mi"},
            "limits": {"cpu": "500m", "memory": "1Gi"},
        },
        "triggerer": {
            "requests": {"cpu": "100m", "memory": "512Mi"},
            "limits": {"cpu": "500m", "memory": "1Gi"},
        },
    }
    for component, resources in expected_components.items():
        expect_equal(
            failures,
            f"Airflow HelmRelease {component} replicas",
            nested(values, component, "replicas"),
            1,
        )
        expect_equal(
            failures,
            f"Airflow HelmRelease {component} resources",
            nested(values, component, "resources"),
            resources,
        )

    expected_task_account = {
        "create": True,
        "name": "airflow-spark-submit",
        "automountServiceAccountToken": True,
    }
    expect_equal(
        failures,
        "Airflow HelmRelease task service account",
        nested(values, "workers", "kubernetes", "serviceAccount"),
        expected_task_account,
    )
    expect_equal(
        failures,
        "Airflow task resources",
        nested(values, "workers", "kubernetes", "resources"),
        {
            "requests": {"cpu": "100m", "memory": "256Mi"},
            "limits": {"cpu": "500m", "memory": "768Mi"},
        },
    )
    expect_equal(
        failures,
        "Airflow migration resources",
        nested(values, "migrateDatabaseJob", "resources"),
        {
            "requests": {"cpu": "100m", "memory": "256Mi"},
            "limits": {"cpu": "500m", "memory": "768Mi"},
        },
    )
    expect_equal(
        failures,
        "Airflow migration Job enabled",
        nested(values, "migrateDatabaseJob", "enabled"),
        True,
    )
    expect_equal(
        failures,
        "Airflow Flux migration Job hooks",
        nested(values, "migrateDatabaseJob", "useHelmHooks"),
        False,
    )
    expect_equal(
        failures,
        "Airflow migration custom environment",
        nested(values, "migrateDatabaseJob", "applyCustomEnv"),
        False,
    )
    expect_equal(
        failures,
        "Airflow migration database environment",
        nested(values, "migrateDatabaseJob", "env"),
        expected_database_environment,
    )
    expect_equal(
        failures,
        "Airflow cleanup resources",
        nested(values, "cleanup", "resources"),
        {
            "requests": {"cpu": "50m", "memory": "128Mi"},
            "limits": {"cpu": "250m", "memory": "256Mi"},
        },
    )
    expect_equal(
        failures,
        "Airflow worker image repository",
        nested(values, "config", "kubernetes_executor", "worker_container_repository"),
        "192.168.1.106/library/airflow-runtime@sha256",
    )
    expect_equal(
        failures,
        "Airflow worker image tag",
        nested(values, "config", "kubernetes_executor", "worker_container_tag"),
        IMAGE_DIGEST_HEX,
    )
    expect_equal(
        failures,
        "Airflow task pod deletion",
        nested(values, "config", "kubernetes_executor", "delete_worker_pods"),
        "False",
    )
    expect_equal(
        failures,
        "Airflow failed task pod deletion",
        nested(values, "config", "kubernetes_executor", "delete_worker_pods_on_failure"),
        "False",
    )
    for embedded in ("postgresql", "redis", "pgbouncer", "statsd", "flower"):
        expect_equal(
            failures,
            f"Airflow embedded {embedded}",
            nested(values, embedded, "enabled"),
            False,
        )
    return failures


def validate_database_source(failures: list[str]) -> None:
    cluster = load_yaml(DATABASE_APP / "postgres-cluster.yaml")
    credentials = load_yaml(DATABASE_APP / "externalsecret.yaml")
    kustomization = load_yaml(DATABASE_APP / "kustomization.yaml")
    flux_kustomization = load_yaml(DATABASE_KS)

    expect_equal(failures, "Airflow CNPG name", nested(cluster, "metadata", "name"), "airflow-postgres")
    expect_equal(failures, "Airflow CNPG instances", nested(cluster, "spec", "instances"), 1)
    expect_equal(
        failures,
        "Airflow CNPG image",
        nested(cluster, "spec", "imageName"),
        "ghcr.io/cloudnative-pg/postgresql:17.2",
    )
    expect_equal(
        failures,
        "Airflow CNPG storage",
        nested(cluster, "spec", "storage"),
        {"storageClass": "longhorn", "size": "10Gi"},
    )
    expect_equal(
        failures,
        "Airflow CNPG resources",
        nested(cluster, "spec", "resources"),
        {
            "requests": {"cpu": "100m", "memory": "512Mi"},
            "limits": {"cpu": "500m", "memory": "1Gi"},
        },
    )
    expect_equal(
        failures,
        "Airflow CNPG bootstrap Secret",
        nested(cluster, "spec", "bootstrap", "initdb", "secret", "name"),
        "airflow-postgres-bootstrap",
    )
    expect_absent(failures, "Airflow CNPG pending backup", nested(cluster, "spec"), "backup")

    failures.extend(validate_credentials(credentials))

    expect_equal(
        failures,
        "Airflow database app resources",
        kustomization.get("resources"),
        ["./externalsecret.yaml", "./postgres-cluster.yaml"],
    )
    if (DATABASE_APP / "scheduled-backup.yaml").exists():
        failures.append("Airflow scheduled backup must wait for an independent target")

    expected_dependencies = {
        ("cloudnative-pg", "databases"),
        ("external-secrets", "external-secrets"),
        ("longhorn", "storage"),
    }
    observed_dependencies = {
        (dependency.get("name"), dependency.get("namespace", "flux-system"))
        for dependency in nested(flux_kustomization, "spec", "dependsOn") or []
        if isinstance(dependency, dict)
    }
    expect_equal(
        failures,
        "Airflow database dependencies",
        observed_dependencies,
        expected_dependencies,
    )
    expected_health_checks = {
        ("v1", "Secret", "airflow-postgres-bootstrap", "airflow"),
        ("postgresql.cnpg.io/v1", "Cluster", "airflow-postgres", "airflow"),
    }
    observed_health_checks = {
        (
            check.get("apiVersion"),
            check.get("kind"),
            check.get("name"),
            check.get("namespace"),
        )
        for check in nested(flux_kustomization, "spec", "healthChecks") or []
        if isinstance(check, dict)
    }
    expect_equal(
        failures,
        "Airflow database health checks",
        observed_health_checks,
        expected_health_checks,
    )


def validate_credentials(credentials: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    expect_equal(
        failures,
        "Airflow ExternalSecret name",
        nested(credentials, "metadata", "name"),
        "airflow-postgres-bootstrap",
    )
    expect_equal(
        failures,
        "Airflow ExternalSecret refresh policy",
        nested(credentials, "spec", "refreshPolicy"),
        "OnChange",
    )
    expect_absent(
        failures,
        "Airflow ExternalSecret refresh",
        nested(credentials, "spec"),
        "refreshInterval",
    )
    expect_equal(
        failures,
        "Airflow ExternalSecret store",
        nested(credentials, "spec", "secretStoreRef"),
        {"kind": "ClusterSecretStore", "name": "onepassword-connect"},
    )
    expect_equal(
        failures,
        "Airflow ExternalSecret extraction",
        nested(credentials, "spec", "dataFrom"),
        [{"extract": {"key": "airflow-postgres"}}],
    )
    expect_absent(failures, "Airflow ExternalSecret direct references", nested(credentials, "spec"), "data")
    expect_equal(
        failures,
        "Airflow ExternalSecret target",
        nested(credentials, "spec", "target", "name"),
        "airflow-postgres-bootstrap",
    )
    template_data = nested(credentials, "spec", "target", "template", "data")
    if not isinstance(template_data, dict):
        failures.append("Airflow ExternalSecret template data must be an object")
    else:
        expect_equal(
            failures,
            "Airflow ExternalSecret template keys",
            set(template_data),
            {"username", "password", "connection", "fernet-key", "jwt-secret"},
        )
        connection = template_data.get("connection")
        if not isinstance(connection, str) or "urlquery" not in connection:
            failures.append("Airflow ExternalSecret connection must URL-encode credentials")
    return failures


def validate_backup_safety(failures: list[str]) -> None:
    if RETIRED_BACKUP_APP.exists() and any(
        item.is_file() for item in RETIRED_BACKUP_APP.rglob("*")
    ):
        failures.append("Longhorn backup target must not share the Longhorn failure domain")

    failures.extend(validate_longhorn_release(load_yaml(LONGHORN_RELEASE)))

    storage_root = load_yaml(STORAGE_ROOT)
    resources = storage_root.get("resources", [])
    if "./longhorn-backup-config/ks.yaml" in resources:
        failures.append("Storage root still references the same-domain backup app")

    longhorn_kustomization = load_yaml(LONGHORN_KS)
    dependencies = nested(longhorn_kustomization, "spec", "dependsOn") or []
    if any(
        isinstance(dependency, dict) and dependency.get("name") == "longhorn-backup-config"
        for dependency in dependencies
    ):
        failures.append("Longhorn still depends on the same-domain backup app")


def validate_longhorn_release(release: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    values = nested(release, "spec", "values")
    expect_absent(failures, "Longhorn backup target", values, "defaultBackupStore")
    return failures


def validate_image_source(failures: list[str]) -> None:
    dockerfile = (IMAGE_ROOT / "Dockerfile").read_text(encoding="utf-8")
    required_dockerfile = (
        "apache/airflow:3.2.2-python3.12@sha256:",
        "ARG AIRFLOW_VERSION=3.2.2",
        "ARG PYTHON_VERSION=3.12",
        "ARG KUBERNETES_PROVIDER_VERSION=10.21.0",
        "ARG OFFICIAL_PROVIDER_VERSION=10.17.1",
        "ARG AIRFLOW_CONSTRAINTS_SHA256=dd09ca7bc7da06f209dbc57005c38beccad9464e8d33e55598519d904e798c85",
        "source.count(old) != 1",
        "pip check",
        "FROM runtime AS test",
        "COPY --from=test /tmp/airflow-runtime-tests.pass /opt/airflow/runtime-contract/tests.pass",
        'assert anton_airflow.spark.PACKAGE_VERSION == "0.3.0"',
    )
    failures.extend(
        f"Airflow image missing {value!r}" for value in required_dockerfile if value not in dockerfile
    )

    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            IMAGE_ROOT / "dags" / "airflow_kubernetes_foundation.py",
            IMAGE_ROOT / "src" / "anton_airflow" / "spark" / "__init__.py",
            IMAGE_ROOT / "src" / "anton_airflow" / "spark" / "identity.py",
            IMAGE_ROOT / "src" / "anton_airflow" / "spark" / "state.py",
            IMAGE_ROOT / "src" / "anton_airflow" / "spark" / "lease.py",
            IMAGE_ROOT / "src" / "anton_airflow" / "spark" / "adapter.py",
            IMAGE_ROOT / "src" / "anton_airflow" / "spark" / "receipts.py",
            IMAGE_ROOT / "src" / "anton_airflow" / "spark" / "operator.py",
            IMAGE_ROOT / "src" / "anton_airflow" / "spark" / "trigger.py",
            IMAGE_ROOT / "src" / "anton_airflow" / "loki.py",
            IMAGE_ROOT / "src" / "anton_airflow" / "flight_recorder.py",
            IMAGE_ROOT / "src" / "anton_airflow" / "lakehouse.py",
            IMAGE_ROOT / "tests" / "test_adapter_package.py",
            IMAGE_ROOT / "tests" / "test_ticket06_recovery.py",
            IMAGE_ROOT / "dags" / "airflow_spark_lakehouse.py",
            IMAGE_ROOT / "dags" / "airflow_flight_recorder.py",
        )
    )
    required_source = (
        'dag_id="airflow_kubernetes_foundation"',
        "schedule=None",
        "max_active_runs=1",
        '"event": "airflow-foundation-pass"',
        "def foundation_marker(",
        "test_runtime_versions_are_exact",
        "test_foundation_dag_is_manual_and_bounded",
        "class AttemptIdentity",
        "NUL separators",
        "class ApacheSparkApplicationOperator",
        "class SparkApplicationTrigger",
        "stateTransitionHistory",
        "class LeaseCoordinator",
        "spark_attempt_receipt",
        "task_completion",
        "prior_output_validator",
        "test_triggerer_recovery_renews_lease_before_terminal_observation",
        "spark.apache.org",
        'dag_id="airflow_spark_lakehouse",\n    schedule="23 * * * *",',
        'dag_id="airflow_flight_recorder",\n    schedule=None,',
        "class FlightRecorderSparkOperator",
        "FLIGHT_RECORDER_APPLICATION_SPEC",
        "catchup=False",
        "max_active_runs=1",
    )
    failures.extend(
        f"Airflow image content missing {value!r}" for value in required_source if value not in source
    )
    retired_shadow_paths = (
        IMAGE_ROOT / "dags" / "airflow_loki_source.py",
        IMAGE_ROOT / "src" / "anton_airflow" / "loki_operator.py",
        IMAGE_ROOT / "src" / "anton_airflow" / "shadow_validation.py",
    )
    failures.extend(
        f"retired shadow image path remains: {path.relative_to(REPO)}"
        for path in retired_shadow_paths
        if path.exists()
    )
    for retired_name in ("SHADOW_APPLICATION_SPEC", "LOKI_APPLICATION_SPEC"):
        if retired_name in source:
            failures.append(f"Airflow image still defines {retired_name}")


def validate_spark_rbac(failures: list[str]) -> None:
    """Validate the namespace-only Airflow permissions for Spark attempts."""
    try:
        result = subprocess.run(
            ["yq", "eval-all", "-o=json", "-I=0", "[.]", str(AIRFLOW_SPARK_RBAC)],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        documents = json.loads(result.stdout)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        failures.append(f"Airflow Spark RBAC parse failed: {error}")
        return
    if not isinstance(documents, list) or not all(isinstance(item, dict) for item in documents):
        failures.append("Airflow Spark RBAC must contain Role and RoleBinding documents")
        return
    role = next((item for item in documents if item.get("kind") == "Role"), None)
    binding = next((item for item in documents if item.get("kind") == "RoleBinding"), None)
    if role is None or binding is None:
        failures.append("Airflow Spark RBAC must contain one Role and one RoleBinding")
        return
    expected_rules = {
        ("spark.apache.org", "sparkapplications"): {"get", "list", "watch", "create", "delete"},
        ("coordination.k8s.io", "leases"): {"get", "list", "watch", "create", "update", "patch", "delete"},
        ("", "pods"): {"get", "list", "watch"},
        ("", "pods/log"): {"get"},
        ("", "events"): {"get", "list", "watch"},
    }
    observed: dict[tuple[str, str], set[str]] = {}
    rules = role.get("rules", [])
    if not isinstance(rules, list) or not all(isinstance(rule, dict) for rule in rules):
        failures.append("Airflow Spark Role rules must be mappings")
        return
    for rule in rules:
        groups = rule.get("apiGroups", [])
        resources = rule.get("resources", [])
        if len(groups) == 1:
            for resource in resources:
                observed[(groups[0], resource)] = set(rule.get("verbs", []))
    expect_equal(failures, "Airflow Spark Role rules", observed, expected_rules)
    binding_subjects = binding.get("subjects", [])
    if not isinstance(binding_subjects, list) or not all(isinstance(item, dict) for item in binding_subjects):
        failures.append("Airflow Spark RoleBinding subjects must be mappings")
        return
    subjects = {(item.get("kind"), item.get("name"), item.get("namespace")) for item in binding_subjects}
    expect_equal(
        failures,
        "Airflow Spark RoleBinding subjects",
        subjects,
        {("ServiceAccount", "airflow-spark-submit", "airflow"), ("ServiceAccount", "airflow-triggerer", "airflow")},
    )


def validate_namespace_source(failures: list[str]) -> None:
    kustomization = load_yaml(AIRFLOW_ROOT / "kustomization.yaml")
    expect_equal(
        failures,
        "Airflow namespace resources",
        kustomization.get("resources"),
        ["./namespace.yaml", "./airflow-database/ks.yaml", "./airflow/ks.yaml", "./flight-recorder/ks.yaml"],
    )
    readme = (AIRFLOW_ROOT / "README.md").read_text(encoding="utf-8")
    if "Kubernetes 1.36" not in readme:
        failures.append("Airflow README must record Kubernetes 1.36 as the local target")


def validate_kustomize(failures: list[str], path: Path) -> None:
    result = subprocess.run(
        ["kustomize", "build", str(path)],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if result.returncode != 0:
        failures.append(f"Kustomize render {path.relative_to(REPO)}: {result.stderr.strip()}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", type=Path, help="Validate one HelmRelease candidate")
    parser.add_argument("--credentials", type=Path, help="Validate one ExternalSecret candidate")
    parser.add_argument(
        "--longhorn-release",
        type=Path,
        help="Validate one Longhorn HelmRelease candidate",
    )
    return parser.parse_args()


def report(failures: list[str], success: str) -> int:
    if failures:
        for failure in failures:
            print(f"[airflow.foundation] {failure}", file=sys.stderr)
        return 1
    print(success)
    return 0


def main() -> int:
    args = parse_args()
    if args.release is not None:
        try:
            failures = validate_release(load_yaml(args.release))
        except (json.JSONDecodeError, OSError, ValueError) as error:
            failures = [f"Airflow HelmRelease parse failed: {error}"]
        return report(failures, "Airflow HelmRelease contract: PASS")
    if args.credentials is not None:
        try:
            failures = validate_credentials(load_yaml(args.credentials))
        except (json.JSONDecodeError, OSError, ValueError) as error:
            failures = [f"Airflow ExternalSecret parse failed: {error}"]
        return report(failures, "Airflow ExternalSecret contract: PASS")
    if args.longhorn_release is not None:
        try:
            failures = validate_longhorn_release(load_yaml(args.longhorn_release))
        except (json.JSONDecodeError, OSError, ValueError) as error:
            failures = [f"Longhorn HelmRelease parse failed: {error}"]
        return report(failures, "Longhorn backup safety contract: PASS")

    failures: list[str] = []
    try:
        validate_image_source(failures)
        validate_spark_rbac(failures)
        validate_namespace_source(failures)
        failures.extend(validate_release(load_yaml(RELEASE_APP / "helmrelease.yaml")))
        validate_database_source(failures)
        validate_backup_safety(failures)
        for path in (AIRFLOW_ROOT, DATABASE_APP, RELEASE_APP):
            validate_kustomize(failures, path)
    except (json.JSONDecodeError, OSError, ValueError) as error:
        failures.append(f"Airflow source parse failed: {error}")

    return report(failures, "Airflow Kubernetes foundation contract: PASS")
