#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Validate the source contract for the ticket 04 Airflow foundation."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
IMAGE = REPO / "images" / "airflow-runtime"
AIRFLOW = REPO / "kubernetes" / "apps" / "airflow"
DATABASE = AIRFLOW / "airflow-database" / "app"
RELEASE = AIRFLOW / "airflow" / "app"
BACKUP = REPO / "kubernetes" / "apps" / "storage" / "longhorn-backup-config" / "app"
LONGHORN_RELEASE = REPO / "kubernetes" / "apps" / "storage" / "longhorn" / "app" / "helmrelease.yaml"
STORAGE_ROOT = REPO / "kubernetes" / "apps" / "storage" / "kustomization.yaml"
LONGHORN_KS = REPO / "kubernetes" / "apps" / "storage" / "longhorn" / "ks.yaml"
SEAWEED_CRONJOB = REPO / "kubernetes" / "apps" / "storage" / "seaweedfs-config" / "app" / "buckets-cronjob.yaml"
SEAWEED_SECRET = REPO / "kubernetes" / "apps" / "storage" / "seaweedfs-config" / "app" / "externalsecret.yaml"
SEAWEED = REPO / "kubernetes" / "apps" / "storage" / "seaweedfs-config" / "app" / "seaweed.yaml"

IMAGE_DIGEST = "sha256:9ccd3dcff1f11535c3915434c40602f443c4d5f160673c7f9ced4af094957065"


def require(failures: list[str], text: str, values: tuple[str, ...], owner: str) -> None:
    failures.extend(f"{owner} missing {value!r}" for value in values if value not in text)


def validate_kustomize(failures: list[str], path: Path) -> None:
    result = subprocess.run(
        ["kustomize", "build", str(path)],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if result.returncode != 0:
        failures.append(f"Kustomize render {path.relative_to(REPO)}: {result.stderr.strip()}")


def main() -> int:
    failures: list[str] = []

    dockerfile = (IMAGE / "Dockerfile").read_text(encoding="utf-8")
    require(
        failures,
        dockerfile,
        (
            "apache/airflow:3.2.2-python3.12@sha256:",
            "ARG AIRFLOW_VERSION=3.2.2",
            "ARG PYTHON_VERSION=3.12",
            "ARG KUBERNETES_PROVIDER_VERSION=10.21.0",
            "ARG OFFICIAL_PROVIDER_VERSION=10.17.1",
            "ARG AIRFLOW_CONSTRAINTS_SHA256=dd09ca7bc7da06f209dbc57005c38beccad9464e8d33e55598519d904e798c85",
            "constraints-",
            "source.count(old) != 1",
            "pip check",
            "FROM runtime AS test",
            "COPY --from=test /tmp/airflow-runtime-tests.pass",
        ),
        "Airflow image",
    )

    dag = (IMAGE / "dags" / "airflow_kubernetes_foundation.py").read_text(encoding="utf-8")
    package = (IMAGE / "src" / "anton_airflow" / "spark" / "__init__.py").read_text(encoding="utf-8")
    image_tests = (IMAGE / "tests" / "test_adapter_package.py").read_text(encoding="utf-8")
    require(
        failures,
        dag + package + image_tests,
        (
            'dag_id="airflow_kubernetes_foundation"',
            "schedule=None",
            "max_active_runs=1",
            '"event": "airflow-foundation-pass"',
            "def foundation_marker(",
            "test_runtime_versions_are_exact",
            "test_foundation_dag_is_manual_and_bounded",
        ),
        "Airflow image content",
    )

    namespace = (AIRFLOW / "kustomization.yaml").read_text(encoding="utf-8")
    readme = (AIRFLOW / "README.md").read_text(encoding="utf-8")
    require(
        failures,
        namespace + readme,
        ("./namespace.yaml", "./airflow-database/ks.yaml", "./airflow/ks.yaml", "Kubernetes 1.36"),
        "Airflow namespace",
    )

    release = (RELEASE / "helmrelease.yaml").read_text(encoding="utf-8")
    require(
        failures,
        release,
        (
            "version: 1.22.0",
            "executor: KubernetesExecutor",
            "airflowVersion: \"3.2.2\"",
            f"digest: {IMAGE_DIGEST}",
            f"tag: {IMAGE_DIGEST.removeprefix('sha256:')}",
            "metadataSecretName: airflow-postgres-credentials",
            "fernetKeySecretName: airflow-postgres-credentials",
            "jwtSecretName: airflow-postgres-credentials",
            "name: airflow-task",
            "automountServiceAccountToken: false",
            "delete_worker_pods: \"False\"",
            "cleanup:",
            "postgresql:\n      enabled: false",
        ),
        "Airflow HelmRelease",
    )
    for component in ("apiServer", "scheduler", "dagProcessor", "triggerer"):
        if f"    {component}:" not in release:
            failures.append(f"Airflow HelmRelease missing {component} settings")
    if release.count("replicas: 1") < 4:
        failures.append("Airflow HelmRelease must set four control-plane replicas to one")
    if release.count("requests:") < 7 or release.count("limits:") < 7:
        failures.append("Airflow HelmRelease must bound control-plane, task, migration, and cleanup resources")

    database = (DATABASE / "postgres-cluster.yaml").read_text(encoding="utf-8")
    credentials = (DATABASE / "externalsecret.yaml").read_text(encoding="utf-8")
    scheduled_path = DATABASE / "scheduled-backup.yaml"
    database_kustomization = (DATABASE / "kustomization.yaml").read_text(encoding="utf-8")
    if scheduled_path.exists():
        failures.append("Airflow metadata database must not define the unsupported ScheduledBackup")
    if "scheduled-backup.yaml" in database_kustomization:
        failures.append("Airflow metadata database must not register the unsupported ScheduledBackup")
    require(
        failures,
        database + credentials,
        (
            "name: airflow-postgres",
            "instances: 1",
            "storageClass: longhorn",
            "name: airflow-postgres-credentials",
            "key: airflow-postgres/username",
            "key: airflow-postgres/password",
        ),
        "Airflow metadata database",
    )

    backup = "\n".join(path.read_text(encoding="utf-8") for path in sorted(BACKUP.glob("*.yaml")))
    longhorn = LONGHORN_RELEASE.read_text(encoding="utf-8")
    storage_root = STORAGE_ROOT.read_text(encoding="utf-8")
    longhorn_ks = LONGHORN_KS.read_text(encoding="utf-8")
    require(
        failures,
        backup + longhorn + storage_root + longhorn_ks,
        (
            "name: longhorn-backup",
            "driver: driver.longhorn.io",
            "deletionPolicy: Retain",
            "type: bak",
            "backupMode: full",
            "key: seaweedfs-longhorn-backup/access-key",
            "key: seaweedfs-longhorn-backup/secret-key",
            "backupTarget: s3://longhorn-backups@us-east-1/",
            "backupTargetCredentialSecret: longhorn-backup-credentials",
            "./longhorn-backup-config/ks.yaml",
            "name: longhorn-backup-config",
        ),
        "Longhorn backup",
    )

    seaweed = (
        SEAWEED_CRONJOB.read_text(encoding="utf-8")
        + SEAWEED_SECRET.read_text(encoding="utf-8")
        + SEAWEED.read_text(encoding="utf-8")
    )
    require(
        failures,
        seaweed,
        (
            "spark-events longhorn-backups",
            '"name": "longhorn-backup"',
            '"Write:longhorn-backups"',
            'key: "seaweedfs-longhorn-backup/access-key"',
            'key: "seaweedfs-longhorn-backup/secret-key"',
            "secret.reloader.stakater.com/reload: seaweedfs-s3-config",
        ),
        "SeaweedFS backup target",
    )

    for path in (AIRFLOW, DATABASE, RELEASE, BACKUP):
        validate_kustomize(failures, path)

    if failures:
        for failure in failures:
            print(f"[airflow.foundation] {failure}", file=sys.stderr)
        return 1

    print("Airflow Kubernetes foundation contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
