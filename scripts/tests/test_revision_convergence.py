"""Tests for the read-only Flux revision convergence observer."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "scripts" / "lib"))

from evaluate_revision_convergence import main, read_cluster_snapshot  # noqa: E402
from cluster_target_contract import TargetPreflightError  # noqa: E402
from revision_convergence import (  # noqa: E402
    DEFAULT_CRITICAL_KUSTOMIZATIONS,
    CriticalKustomization,
    ObservationError,
    aggregate_revision_records,
    evaluate_revision_convergence,
    format_utc_timestamp,
    new_revision_record,
    parse_utc_timestamp,
    update_revision_record,
)


FIXTURE = REPO / "scripts" / "tests" / "fixtures" / "revision-convergence-v1.json"
LIVE_EVIDENCE = (
    REPO
    / "context"
    / "notes"
    / "cluster-metric-evidence"
    / "2026-08-11T011440Z-m2.json"
)
CURRENT_REVISION = "refs/heads/main@sha1:50f056942b78cfaa16052ff781630cfcde4d793a"
STALE_REVISION = "refs/heads/main@sha1:fc3f7940ea9d0f7d6d11e6f386431a6b895ca8d8"


def lifecycle_observation(index: int, duration_seconds: int, *, complete: bool) -> dict[str, Any]:
    revision = f"refs/heads/main@sha1:{index:040x}"
    start = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=index)
    observed = start + timedelta(seconds=duration_seconds)
    evidence = [
        {
            "classification": "current_ready",
            "name": item.name,
            "namespace": item.namespace,
        }
        for item in DEFAULT_CRITICAL_KUSTOMIZATIONS
    ]
    if not complete:
        evidence[-1]["classification"] = "current_failed"
    return {
        "complete": complete,
        "critical_kustomizations": evidence,
        "incomplete_count": 0 if complete else 1,
        "observed_at": format_utc_timestamp(observed),
        "schema_version": 1,
        "source": {
            "artifact_last_update_time": format_utc_timestamp(start),
            "kind": "GitRepository",
            "name": "flux-system",
            "namespace": "flux-system",
            "revision": revision,
        },
    }


def completed_lifecycle_record(index: int, duration_seconds: int) -> dict[str, Any]:
    """Create a complete record only through the required incomplete start."""

    record = new_revision_record(lifecycle_observation(index, 0, complete=False))
    return update_revision_record(record, lifecycle_observation(index, duration_seconds, complete=True))


def kustomization(
    namespace: str,
    name: str,
    *,
    ready: str,
    applied: str = CURRENT_REVISION,
    attempted: str = CURRENT_REVISION,
    generation: int = 1,
    observed_generation: int | None = None,
    condition_generation: int | None = None,
    source_namespace: str | None = None,
    source_name: str = "flux-system",
) -> dict[str, Any]:
    source_ref: dict[str, Any] = {"kind": "GitRepository", "name": source_name}
    if source_namespace is not None:
        source_ref["namespace"] = source_namespace
    return {
        "metadata": {"generation": generation, "name": name, "namespace": namespace},
        "spec": {"sourceRef": source_ref},
        "status": {
            "conditions": [
                {
                    "observedGeneration": generation if condition_generation is None else condition_generation,
                    "reason": "fixture",
                    "status": ready,
                    "type": "Ready",
                }
            ],
            "lastAppliedRevision": applied,
            "lastAttemptedRevision": attempted,
            "observedGeneration": generation if observed_generation is None else observed_generation,
        },
    }


class RevisionConvergenceTests(unittest.TestCase):
    @staticmethod
    def fixture() -> dict[str, Any]:
        return json.loads(FIXTURE.read_text(encoding="utf-8"))

    def evaluate_fixture(self) -> tuple[dict[str, Any], dict[str, Any]]:
        fixture = self.fixture()
        critical = tuple(CriticalKustomization(*value.split("/", 1)) for value in fixture["critical"])
        return (
            evaluate_revision_convergence(
                fixture["source"],
                fixture["kustomizations"],
                critical=critical,
                observed_at=parse_utc_timestamp(fixture["now"]),
            ),
            fixture,
        )

    def test_fixed_corpus_classifies_all_states(self) -> None:
        result, fixture = self.evaluate_fixture()
        classifications = {
            f"{item['namespace']}/{item['name']}": item["classification"]
            for item in result["critical_kustomizations"]
        }
        self.assertEqual(classifications, fixture["expected"]["classifications"])
        self.assertEqual(result["age_seconds"], fixture["expected"]["age_seconds"])
        self.assertEqual(result["incomplete_count"], fixture["expected"]["incomplete_count"])
        self.assertFalse(result["complete"])
        self.assertNotIn("convergence_time_seconds", result)
        self.assertEqual(result["source"]["revision"], CURRENT_REVISION)

    def test_default_inventory_is_the_explicit_critical_scope(self) -> None:
        self.assertEqual(
            [item.identifier for item in DEFAULT_CRITICAL_KUSTOMIZATIONS],
            [
                "flux-system/flux-system",
                "flux-system/cluster-apps",
                "flux-system/flux-operator",
                "flux-system/flux-instance",
                "kube-system/cilium",
                "kube-system/coredns",
                "external-secrets/external-secrets",
                "external-secrets/onepassword-store",
                "network/envoy-gateway",
                "network/cloudflare-dns",
                "network/cloudflare-tunnel",
                "network/k8s-gateway",
                "storage/longhorn-config",
                "storage/longhorn",
                "storage/seaweedfs",
                "storage/seaweedfs-config",
                "observability/kube-prometheus-stack",
                "observability/ntfy",
            ],
        )

    def test_fixture_critical_scope_matches_default_inventory(self) -> None:
        fixture = self.fixture()
        self.assertEqual(
            fixture["critical"],
            [item.identifier for item in DEFAULT_CRITICAL_KUSTOMIZATIONS],
        )

    def test_retained_live_evidence_uses_the_fixed_scope(self) -> None:
        evidence = json.loads(LIVE_EVIDENCE.read_text(encoding="utf-8"))
        self.assertEqual(evidence["target_preflight"], "passed")
        self.assertEqual(
            [f"{item['namespace']}/{item['name']}" for item in evidence["critical_kustomizations"]],
            [item.identifier for item in DEFAULT_CRITICAL_KUSTOMIZATIONS],
        )
        incomplete = sum(
            item["classification"] != "current_ready"
            for item in evidence["critical_kustomizations"]
        )
        self.assertEqual(evidence["incomplete_count"], incomplete)
        self.assertEqual(evidence["complete"], incomplete == 0)
        self.assertRegex(evidence["source"]["revision"], r"@sha1:[0-9a-f]{40}$")
        self.assertNotIn("message", LIVE_EVIDENCE.read_text(encoding="utf-8").lower())

    def test_retained_live_evidence_starts_one_incomplete_record(self) -> None:
        evidence = json.loads(LIVE_EVIDENCE.read_text(encoding="utf-8"))
        record = new_revision_record(evidence)
        self.assertEqual(record["status"], "incomplete")
        self.assertIsNone(record["duration_seconds"])
        self.assertIsNone(record["stop_event_time"])

    def test_revision_record_advances_from_incomplete_to_complete(self) -> None:
        initial = lifecycle_observation(1, 1, complete=False)
        record = new_revision_record(initial)
        initial_evidence = [dict(item) for item in record["initial_critical_kustomizations"]]
        completed = update_revision_record(record, lifecycle_observation(1, 10, complete=True))
        self.assertEqual(completed["status"], "complete")
        self.assertEqual(completed["duration_seconds"], 10)
        self.assertEqual(completed["stop_event_time"], completed["last_observed_at"])
        self.assertEqual(completed["initial_critical_kustomizations"], initial_evidence)
        self.assertEqual(record["initial_critical_kustomizations"], initial_evidence)
        self.assertEqual(completed["initial_incomplete_count"], record["initial_incomplete_count"])

    def test_revision_record_rejects_a_complete_initial_observation(self) -> None:
        with self.assertRaisesRegex(ObservationError, "must start incomplete"):
            new_revision_record(lifecycle_observation(1, 1, complete=True))

    def test_revision_record_rejects_revision_changes_and_short_revisions(self) -> None:
        record = new_revision_record(lifecycle_observation(1, 1, complete=False))
        with self.assertRaisesRegex(ObservationError, "source identities differ"):
            update_revision_record(record, lifecycle_observation(2, 10, complete=True))

        shortened = lifecycle_observation(1, 1, complete=False)
        shortened["source"]["revision"] = "refs/heads/main@sha1:00000001"
        with self.assertRaisesRegex(ObservationError, "full SHA-1"):
            new_revision_record(shortened)

    def test_revision_record_pins_the_metric_source(self) -> None:
        for field, value in (
            ("kind", "Bucket"),
            ("namespace", "other"),
            ("name", "other"),
        ):
            with self.subTest(field=field):
                observation = lifecycle_observation(1, 1, complete=False)
                observation["source"][field] = value
                with self.assertRaisesRegex(ObservationError, "GitRepository flux-system/flux-system"):
                    new_revision_record(observation)

    def test_revision_record_requires_time_progress_and_fixed_scope(self) -> None:
        initial = lifecycle_observation(1, 1, complete=False)
        record = new_revision_record(initial)
        with self.assertRaisesRegex(ObservationError, "advance in time"):
            update_revision_record(record, initial)

        wrong_scope = lifecycle_observation(1, 2, complete=False)
        wrong_scope["critical_kustomizations"].pop()
        with self.assertRaisesRegex(ObservationError, "fixed critical scope"):
            update_revision_record(record, wrong_scope)

    def test_complete_revision_record_is_immutable(self) -> None:
        record = completed_lifecycle_record(1, 1)
        with self.assertRaisesRegex(ObservationError, "immutable"):
            update_revision_record(record, lifecycle_observation(1, 2, complete=True))

    def test_rolling_thirty_uses_nearest_rank_quantiles(self) -> None:
        records = [
            completed_lifecycle_record(index, index)
            for index in range(1, 31)
        ]
        aggregate = aggregate_revision_records(records)
        self.assertTrue(aggregate["eligible"])
        self.assertEqual(aggregate["complete_count"], 30)
        self.assertEqual(aggregate["incomplete_count"], 0)
        self.assertEqual(aggregate["p50_seconds"], 15)
        self.assertEqual(aggregate["p95_seconds"], 29)
        self.assertEqual(aggregate["maximum_seconds"], 30)

    def test_rolling_window_keeps_incomplete_records_out_of_quantiles(self) -> None:
        records = [
            (
                completed_lifecycle_record(index, index)
                if index != 30
                else new_revision_record(lifecycle_observation(index, 0, complete=False))
            )
            for index in range(1, 31)
        ]
        aggregate = aggregate_revision_records(records)
        self.assertFalse(aggregate["eligible"])
        self.assertEqual(aggregate["complete_count"], 29)
        self.assertEqual(aggregate["incomplete_count"], 1)
        self.assertIsNone(aggregate["p50_seconds"])
        self.assertIsNone(aggregate["p95_seconds"])
        self.assertIsNone(aggregate["maximum_seconds"])

    def test_rolling_window_rejects_duplicate_revisions(self) -> None:
        record = completed_lifecycle_record(1, 1)
        with self.assertRaisesRegex(ObservationError, "duplicate revisions"):
            aggregate_revision_records([record, record])

    def test_rolling_window_rejects_a_window_size_override_and_tied_starts(self) -> None:
        record = completed_lifecycle_record(1, 1)
        with self.assertRaises(TypeError):
            aggregate_revision_records([record], window_size=1)  # type: ignore[call-arg]

        tied = completed_lifecycle_record(2, 2)
        tied_start = parse_utc_timestamp(str(record["start_event_time"]))
        tied_stop = format_utc_timestamp(tied_start + timedelta(seconds=2))
        tied["source"]["artifact_last_update_time"] = record["source"]["artifact_last_update_time"]
        tied["first_observed_at"] = format_utc_timestamp(tied_start)
        tied["last_observed_at"] = tied_stop
        tied["start_event_time"] = format_utc_timestamp(tied_start)
        tied["stop_event_time"] = tied_stop
        with self.assertRaisesRegex(ObservationError, "tied source event times"):
            aggregate_revision_records([record, tied])

    def test_aggregation_rejects_complete_status_with_failed_evidence(self) -> None:
        record = completed_lifecycle_record(1, 1)
        record["critical_kustomizations"][-1]["classification"] = "current_failed"
        with self.assertRaisesRegex(ObservationError, "incomplete critical evidence"):
            aggregate_revision_records([record])

    def test_aggregation_rejects_a_forged_complete_start(self) -> None:
        record = new_revision_record(lifecycle_observation(1, 0, complete=False))
        record["critical_kustomizations"] = [
            {"classification": "current_ready", "name": item.name, "namespace": item.namespace}
            for item in DEFAULT_CRITICAL_KUSTOMIZATIONS
        ]
        record["duration_seconds"] = 0
        record["status"] = "complete"
        record["stop_event_time"] = record["last_observed_at"]
        with self.assertRaisesRegex(ObservationError, "advance beyond its first observation"):
            aggregate_revision_records([record])

    def test_revision_record_rejects_unknown_evidence_classifications(self) -> None:
        observation = lifecycle_observation(1, 1, complete=False)
        observation["critical_kustomizations"][-1]["classification"] = "untrusted"
        with self.assertRaisesRegex(ObservationError, "invalid classification"):
            new_revision_record(observation)

        record = new_revision_record(lifecycle_observation(1, 1, complete=False))
        record["critical_kustomizations"][-1]["classification"] = "untrusted"
        with self.assertRaisesRegex(ObservationError, "invalid classification"):
            aggregate_revision_records([record])

    def test_cli_rejects_critical_scope_override_before_cluster_read(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as exit_status:
            main(["--critical", "storage/seaweedfs-config"])
        self.assertEqual(exit_status.exception.code, 2)
        self.assertIn("unrecognized arguments: --critical", stderr.getvalue())

    def test_cli_rejects_source_override_before_cluster_read(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as exit_status:
            main(["--source-name", "other"])
        self.assertEqual(exit_status.exception.code, 2)
        self.assertIn("unrecognized arguments: --source-name", stderr.getvalue())

    def test_stale_ready_never_counts_as_converged(self) -> None:
        fixture = self.fixture()
        fixture["kustomizations"]["items"] = [
            kustomization(
                "storage",
                "seaweedfs-config",
                ready="True",
                applied=STALE_REVISION,
                attempted=CURRENT_REVISION,
                source_namespace="flux-system",
            )
        ]
        result = evaluate_revision_convergence(
            fixture["source"],
            fixture["kustomizations"],
            critical=(CriticalKustomization("storage", "seaweedfs-config"),),
            observed_at=parse_utc_timestamp(fixture["now"]),
        )
        self.assertEqual(result["critical_kustomizations"][0]["classification"], "stale_ready")
        self.assertEqual(result["incomplete_count"], 1)

    def test_stale_generation_never_counts_as_converged(self) -> None:
        fixture = self.fixture()
        fixture["kustomizations"]["items"] = [
            kustomization(
                "storage",
                "seaweedfs-config",
                ready="True",
                observed_generation=1,
                condition_generation=1,
                generation=2,
                source_namespace="flux-system",
            )
        ]
        result = evaluate_revision_convergence(
            fixture["source"],
            fixture["kustomizations"],
            critical=(CriticalKustomization("storage", "seaweedfs-config"),),
            observed_at=parse_utc_timestamp(fixture["now"]),
        )
        self.assertEqual(result["critical_kustomizations"][0]["classification"], "stale_ready")

    def test_current_failed_requires_the_exact_full_revision(self) -> None:
        fixture = self.fixture()
        fixture["kustomizations"]["items"] = [
            kustomization(
                "storage",
                "seaweedfs-config",
                ready="False",
                applied=STALE_REVISION,
                source_namespace="flux-system",
            )
        ]
        result = evaluate_revision_convergence(
            fixture["source"],
            fixture["kustomizations"],
            critical=(CriticalKustomization("storage", "seaweedfs-config"),),
            observed_at=parse_utc_timestamp(fixture["now"]),
        )
        self.assertEqual(result["critical_kustomizations"][0]["classification"], "current_failed")

        fixture["kustomizations"]["items"][0]["status"]["lastAttemptedRevision"] = CURRENT_REVISION.rsplit(":", 1)[1]
        result = evaluate_revision_convergence(
            fixture["source"],
            fixture["kustomizations"],
            critical=(CriticalKustomization("storage", "seaweedfs-config"),),
            observed_at=parse_utc_timestamp(fixture["now"]),
        )
        self.assertEqual(result["critical_kustomizations"][0]["classification"], "stale_failed")

    def test_missing_and_source_mismatch_are_incomplete(self) -> None:
        fixture = self.fixture()
        fixture["kustomizations"]["items"] = [
            kustomization("storage", "seaweedfs-config", ready="True", source_namespace="other")
        ]
        result = evaluate_revision_convergence(
            fixture["source"],
            fixture["kustomizations"],
            critical=(
                CriticalKustomization("storage", "seaweedfs-config"),
                CriticalKustomization("storage", "seaweedfs"),
            ),
            observed_at=parse_utc_timestamp(fixture["now"]),
        )
        self.assertEqual(
            [item["classification"] for item in result["critical_kustomizations"]], ["missing", "missing"]
        )
        self.assertEqual(result["critical_kustomizations"][0]["detail"], "source_ref_mismatch")
        self.assertEqual(result["incomplete_count"], 2)

    def test_kustomization_without_status_is_stale_failed(self) -> None:
        fixture = self.fixture()
        resource = kustomization("storage", "seaweedfs-config", ready="False", source_namespace="flux-system")
        del resource["status"]
        fixture["kustomizations"]["items"] = [resource]
        result = evaluate_revision_convergence(
            fixture["source"],
            fixture["kustomizations"],
            critical=(CriticalKustomization("storage", "seaweedfs-config"),),
            observed_at=parse_utc_timestamp(fixture["now"]),
        )
        self.assertEqual(result["critical_kustomizations"][0]["classification"], "stale_failed")

    def test_not_ready_or_malformed_source_fails_closed(self) -> None:
        fixture = self.fixture()
        fixture["source"]["status"]["conditions"][0]["status"] = "False"
        with self.assertRaisesRegex(ObservationError, "not Ready"):
            evaluate_revision_convergence(fixture["source"], fixture["kustomizations"])

        fixture = self.fixture()
        del fixture["source"]["status"]["artifact"]["revision"]
        with self.assertRaisesRegex(ObservationError, "lacks"):
            evaluate_revision_convergence(fixture["source"], fixture["kustomizations"])

    def test_clock_reversal_fails_closed(self) -> None:
        fixture = self.fixture()
        observed_at = parse_utc_timestamp(fixture["source"]["status"]["artifact"]["lastUpdateTime"]) - timedelta(seconds=1)
        with self.assertRaisesRegex(ObservationError, "precedes"):
            evaluate_revision_convergence(fixture["source"], fixture["kustomizations"], observed_at=observed_at)

    def test_read_snapshot_uses_exact_read_only_kubectl_commands(self) -> None:
        fixture = self.fixture()
        commands: list[list[str]] = []

        def runner(command: list[str]) -> dict[str, Any]:
            commands.append(command)
            self.assertNotIn("secret", " ".join(command).lower())
            return fixture["source"] if len(commands) == 1 else fixture["kustomizations"]

        prefix = (
            "mise",
            "exec",
            "--",
            "kubectl",
            "--kubeconfig",
            "/fixture/kubeconfig",
            "--context",
            "fixture-context",
        )
        source, kustomizations = read_cluster_snapshot(runner=runner, prefix_provider=lambda: prefix)
        self.assertIs(source, fixture["source"])
        self.assertIs(kustomizations, fixture["kustomizations"])
        self.assertEqual(
            commands,
            [
                [
                    *prefix,
                    "-n",
                    "flux-system",
                    "get",
                    "gitrepositories.source.toolkit.fluxcd.io",
                    "flux-system",
                    "-o",
                    "json",
                ],
                [*prefix, "get", "kustomizations.kustomize.toolkit.fluxcd.io", "-A", "-o", "json"],
            ],
        )

    def test_target_preflight_failure_prevents_cluster_reads(self) -> None:
        commands: list[list[str]] = []

        def runner(command: list[str]) -> dict[str, Any]:
            commands.append(command)
            return {}

        def fail_preflight() -> tuple[str, ...]:
            raise TargetPreflightError("Anton target preflight failed: cannot resolve Kubernetes context")

        with self.assertRaises(TargetPreflightError):
            read_cluster_snapshot(runner=runner, prefix_provider=fail_preflight)
        self.assertEqual(commands, [])


if __name__ == "__main__":
    unittest.main()
