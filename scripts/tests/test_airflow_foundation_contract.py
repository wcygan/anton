"""Tests for the ticket 04 Airflow foundation contract."""

from __future__ import annotations

import copy
import json
from unittest.mock import patch

from scripts.lib import airflow_foundation_contract as contract

import subprocess
import tempfile
import unittest
from pathlib import Path
from shutil import copy2


REPO = Path(__file__).resolve().parents[2]


class SparkRbacContractTests(unittest.TestCase):
    def setUp(self):
        self.documents = json.loads(subprocess.check_output(
            ["yq", "eval-all", "-o=json", "[.]", str(contract.AIRFLOW_SPARK_RBAC)], text=True
        ))

    def validate(self, documents):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rbac.yaml"
            path.write_text("\n---\n".join(json.dumps(document) for document in documents))
            failures = []
            with patch.object(contract, "AIRFLOW_SPARK_RBAC", path):
                contract.validate_spark_rbac(failures)
            return failures

    def test_accepts_current_permissions(self):
        self.assertEqual(self.validate(self.documents), [])

    def test_rejects_additive_permissions_in_either_order(self):
        for index in (0, len(self.documents[0]["rules"])):
            with self.subTest(index=index):
                documents = copy.deepcopy(self.documents)
                documents[0]["rules"].insert(index, {"apiGroups": [""], "resources": ["pods"], "verbs": ["create"]})
                self.assertTrue(self.validate(documents))

    def test_rejects_multi_group_permissions(self):
        self.documents[0]["rules"].append({"apiGroups": ["", "apps"], "resources": ["pods"], "verbs": ["create"]})
        self.assertTrue(self.validate(self.documents))

    def test_rejects_additional_documents(self):
        for kind in ("Role", "RoleBinding", "ClusterRoleBinding"):
            with self.subTest(kind=kind):
                self.assertTrue(self.validate(self.documents + [{"kind": kind}]))

    def test_rejects_wrong_binding_target(self):
        self.documents[1]["roleRef"] = {"apiGroup": "rbac.authorization.k8s.io", "kind": "ClusterRole", "name": "cluster-admin"}
        self.assertTrue(self.validate(self.documents))

    def test_rejects_wrong_namespace(self):
        self.documents[0]["metadata"]["namespace"] = "other"
        self.assertTrue(self.validate(self.documents))


class AirflowFoundationContractTests(unittest.TestCase):
    def test_repository_contract_passes(self) -> None:
        result = subprocess.run(
            ["python3", "scripts/validate-airflow-foundation-contract.py"],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Airflow Kubernetes foundation contract: PASS", result.stdout)

    def test_rejects_scheduler_replica_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            candidate = Path(temporary_directory) / "helmrelease.yaml"
            copy2(
                REPO / "kubernetes/apps/airflow/airflow/app/helmrelease.yaml",
                candidate,
            )
            mutation = subprocess.run(
                ["yq", "-i", ".spec.values.scheduler.replicas = 2", str(candidate)],
                cwd=REPO,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(mutation.returncode, 0, mutation.stderr)

            result = subprocess.run(
                [
                    "python3",
                    "scripts/validate-airflow-foundation-contract.py",
                    "--release",
                    str(candidate),
                ],
                cwd=REPO,
                capture_output=True,
                text=True,
                timeout=30,
            )

        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("scheduler replicas", result.stderr)

    def test_rejects_flux_migration_hook_deadlock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            candidate = Path(temporary_directory) / "helmrelease.yaml"
            copy2(
                REPO / "kubernetes/apps/airflow/airflow/app/helmrelease.yaml",
                candidate,
            )
            mutation = subprocess.run(
                [
                    "yq",
                    "-i",
                    ".spec.values.migrateDatabaseJob.useHelmHooks = true",
                    str(candidate),
                ],
                cwd=REPO,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(mutation.returncode, 0, mutation.stderr)

            result = subprocess.run(
                [
                    "python3",
                    "scripts/validate-airflow-foundation-contract.py",
                    "--release",
                    str(candidate),
                ],
                cwd=REPO,
                capture_output=True,
                text=True,
                timeout=30,
            )

        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("migration Job hooks", result.stderr)

    def test_rejects_disabled_migration_job(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            candidate = Path(temporary_directory) / "helmrelease.yaml"
            copy2(
                REPO / "kubernetes/apps/airflow/airflow/app/helmrelease.yaml",
                candidate,
            )
            mutation = subprocess.run(
                [
                    "yq",
                    "-i",
                    ".spec.values.migrateDatabaseJob.enabled = false",
                    str(candidate),
                ],
                cwd=REPO,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(mutation.returncode, 0, mutation.stderr)

            result = subprocess.run(
                [
                    "python3",
                    "scripts/validate-airflow-foundation-contract.py",
                    "--release",
                    str(candidate),
                ],
                cwd=REPO,
                capture_output=True,
                text=True,
                timeout=30,
            )

        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("migration Job enabled", result.stderr)

    def test_rejects_api_server_resource_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            candidate = Path(temporary_directory) / "helmrelease.yaml"
            copy2(
                REPO / "kubernetes/apps/airflow/airflow/app/helmrelease.yaml",
                candidate,
            )
            mutation = subprocess.run(
                [
                    "yq",
                    "-i",
                    ".spec.values.apiServer.resources.limits.memory = \"2Gi\"",
                    str(candidate),
                ],
                cwd=REPO,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(mutation.returncode, 0, mutation.stderr)

            result = subprocess.run(
                [
                    "python3",
                    "scripts/validate-airflow-foundation-contract.py",
                    "--release",
                    str(candidate),
                ],
                cwd=REPO,
                capture_output=True,
                text=True,
                timeout=30,
            )

        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("apiServer resources", result.stderr)

    def test_rejects_task_pod_api_token_mount(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            candidate = Path(temporary_directory) / "helmrelease.yaml"
            copy2(
                REPO / "kubernetes/apps/airflow/airflow/app/helmrelease.yaml",
                candidate,
            )
            mutation = subprocess.run(
                [
                    "yq",
                    "-i",
                    ".spec.values.workers.kubernetes.serviceAccount.automountServiceAccountToken = false",
                    str(candidate),
                ],
                cwd=REPO,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(mutation.returncode, 0, mutation.stderr)

            result = subprocess.run(
                [
                    "python3",
                    "scripts/validate-airflow-foundation-contract.py",
                    "--release",
                    str(candidate),
                ],
                cwd=REPO,
                capture_output=True,
                text=True,
                timeout=30,
            )

        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("task service account", result.stderr)

    def test_rejects_external_secret_field_fan_out(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            candidate = Path(temporary_directory) / "externalsecret.yaml"
            copy2(
                REPO
                / "kubernetes/apps/airflow/airflow-database/app/externalsecret.yaml",
                candidate,
            )
            mutation = subprocess.run(
                [
                    "yq",
                    "-i",
                    ".spec.dataFrom[0].extract.key = \"wrong-item\"",
                    str(candidate),
                ],
                cwd=REPO,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(mutation.returncode, 0, mutation.stderr)

            result = subprocess.run(
                [
                    "python3",
                    "scripts/validate-airflow-foundation-contract.py",
                    "--credentials",
                    str(candidate),
                ],
                cwd=REPO,
                capture_output=True,
                text=True,
                timeout=30,
            )

        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("ExternalSecret extraction", result.stderr)

    def test_rejects_same_domain_longhorn_backup_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            candidate = Path(temporary_directory) / "helmrelease.yaml"
            copy2(
                REPO / "kubernetes/apps/storage/longhorn/app/helmrelease.yaml",
                candidate,
            )
            mutation = subprocess.run(
                [
                    "yq",
                    "-i",
                    '.spec.values.defaultBackupStore.backupTarget = "s3://longhorn-backups@us-east-1/"',
                    str(candidate),
                ],
                cwd=REPO,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(mutation.returncode, 0, mutation.stderr)

            result = subprocess.run(
                [
                    "python3",
                    "scripts/validate-airflow-foundation-contract.py",
                    "--longhorn-release",
                    str(candidate),
                ],
                cwd=REPO,
                capture_output=True,
                text=True,
                timeout=30,
            )

        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("defaultBackupStore", result.stderr)


if __name__ == "__main__":
    unittest.main()
