"""Controlled Ticket 06 recovery scenarios at the adapter and trigger seams."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import importlib.util
from typing import Any, Mapping
import unittest
from unittest.mock import patch

from anton_airflow.spark import AttemptIdentity, AttemptState
from anton_airflow.spark.adapter import AttemptObservation, SparkApplicationAdapter
from anton_airflow.spark.lease import LeaseCoordinator, LeaseTakeoverBlocked
from anton_airflow.spark.receipts import LoggingReceiptSink
from anton_airflow.spark.trigger import SparkApplicationTrigger


class NotFound(Exception):
    status = 404


class Conflict(Exception):
    status = 409


class Receipts:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def record(self, receipt: Mapping[str, Any]) -> None:
        self.items.append(dict(receipt))

    def events(self) -> set[str]:
        return {str(item["event"]) for item in self.items}


class Applications:
    def __init__(self) -> None:
        self.resources: dict[str, dict[str, Any]] = {}
        self.created: list[str] = []
        self.deleted: list[str] = []

    def get(self, *, namespace: str, name: str) -> Mapping[str, Any]:
        if name not in self.resources:
            raise NotFound()
        return self.resources[name]

    def create(self, *, namespace: str, body: Mapping[str, Any]) -> Mapping[str, Any]:
        name = str(body["metadata"]["name"])
        if name in self.resources:
            raise Conflict()
        resource = dict(body)
        resource["status"] = {
            "currentState": {"currentStateSummary": "Submitted"},
            "stateTransitionHistory": {
                "1": {"currentStateSummary": "Submitted"},
            },
        }
        self.resources[name] = resource
        self.created.append(name)
        return resource

    def delete(self, *, namespace: str, name: str) -> Any:
        self.resources.pop(name, None)
        self.deleted.append(name)

    def list(self, *, namespace: str, label_selector: str) -> list[Mapping[str, Any]]:
        return list(self.resources.values())

    def watch(self, *, namespace: str, name: str, timeout_seconds: int) -> list[Mapping[str, Any]]:
        return []


class DuplicateDeliveryApplications(Applications):
    def __init__(self) -> None:
        super().__init__()
        self.raced = False

    def create(self, *, namespace: str, body: Mapping[str, Any]) -> Mapping[str, Any]:
        if not self.raced:
            self.raced = True
            super().create(namespace=namespace, body=body)
            raise Conflict()
        return super().create(namespace=namespace, body=body)


class LeaseApi:
    def __init__(self, resource: Mapping[str, Any] | None = None) -> None:
        self.resource = dict(resource) if resource else None
        self.releases = 0

    def get_namespaced_lease(self, name: str, namespace: str) -> Mapping[str, Any]:
        if self.resource is None:
            raise NotFound()
        return self.resource

    def create_namespaced_lease(self, namespace: str, body: Mapping[str, Any]) -> Mapping[str, Any]:
        self.resource = dict(body)
        self.resource["metadata"] = {
            **dict(self.resource.get("metadata") or {}),
            "resourceVersion": "1",
        }
        return self.resource

    def replace_namespaced_lease(self, name: str, namespace: str, body: Mapping[str, Any]) -> Mapping[str, Any]:
        self.resource = dict(body)
        return self.resource

    def delete_namespaced_lease(
        self,
        name: str,
        namespace: str,
        *,
        body: Mapping[str, Any] | None = None,
    ) -> Any:
        self.releases += 1
        self.resource = None


class Pods:
    def __init__(self, *, attempt: str, driver_log: str = "", executor_log: str = "") -> None:
        self.attempt = attempt
        self.logs = {"driver": driver_log, "executor": executor_log}
        self.events = [{"reason": "ExecutorLost", "message": "executor exited before commit"}]

    def list_pods(self, *, namespace: str, label_selector: str) -> list[Mapping[str, Any]]:
        return [
            {
                "metadata": {
                    "name": f"{self.attempt}-{role}",
                    "labels": {"spark-role": role},
                },
                "spec": {"containers": [{"name": role}]},
                "status": {"phase": "Failed"},
            }
            for role in ("driver", "executor")
        ]

    def read_log(self, *, namespace: str, name: str, container: str) -> str:
        return self.logs[container]

    def list_events(self, *, namespace: str, field_selector: str) -> list[Mapping[str, Any]]:
        return self.events


def adapter_for(
    applications: Applications,
    *,
    lease_api: LeaseApi | None = None,
    pods: Pods | None = None,
    receipts: Receipts | None = None,
    diagnostics_limit: int = 2000,
) -> tuple[SparkApplicationAdapter, LeaseApi]:
    lease_api = lease_api or LeaseApi()
    return (
        SparkApplicationAdapter(
            applications=applications,
            leases=LeaseCoordinator(lease_api, "lakehouse", "shadow"),
            pods=pods,
            namespace="lakehouse",
            diagnostics_limit=diagnostics_limit,
            receipts=receipts,
        ),
        lease_api,
    )


class Ticket06RecoveryTests(unittest.TestCase):
    def test_logging_receipt_sink_emits_structured_task_log_record(self) -> None:
        class Logger:
            def __init__(self) -> None:
                self.messages: list[str] = []

            def info(self, template: str, payload: str) -> None:
                self.messages.append(template.replace("%s", payload))

        logger = Logger()
        LoggingReceiptSink(logger).record({"event": "submission", "attempt": "lh-test"})
        self.assertEqual(len(logger.messages), 1)
        self.assertIn('"event": "submission"', logger.messages[0])
        self.assertIn('"receipt_schema": 1', logger.messages[0])

    def test_authoritative_dag_uses_the_authoritative_target(self) -> None:
        dag_path = "/opt/airflow/dags/airflow_spark_lakehouse.py"
        spec = importlib.util.spec_from_file_location("airflow_spark_lakehouse", dag_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        task = module.spark_lakehouse_dag.get_task("run_authoritative_spark_attempt")
        self.assertEqual(task.target, "authoritative")
        self.assertIsNone(task.prior_output_validator)
        driver = task.application_spec["spec"]["driverSpec"]["podTemplateSpec"]["spec"]["containers"][0]
        environment = {item["name"]: item["value"] for item in driver["env"]}
        self.assertEqual(environment["ICEBERG_WAREHOUSE"], "s3://iceberg-warehouse")
        self.assertEqual(driver["envFrom"][0]["secretRef"]["name"], "authoritative-fixture-s3")

    def test_normal_success_records_submission_transitions_and_terminal_state(self) -> None:
        applications = Applications()
        receipts = Receipts()
        adapter, lease_api = adapter_for(applications, receipts=receipts)
        identity = AttemptIdentity("lakehouse", "run-success", "fixture", -1, 1)

        adapter.submit_or_reattach(identity, application_spec={"spec": {}}, target="shadow")
        applications.resources[identity.name]["status"] = {
            "currentState": {"currentStateSummary": "Succeeded"},
            "stateTransitionHistory": {
                "1": {"currentStateSummary": "Submitted"},
                "2": {"currentStateSummary": "Succeeded"},
            },
        }
        result = adapter.wait_for_completion(identity.name, timeout=0.1, interval=0.001)

        self.assertEqual(result.state, AttemptState.SUCCEEDED)
        self.assertEqual(lease_api.releases, 1)
        self.assertTrue({"submission", "state_transition", "terminal_state"} <= receipts.events())

    def test_short_lived_executor_and_precommit_failure_keep_bounded_diagnostics(self) -> None:
        applications = Applications()
        receipts = Receipts()
        identity = AttemptIdentity("lakehouse", "run-failure", "fixture", -1, 1)
        pods = Pods(attempt=identity.name, driver_log="d" * 400 + "\ndriver-tail", executor_log="e" * 400 + "\nexecutor-exit")
        adapter, _ = adapter_for(applications, pods=pods, receipts=receipts, diagnostics_limit=64)
        adapter.submit_or_reattach(identity, application_spec={"spec": {}}, target="shadow")
        applications.resources[identity.name]["status"] = {
            "currentState": {"currentStateSummary": "Failed"},
            "stateTransitionHistory": {
                "1": {"currentStateSummary": "Submitted"},
                "2": {"currentStateSummary": "Failed"},
            },
        }

        result = adapter.submit_or_reattach(identity, application_spec={"spec": {}}, target="shadow")

        self.assertEqual(result.state, AttemptState.FAILED)
        self.assertTrue(any("executor-exit" in item for item in result.diagnostics))
        diagnostic = next(item for item in receipts.items if item["event"] == "failure_diagnostics")
        self.assertLessEqual(len(diagnostic["driver_tails"][0]["tail"]), 64)
        self.assertLessEqual(len(diagnostic["executor_tails"][0]["tail"]), 64)
        self.assertEqual(diagnostic["events"][0]["reason"], "ExecutorLost")

    def test_scheduler_recovery_reattaches_and_duplicate_delivery_creates_one_attempt(self) -> None:
        applications = Applications()
        receipts = Receipts()
        first, lease_api = adapter_for(applications, receipts=receipts)
        identity = AttemptIdentity("lakehouse", "run-recovery", "fixture", -1, 1)
        first.submit_or_reattach(identity, application_spec={"spec": {}}, target="shadow")

        recovered, _ = adapter_for(applications, lease_api=lease_api, receipts=receipts)
        result = recovered.submit_or_reattach(identity, application_spec={"spec": {}}, target="shadow")

        self.assertEqual(result.state, AttemptState.ACTIVE)
        self.assertEqual(applications.created, [identity.name])

        raced_apps = DuplicateDeliveryApplications()
        raced_receipts = Receipts()
        raced, _ = adapter_for(raced_apps, receipts=raced_receipts)
        raced_result = raced.submit_or_reattach(identity, application_spec={"spec": {}}, target="shadow")
        self.assertEqual(raced_result.state, AttemptState.ACTIVE)
        self.assertEqual(raced_apps.created, [identity.name])
        self.assertIn("duplicate_delivery", raced_receipts.events())

    def test_retry_reuses_valid_prior_output_or_creates_a_new_attempt(self) -> None:
        applications = Applications()
        receipts = Receipts()
        adapter, lease_api = adapter_for(applications, receipts=receipts)
        first = AttemptIdentity("lakehouse", "run-retry", "fixture", -1, 1)
        second = AttemptIdentity("lakehouse", "run-retry", "fixture", -1, 2)
        adapter.submit_or_reattach(first, application_spec={"spec": {}}, target="shadow")
        applications.resources[first.name]["status"] = {
            "currentState": {"currentStateSummary": "Succeeded"},
            "stateTransitionHistory": {"1": {"currentStateSummary": "Succeeded"}},
        }
        lease_api.resource = None

        reused = adapter.retry(
            first,
            second,
            application_spec={"spec": {}},
            target="shadow",
            prior_output_valid=lambda resource: True,
        )
        self.assertEqual(reused.name, first.name)
        self.assertEqual(applications.created, [first.name])
        self.assertIn("prior_output_reused", receipts.events())

        third = AttemptIdentity("lakehouse", "run-retry", "fixture", -1, 3)
        fresh = adapter.retry(
            second,
            third,
            application_spec={"spec": {}},
            target="shadow",
            prior_output_valid=lambda resource: False,
        )
        self.assertEqual(fresh.name, third.name)
        self.assertEqual(applications.created, [first.name, third.name])

    def test_cancellation_stops_exact_attempt_before_releasing_lease(self) -> None:
        applications = Applications()
        receipts = Receipts()
        identity = AttemptIdentity("lakehouse", "run-cancel", "fixture", -1, 1)
        pods = Pods(attempt=identity.name, driver_log="driver", executor_log="executor")
        adapter, lease_api = adapter_for(applications, pods=pods, receipts=receipts)
        adapter.submit_or_reattach(identity, application_spec={"spec": {}}, target="shadow")

        diagnostics = adapter.cancel(identity, timeout=0.1)

        self.assertTrue(diagnostics)
        self.assertEqual(applications.deleted, [identity.name])
        self.assertEqual(lease_api.releases, 1)
        self.assertTrue({"cancellation_requested", "cancellation_stopped"} <= receipts.events())

    def test_expired_lease_refuses_takeover_when_prior_application_is_active(self) -> None:
        identity = AttemptIdentity("lakehouse", "run-new", "fixture", -1, 1)
        prior = AttemptIdentity("lakehouse", "run-old", "fixture", -1, 1)
        applications = Applications()
        applications.resources[prior.name] = {
            "metadata": {"name": prior.name},
            "status": {
                "currentState": {"currentStateSummary": "Submitted"},
                "stateTransitionHistory": {"1": {"currentStateSummary": "Submitted"}},
            },
        }
        expired = {
            "metadata": {"resourceVersion": "7"},
            "spec": {
                "holderIdentity": prior.name,
                "renewTime": "2026-08-12T00:00:00+00:00",
                "leaseDurationSeconds": 30,
            },
        }
        lease_api = LeaseApi(expired)
        clock = lambda: datetime(2026, 8, 12, 0, 1, tzinfo=timezone.utc)
        adapter = SparkApplicationAdapter(
            applications=applications,
            leases=LeaseCoordinator(lease_api, "lakehouse", "shadow", clock=clock),
            namespace="lakehouse",
        )

        with self.assertRaises(LeaseTakeoverBlocked):
            adapter.submit_or_reattach(identity, application_spec={"spec": {}}, target="shadow")

    def test_triggerer_recovery_renews_lease_before_terminal_observation(self) -> None:
        class Monitor:
            def __init__(self) -> None:
                self.observations = iter(
                    (
                        AttemptObservation("lh-attempt", AttemptState.ACTIVE),
                        AttemptObservation("lh-attempt", AttemptState.SUCCEEDED),
                    )
                )
                self.calls = 0

            def advance(self) -> AttemptObservation:
                self.calls += 1
                return next(self.observations)

        class TriggerAdapter:
            def __init__(self) -> None:
                self.monitor = Monitor()
                self.monitor_request: tuple[str, float, float] | None = None

            def monitor_attempt(
                self,
                name: str,
                *,
                interval: float,
                startup_timeout: float,
            ) -> Monitor:
                self.monitor_request = (name, interval, startup_timeout)
                return self.monitor

        fake = TriggerAdapter()
        trigger = SparkApplicationTrigger(
            attempt_name="lh-attempt",
            target="shadow",
            namespace="lakehouse",
            poll_interval=0.001,
        )

        async def collect() -> list[Mapping[str, Any]]:
            return [event async for event in trigger.run()]

        with patch("anton_airflow.spark.operator._airflow_adapter", return_value=fake):
            events = asyncio.run(collect())

        self.assertEqual(events[0].payload["state"], "succeeded")
        self.assertEqual(fake.monitor.calls, 2)
        self.assertEqual(fake.monitor_request, ("lh-attempt", 0.001, 60.0))

    def test_triggerer_returns_ambiguous_lifecycle_evidence(self) -> None:
        class Monitor:
            def __init__(self) -> None:
                self.observation = AttemptObservation(
                    "lh-attempt",
                    AttemptState.AMBIGUOUS,
                    diagnostics=("event DriverReadyTimedOut: no driver",),
                )

            def advance(self) -> AttemptObservation:
                return self.observation

        class TriggerAdapter:
            def __init__(self) -> None:
                self.monitor = Monitor()

            def monitor_attempt(self, name: str, **kwargs: Any) -> Monitor:
                return self.monitor

        fake = TriggerAdapter()
        trigger = SparkApplicationTrigger(
            attempt_name="lh-attempt",
            target="shadow",
            namespace="lakehouse",
            poll_interval=0.001,
            startup_timeout=1.0,
        )

        async def collect() -> list[Mapping[str, Any]]:
            return [event async for event in trigger.run()]

        with patch("anton_airflow.spark.operator._airflow_adapter", return_value=fake):
            events = asyncio.run(collect())

        self.assertEqual(events[0].payload["state"], "ambiguous")
        self.assertEqual(
            events[0].payload["diagnostics"],
            ("event DriverReadyTimedOut: no driver",),
        )


if __name__ == "__main__":
    unittest.main()
