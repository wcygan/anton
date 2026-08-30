"""Behavior tests for the shared Spark Attempt lifecycle seam."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Mapping
import unittest
from unittest.mock import patch

from anton_airflow.spark.adapter import SparkApplicationAdapter
from anton_airflow.spark.lease import LeaseConflict, LeaseCoordinator
from anton_airflow.spark.lifecycle import SparkAttemptLifecycle
from anton_airflow.spark.state import AttemptState
from anton_airflow.spark.trigger import SparkApplicationTrigger


ATTEMPT = "lh-lifecycle-trace-a1"


class TransientWatchError(RuntimeError):
    """One bounded watch ended before the next resource read."""


class NotFound(RuntimeError):
    status = 404


class Conflict(RuntimeError):
    status = 409


class SequenceApplications:
    def __init__(self) -> None:
        self.resources = iter(
            (
                {"metadata": {"name": ATTEMPT}},
                {
                    "metadata": {"name": ATTEMPT},
                    "status": {
                        "currentState": {"currentStateSummary": "Submitted"},
                        "stateTransitionHistory": {
                            "1": {"currentStateSummary": "Submitted"},
                        },
                    },
                },
                {
                    "metadata": {"name": ATTEMPT},
                    "status": {
                        "currentState": {"currentStateSummary": "Succeeded"},
                        "stateTransitionHistory": {
                            "1": {"currentStateSummary": "Submitted"},
                            "2": {"currentStateSummary": "Succeeded"},
                        },
                    },
                },
            )
        )
        self.watch_calls = 0

    def get(self, *, namespace: str, name: str) -> Mapping[str, Any]:
        return next(self.resources)

    def create(self, *, namespace: str, body: Mapping[str, Any]) -> Mapping[str, Any]:
        raise AssertionError("the lifecycle trace does not submit resources")

    def list(self, *, namespace: str, label_selector: str) -> list[Mapping[str, Any]]:
        return []

    def delete(self, *, namespace: str, name: str) -> Any:
        raise AssertionError("the lifecycle trace does not cancel resources")

    def watch(self, *, namespace: str, name: str, timeout_seconds: int) -> list[Mapping[str, Any]]:
        self.watch_calls += 1
        if self.watch_calls == 1:
            raise TransientWatchError("the bounded watch disconnected")
        return []


class LeaseApi:
    def __init__(self) -> None:
        self.resource: Mapping[str, Any] | None = {
            "metadata": {"resourceVersion": "1"},
            "spec": {
                "holderIdentity": ATTEMPT,
                "leaseDurationSeconds": 60,
                "renewTime": "2026-08-29T12:00:00+00:00",
            },
        }
        self.renewals = 0
        self.releases = 0

    def get_namespaced_lease(self, name: str, namespace: str) -> Mapping[str, Any]:
        if self.resource is None:
            raise AssertionError("the lifecycle released the Lease more than once")
        return self.resource

    def create_namespaced_lease(self, namespace: str, body: Mapping[str, Any]) -> Mapping[str, Any]:
        raise AssertionError("the lifecycle trace already owns its Lease")

    def replace_namespaced_lease(
        self,
        name: str,
        namespace: str,
        body: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self.renewals += 1
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


class Receipts:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def record(self, receipt: Mapping[str, Any]) -> None:
        self.items.append(dict(receipt))


def lifecycle_adapter(receipts: Any) -> tuple[SparkApplicationAdapter, LeaseApi]:
    lease_api = LeaseApi()
    adapter = SparkApplicationAdapter(
        applications=SequenceApplications(),
        leases=LeaseCoordinator(
            lease_api,
            namespace="lakehouse",
            target="authoritative",
            clock=lambda: datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc),
        ),
        namespace="lakehouse",
        receipts=receipts,
    )
    return adapter, lease_api


def lifecycle_events(receipts: list[Mapping[str, Any]]) -> list[str]:
    selected = {
        "status_pending",
        "watch_fallback",
        "lease_renewed",
        "terminal_state",
        "lease_released",
    }
    return [str(receipt["event"]) for receipt in receipts if receipt.get("event") in selected]


class SparkAttemptLifecycleTests(unittest.TestCase):
    def test_empty_operator_status_is_an_active_attempt_during_startup(self) -> None:
        class EmptyStatusApplications(SequenceApplications):
            def get(self, *, namespace: str, name: str) -> Mapping[str, Any]:
                return {"metadata": {"name": ATTEMPT}, "status": {}}

        adapter = SparkApplicationAdapter(
            applications=EmptyStatusApplications(),
            leases=LeaseCoordinator(
                LeaseApi(),
                namespace="lakehouse",
                target="authoritative",
            ),
            namespace="lakehouse",
        )

        observation = adapter.observe(ATTEMPT)

        self.assertEqual(observation.state.value, "active")
        self.assertTrue(observation.status_pending)

    def test_terminal_replay_completes_after_the_lease_was_released(self) -> None:
        class SucceededApplications(SequenceApplications):
            def get(self, *, namespace: str, name: str) -> Mapping[str, Any]:
                return {
                    "metadata": {"name": ATTEMPT},
                    "status": {
                        "currentState": {"currentStateSummary": "Succeeded"},
                        "stateTransitionHistory": {
                            "1": {"currentStateSummary": "Succeeded"},
                        },
                    },
                }

        class MissingLeaseApi:
            def get_namespaced_lease(self, name: str, namespace: str) -> Mapping[str, Any]:
                raise NotFound()

            def create_namespaced_lease(
                self,
                namespace: str,
                body: Mapping[str, Any],
            ) -> Mapping[str, Any]:
                raise AssertionError("terminal recovery does not create a Lease")

            def replace_namespaced_lease(
                self,
                name: str,
                namespace: str,
                body: Mapping[str, Any],
            ) -> Mapping[str, Any]:
                raise AssertionError("terminal recovery does not renew a Lease")

            def delete_namespaced_lease(
                self,
                name: str,
                namespace: str,
                *,
                body: Mapping[str, Any] | None = None,
            ) -> Any:
                raise AssertionError("the Lease is already absent")

        receipts = Receipts()
        adapter = SparkApplicationAdapter(
            applications=SucceededApplications(),
            leases=LeaseCoordinator(
                MissingLeaseApi(),
                namespace="lakehouse",
                target="authoritative",
            ),
            namespace="lakehouse",
            receipts=receipts,
        )

        result = adapter.wait_for_completion(ATTEMPT, timeout=1.0, interval=0.001)

        release = next(
            receipt
            for receipt in receipts.items
            if receipt.get("event") == "lease_released"
        )
        self.assertEqual(result.state.value, "succeeded")
        self.assertTrue(release["already_absent"])

    def test_terminal_release_tolerates_a_lease_that_disappears_after_its_holder_check(self) -> None:
        class SucceededApplications(SequenceApplications):
            def get(self, *, namespace: str, name: str) -> Mapping[str, Any]:
                return {
                    "metadata": {"name": ATTEMPT},
                    "status": {
                        "currentState": {"currentStateSummary": "Succeeded"},
                        "stateTransitionHistory": {
                            "1": {"currentStateSummary": "Succeeded"},
                        },
                    },
                }

        class VanishingLeaseApi:
            def __init__(self) -> None:
                self.get_calls = 0
                self.delete_calls = 0

            def get_namespaced_lease(self, name: str, namespace: str) -> Mapping[str, Any]:
                self.get_calls += 1
                if self.get_calls > 1:
                    raise NotFound()
                return {
                    "metadata": {"resourceVersion": "1"},
                    "spec": {"holderIdentity": ATTEMPT},
                }

            def create_namespaced_lease(
                self,
                namespace: str,
                body: Mapping[str, Any],
            ) -> Mapping[str, Any]:
                raise AssertionError("terminal recovery does not create a Lease")

            def replace_namespaced_lease(
                self,
                name: str,
                namespace: str,
                body: Mapping[str, Any],
            ) -> Mapping[str, Any]:
                raise AssertionError("terminal recovery does not renew a Lease")

            def delete_namespaced_lease(
                self,
                name: str,
                namespace: str,
                *,
                body: Mapping[str, Any] | None = None,
            ) -> Any:
                self.delete_calls += 1
                raise NotFound()

        receipts = Receipts()
        lease_api = VanishingLeaseApi()
        adapter = SparkApplicationAdapter(
            applications=SucceededApplications(),
            leases=LeaseCoordinator(
                lease_api,
                namespace="lakehouse",
                target="authoritative",
            ),
            namespace="lakehouse",
            receipts=receipts,
        )

        result = adapter.wait_for_completion(ATTEMPT, timeout=1.0, interval=0.001)

        release = next(
            receipt
            for receipt in receipts.items
            if receipt.get("event") == "lease_released"
        )
        self.assertEqual(result.state.value, "succeeded")
        self.assertEqual(lease_api.get_calls, 1)
        self.assertEqual(lease_api.delete_calls, 1)
        self.assertTrue(release["already_absent"])

    def test_terminal_release_fails_closed_for_a_conflicting_holder(self) -> None:
        lease_api = LeaseApi()
        lease_api.resource = {
            "metadata": {"resourceVersion": "2"},
            "spec": {"holderIdentity": "lh-other-attempt-a1"},
        }
        lifecycle = SparkAttemptLifecycle(
            applications=SequenceApplications(),
            leases=LeaseCoordinator(
                lease_api,
                namespace="lakehouse",
                target="authoritative",
            ),
            namespace="lakehouse",
        )

        with self.assertRaises(LeaseConflict):
            lifecycle.release(ATTEMPT, state=AttemptState.SUCCEEDED)

        self.assertEqual(lease_api.releases, 0)

    def test_terminal_release_does_not_delete_a_replacement_holder(self) -> None:
        class ReplacedLeaseApi:
            def __init__(self) -> None:
                self.resource: Mapping[str, Any] = {
                    "metadata": {"resourceVersion": "1"},
                    "spec": {"holderIdentity": ATTEMPT},
                }
                self.delete_calls = 0

            def get_namespaced_lease(self, name: str, namespace: str) -> Mapping[str, Any]:
                return self.resource

            def create_namespaced_lease(
                self,
                namespace: str,
                body: Mapping[str, Any],
            ) -> Mapping[str, Any]:
                raise AssertionError("terminal recovery does not create a Lease")

            def replace_namespaced_lease(
                self,
                name: str,
                namespace: str,
                body: Mapping[str, Any],
            ) -> Mapping[str, Any]:
                raise AssertionError("terminal recovery does not renew a Lease")

            def delete_namespaced_lease(
                self,
                name: str,
                namespace: str,
                *,
                body: Mapping[str, Any] | None = None,
            ) -> Any:
                self.delete_calls += 1
                self.resource = {
                    "metadata": {"resourceVersion": "2"},
                    "spec": {"holderIdentity": "lh-replacement-attempt-a1"},
                }
                expected = (body or {}).get("preconditions", {}).get("resourceVersion")
                if expected != "2" and body is not None:
                    raise Conflict()
                self.resource = {}
                return None

        lease_api = ReplacedLeaseApi()
        lifecycle = SparkAttemptLifecycle(
            applications=SequenceApplications(),
            leases=LeaseCoordinator(
                lease_api,
                namespace="lakehouse",
                target="authoritative",
            ),
            namespace="lakehouse",
        )

        with self.assertRaises(LeaseConflict):
            lifecycle.release(ATTEMPT, state=AttemptState.SUCCEEDED)

        self.assertEqual(lease_api.delete_calls, 1)
        self.assertEqual(
            lease_api.resource["spec"]["holderIdentity"],
            "lh-replacement-attempt-a1",
        )

    def test_watch_disconnect_causes_an_immediate_resource_reread(self) -> None:
        class ActiveApplications(SequenceApplications):
            def __init__(self) -> None:
                super().__init__()
                self.get_calls = 0

            def get(self, *, namespace: str, name: str) -> Mapping[str, Any]:
                self.get_calls += 1
                return {
                    "metadata": {"name": ATTEMPT},
                    "status": {
                        "currentState": {"currentStateSummary": "Submitted"},
                        "stateTransitionHistory": {
                            "1": {"currentStateSummary": "Submitted"},
                        },
                    },
                }

            def watch(
                self,
                *,
                namespace: str,
                name: str,
                timeout_seconds: int,
            ) -> list[Mapping[str, Any]]:
                raise TransientWatchError("the bounded watch disconnected")

        sleeps: list[float] = []
        applications = ActiveApplications()
        lifecycle = SparkAttemptLifecycle(
            applications=applications,
            leases=LeaseCoordinator(
                LeaseApi(),
                namespace="lakehouse",
                target="authoritative",
            ),
            namespace="lakehouse",
            sleeper=sleeps.append,
        )

        monitor = lifecycle.monitor(
            ATTEMPT,
            interval=10.0,
        )

        observation = monitor.advance()
        monitor.advance()

        self.assertEqual(observation.state.value, "active")
        self.assertEqual(sleeps, [])
        self.assertEqual(applications.get_calls, 2)

    def test_diagnostic_source_errors_do_not_mask_a_failed_terminal_state(self) -> None:
        class FailedApplications(SequenceApplications):
            def get(self, *, namespace: str, name: str) -> Mapping[str, Any]:
                return {
                    "metadata": {"name": ATTEMPT},
                    "status": {
                        "currentState": {"currentStateSummary": "Failed"},
                        "stateTransitionHistory": {
                            "1": {"currentStateSummary": "Failed"},
                        },
                    },
                }

        class BrokenDiagnostics:
            def list_pods(
                self,
                *,
                namespace: str,
                label_selector: str,
            ) -> list[Mapping[str, Any]]:
                raise PermissionError("pod list denied")

            def read_log(self, *, namespace: str, name: str, container: str) -> str:
                raise AssertionError("no pod list means no log read")

            def list_events(
                self,
                *,
                namespace: str,
                field_selector: str,
            ) -> list[Mapping[str, Any]]:
                raise TimeoutError("event list timed out")

        receipts = Receipts()
        lease_api = LeaseApi()
        adapter = SparkApplicationAdapter(
            applications=FailedApplications(),
            leases=LeaseCoordinator(
                lease_api,
                namespace="lakehouse",
                target="authoritative",
            ),
            pods=BrokenDiagnostics(),
            namespace="lakehouse",
            receipts=receipts,
        )

        result = adapter.wait_for_completion(ATTEMPT, timeout=1.0, interval=0.001)

        self.assertEqual(result.state.value, "failed")
        self.assertEqual(lease_api.releases, 1)
        self.assertIn("pod diagnostics unavailable: PermissionError", result.diagnostics)
        self.assertIn("event diagnostics unavailable: TimeoutError", result.diagnostics)
        self.assertEqual(
            lifecycle_events(receipts.items)[-2:],
            ["terminal_state", "lease_released"],
        )

    def test_synchronous_and_deferred_waits_publish_the_same_lifecycle_trace(self) -> None:
        sync_receipts = Receipts()
        sync_adapter, sync_lease = lifecycle_adapter(sync_receipts)

        sync_result = sync_adapter.wait_for_completion(
            ATTEMPT,
            timeout=1.0,
            interval=0.001,
        )

        deferred_lease: LeaseApi | None = None

        def adapter_factory(**kwargs: Any) -> SparkApplicationAdapter:
            nonlocal deferred_lease
            adapter, deferred_lease = lifecycle_adapter(kwargs["receipt_sink"])
            return adapter

        trigger = SparkApplicationTrigger(
            attempt_name=ATTEMPT,
            target="authoritative",
            namespace="lakehouse",
            poll_interval=0.001,
            startup_timeout=1.0,
        )

        async def collect() -> list[Any]:
            return [event async for event in trigger.run()]

        with patch("anton_airflow.spark.operator._airflow_adapter", side_effect=adapter_factory):
            trigger_events = asyncio.run(collect())

        expected_trace = [
            "status_pending",
            "watch_fallback",
            "lease_renewed",
            "terminal_state",
            "lease_released",
        ]
        self.assertEqual(sync_result.state.value, "succeeded")
        self.assertEqual(trigger_events[0].payload["state"], "succeeded")
        self.assertEqual(lifecycle_events(sync_receipts.items), expected_trace)
        self.assertEqual(lifecycle_events(trigger_events[0].payload["receipts"]), expected_trace)
        self.assertEqual(sync_lease.renewals, 2)
        self.assertEqual(sync_lease.releases, 1)
        self.assertIsNotNone(deferred_lease)
        self.assertEqual(deferred_lease.renewals, 2)
        self.assertEqual(deferred_lease.releases, 1)


if __name__ == "__main__":
    unittest.main()
