"""Tests for the ticket 04 Airflow image package boundary."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from importlib.metadata import version
from pathlib import Path
from unittest.mock import patch

import airflow

from datetime import datetime, timezone

from anton_airflow.spark import (
    PACKAGE_VERSION,
    AttemptIdentity,
    AttemptState,
    build_spark_application,
    classify_application,
    foundation_marker,
    identity_hash,
)
from anton_airflow.spark.adapter import KubernetesSparkApplicationClient, SparkApplicationAdapter
from anton_airflow.spark.lease import LeaseCoordinator, LeaseTakeoverBlocked


class AdapterPackageTests(unittest.TestCase):
    def test_runtime_versions_are_exact(self) -> None:
        self.assertEqual(airflow.__version__, "3.2.2")
        self.assertEqual(sys.version_info[:2], (3, 12))
        self.assertEqual(version("apache-airflow-providers-cncf-kubernetes"), "10.21.0")

    def test_foundation_marker_reports_package_identity(self) -> None:
        marker = foundation_marker(run_id="manual__ticket04", pod_name="worker-1")
        self.assertEqual(marker["adapter_package"], PACKAGE_VERSION)
        self.assertEqual(marker["run_id"], "manual__ticket04")
        self.assertEqual(marker["pod_name"], "worker-1")

    def test_attempt_identity_uses_nul_separated_fields_and_try_number(self) -> None:
        identity = AttemptIdentity("daily.lakehouse", "scheduled__2026-08-12", "write", 0, 2)
        self.assertEqual(
            identity.hash,
            identity_hash(
                dag_id="daily.lakehouse",
                run_id="scheduled__2026-08-12",
                task_id="write",
                map_index=0,
            ),
        )
        self.assertTrue(identity.name.startswith("lh-daily-la-write-"))
        self.assertTrue(identity.name.endswith("-a2"))
        self.assertNotEqual(identity.name, AttemptIdentity("daily.lakehouse", "scheduled__2026-08-12", "write", 0, 3).name)

    def test_application_correlation_is_copied_to_both_pod_templates(self) -> None:
        identity = AttemptIdentity("lakehouse", "run-1", "fixture", -1, 1, "2026-08-12T00:00:00+00:00")
        resource = build_spark_application(
            identity,
            application_spec={
                "spec": {
                    "driverSpec": {
                        "podTemplateSpec": {
                            "spec": {"containers": [{"name": "spark-kubernetes-driver", "env": []}]}
                        }
                    },
                    "executorSpec": {
                        "podTemplateSpec": {
                            "spec": {"containers": [{"name": "spark-kubernetes-executor", "env": []}]}
                        }
                    },
                    "applicationTolerations": {"restartConfig": {"restartPolicy": "OnFailure"}},
                }
            },
            namespace="lakehouse",
            target="shadow",
        )
        self.assertEqual(resource["apiVersion"], "spark.apache.org/v1")
        self.assertEqual(
            resource["spec"]["applicationTolerations"]["restartConfig"]["restartPolicy"],
            "Never",
        )
        for role in ("driver", "executor"):
            role_spec = resource["spec"][f"{role}Spec"]["podTemplateSpec"]
            labels = role_spec["metadata"]["labels"]
            environment = {
                item["name"]: item["value"] for item in role_spec["spec"]["containers"][0]["env"]
            }
            self.assertEqual(labels["anton.io/attempt-name"], identity.name)
            self.assertEqual(environment["ANTON_SPARK_ATTEMPT"], identity.name)
            self.assertEqual(environment["ANTON_AIRFLOW_RUN_ID"], "run-1")

    def test_resource_released_without_terminal_history_is_ambiguous(self) -> None:
        self.assertEqual(
            classify_application(
                {
                    "status": {
                        "currentState": {"currentStateSummary": "ResourceReleased"},
                        "stateTransitionHistory": {},
                    }
                }
            ),
            AttemptState.AMBIGUOUS,
        )
        self.assertEqual(
            classify_application(
                {
                    "status": {
                        "currentState": {"currentStateSummary": "ResourceReleased"},
                        "stateTransitionHistory": {"1": {"currentStateSummary": "Succeeded"}},
                    }
                }
            ),
            AttemptState.SUCCEEDED,
        )

    def test_custom_resource_watch_uses_a_name_filtered_list(self) -> None:
        class Api:
            def list_namespaced_custom_object(self, *args, **kwargs):
                return {"items": []}

        class FakeWatch:
            def __init__(self) -> None:
                self.call = None

            def stream(self, function, *args, **kwargs):
                self.call = (function, args, kwargs)
                return [{"type": "MODIFIED", "object": {"metadata": {"name": "attempt"}}}]

        api = Api()
        fake_watch = FakeWatch()
        client = KubernetesSparkApplicationClient(api)
        with patch("kubernetes.watch.Watch", return_value=fake_watch):
            events = client.watch(namespace="lakehouse", name="attempt", timeout_seconds=30)

        self.assertEqual(len(events), 1)
        self.assertIs(fake_watch.call[0].__self__, api)
        self.assertEqual(fake_watch.call[0].__name__, "list_namespaced_custom_object")
        self.assertEqual(fake_watch.call[2]["field_selector"], "metadata.name=attempt")
        self.assertEqual(fake_watch.call[2]["timeout_seconds"], 30)

    def test_retained_recovery_probe_can_access_the_lease_coordinator(self) -> None:
        coordinator = LeaseCoordinator(
            object(),
            namespace="lakehouse",
            target="shadow",
        )
        adapter = SparkApplicationAdapter(
            applications=object(),
            leases=coordinator,
            namespace="lakehouse",
        )

        self.assertIs(adapter.leases, coordinator)

    def test_lease_takeover_requires_expiry_and_inactive_prior_application(self) -> None:
        class Api:
            def __init__(self):
                self.lease = {
                    "metadata": {"resourceVersion": "7"},
                    "spec": {
                        "holderIdentity": "old-attempt",
                        "renewTime": "2026-08-12T00:00:00+00:00",
                        "leaseDurationSeconds": 30,
                    },
                }

            def get_namespaced_lease(self, name, namespace):
                return self.lease

            def replace_namespaced_lease(self, name, namespace, body):
                self.lease = body
                return body

            def create_namespaced_lease(self, namespace, body):
                self.lease = body
                return body

            def delete_namespaced_lease(self, name, namespace):
                self.lease = {"spec": {}}

        clock = lambda: datetime(2026, 8, 12, 0, 1, tzinfo=timezone.utc)
        coordinator = LeaseCoordinator(Api(), "lakehouse", "shadow", clock=clock)
        with self.assertRaises(LeaseTakeoverBlocked):
            coordinator.acquire("new-attempt", prior_application_active=True)
        result = coordinator.acquire("new-attempt", prior_application_active=False)
        self.assertEqual(result["spec"]["holderIdentity"], "new-attempt")

    def test_same_try_reattaches_and_new_try_creates_a_new_attempt(self) -> None:
        class Api404(Exception):
            status = 404

        class Applications:
            def __init__(self):
                self.resources = {}
                self.created = []

            def get(self, *, namespace, name):
                if name not in self.resources:
                    raise Api404()
                return self.resources[name]

            def create(self, *, namespace, body):
                self.created.append(body["metadata"]["name"])
                self.resources[body["metadata"]["name"]] = {
                    **body,
                    "status": {
                        "currentState": {"currentStateSummary": "Submitted"},
                        "stateTransitionHistory": {"1": {"currentStateSummary": "Submitted"}},
                    },
                }

            def delete(self, *, namespace, name):
                self.resources.pop(name, None)

        class LeaseApi:
            def __init__(self):
                self.resource = None

            def get_namespaced_lease(self, name, namespace):
                if self.resource is None:
                    raise Api404()
                return self.resource

            def create_namespaced_lease(self, namespace, body):
                self.resource = body
                return body

            def replace_namespaced_lease(self, name, namespace, body):
                self.resource = body
                return body

            def delete_namespaced_lease(self, name, namespace):
                self.resource = None

        applications = Applications()
        lease_api = LeaseApi()
        adapter = SparkApplicationAdapter(
            applications=applications,
            leases=LeaseCoordinator(lease_api, "lakehouse", "shadow"),
            namespace="lakehouse",
        )
        first = AttemptIdentity("dag", "run", "task", -1, 1)
        second = AttemptIdentity("dag", "run", "task", -1, 2)
        self.assertEqual(
            adapter.submit_or_reattach(first, application_spec={"spec": {}}, target="shadow").state,
            AttemptState.ACTIVE,
        )
        adapter.submit_or_reattach(first, application_spec={"spec": {}}, target="shadow")
        applications.resources[first.name]["status"] = {
            "currentState": {"currentStateSummary": "Failed"},
            "stateTransitionHistory": {"1": {"currentStateSummary": "Failed"}},
        }
        lease_api.resource = None
        adapter.submit_or_reattach(second, application_spec={"spec": {}}, target="shadow")
        self.assertEqual(applications.created, [first.name, second.name])

    def test_cancellation_releases_lease_only_after_the_exact_resource_stops(self) -> None:
        class Api404(Exception):
            status = 404

        class Applications:
            def __init__(self):
                self.resource = None

            def get(self, *, namespace, name):
                if self.resource is None:
                    raise Api404()
                return self.resource

            def create(self, *, namespace, body):
                self.resource = {
                    **body,
                    "status": {
                        "currentState": {"currentStateSummary": "Submitted"},
                        "stateTransitionHistory": {"1": {"currentStateSummary": "Submitted"}},
                    },
                }

            def delete(self, *, namespace, name):
                self.resource = None

        class LeaseApi:
            def __init__(self):
                self.resource = None
                self.released = False

            def get_namespaced_lease(self, name, namespace):
                if self.resource is None:
                    raise Api404()
                return self.resource

            def create_namespaced_lease(self, namespace, body):
                self.resource = {
                    **body,
                    "metadata": {
                        **body["metadata"],
                        "resourceVersion": "1",
                        "uid": "lease-uid-1",
                    },
                }
                return self.resource

            def replace_namespaced_lease(self, name, namespace, body):
                self.resource = body
                return body

            def delete_namespaced_lease(self, name, namespace, *, body=None):
                self.assert_delete_body = body
                self.released = True
                self.resource = None

        leases = LeaseApi()
        applications = Applications()
        adapter = SparkApplicationAdapter(
            applications=applications,
            leases=LeaseCoordinator(leases, "lakehouse", "shadow"),
            namespace="lakehouse",
        )
        identity = AttemptIdentity("dag", "run", "task", -1, 1)
        adapter.submit_or_reattach(identity, application_spec={"spec": {}}, target="shadow")
        adapter.cancel(identity, timeout=0.1,)
        self.assertTrue(leases.released)
        self.assertEqual(
            leases.assert_delete_body["preconditions"],
            {"resourceVersion": "1", "uid": "lease-uid-1"},
        )

    def test_foundation_dag_is_manual_and_bounded(self) -> None:
        dag_path = Path("/opt/airflow/dags/airflow_kubernetes_foundation.py")
        spec = importlib.util.spec_from_file_location("airflow_kubernetes_foundation", dag_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        foundation_dag = module.foundation_dag
        self.assertEqual(foundation_dag.dag_id, "airflow_kubernetes_foundation")
        self.assertIsNone(foundation_dag.schedule)
        self.assertEqual(foundation_dag.max_active_runs, 1)
        self.assertEqual(foundation_dag.task_ids, ["prove_kubernetes_task_pod"])

    def test_spark_dag_is_hourly_in_utc_and_single_run(self) -> None:
        dag_path = Path("/opt/airflow/dags/airflow_spark_lakehouse.py")
        spec = importlib.util.spec_from_file_location("airflow_spark_lakehouse", dag_path)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        spark_dag = module.spark_lakehouse_dag
        self.assertEqual(str(spark_dag.schedule), "23 * * * *")
        self.assertFalse(spark_dag.catchup)
        self.assertEqual(spark_dag.max_active_runs, 1)
        self.assertEqual(str(spark_dag.timezone), "UTC")


if __name__ == "__main__":
    unittest.main()
