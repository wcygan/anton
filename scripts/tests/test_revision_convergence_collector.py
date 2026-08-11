"""Behavior tests for the prospective revision convergence collector."""

from __future__ import annotations

import contextlib
import fcntl
import io
import json
import os
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest import mock


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "scripts" / "lib"))

import revision_convergence_ledger as ledger_module  # noqa: E402
from cluster_target_contract import TargetPreflightError  # noqa: E402
from collect_revision_convergence import run  # noqa: E402
from revision_convergence import (  # noqa: E402
    DEFAULT_CRITICAL_KUSTOMIZATIONS,
    ObservationError,
    aggregate_revision_records_v2,
    format_exact_utc_timestamp,
    new_revision_record_v2,
    update_revision_record_v2,
)
from revision_convergence_ledger import (  # noqa: E402
    LedgerCommitUncertainError,
    LedgerError,
    collect_revision_observation,
    preview_revision_observation,
    read_revision_ledger,
)


def observation(
    index: int,
    duration_seconds: float,
    *,
    complete: bool,
    fractional: bool = False,
) -> dict[str, Any]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=index)
    if fractional:
        start = start.replace(microsecond=500000)
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
        "observed_at": format_exact_utc_timestamp(observed),
        "schema_version": 1,
        "source": {
            "artifact_last_update_time": format_exact_utc_timestamp(start),
            "kind": "GitRepository",
            "name": "flux-system",
            "namespace": "flux-system",
            "revision": f"refs/heads/main@sha1:{index:040x}",
        },
    }


def private_directory() -> TemporaryDirectory[str]:
    directory = TemporaryDirectory()
    os.chmod(directory.name, 0o700)
    return directory


def write_raw_ledger(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_text(
        json.dumps({"records": records, "schema_version": 1}, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(path, 0o600)


class RevisionConvergenceCollectorTests(unittest.TestCase):
    def test_complete_first_revision_is_an_upper_bound_record(self) -> None:
        record = new_revision_record_v2(observation(1, 3, complete=True))
        self.assertEqual(record["schema_version"], 2)
        self.assertEqual(record["admission"], "complete_first")
        self.assertEqual(record["status"], "complete")
        self.assertEqual(record["duration_seconds"], 3)
        self.assertEqual(record["first_observed_at"], record["stop_event_time"])
        self.assertEqual(record["duration_semantics"], "first_observed_complete_upper_bound")

    def test_fractional_duration_rounds_up_to_keep_the_upper_bound(self) -> None:
        record = new_revision_record_v2(observation(1, 4.6, complete=True, fractional=True))
        self.assertEqual(record["duration_seconds"], 5)

    def test_fractional_timestamps_survive_create_update_and_validation(self) -> None:
        initial = new_revision_record_v2(observation(1, 0, complete=False, fractional=True))
        self.assertIn(".500000Z", initial["start_event_time"])
        completed = update_revision_record_v2(initial, observation(1, 5, complete=True, fractional=True))
        aggregate = aggregate_revision_records_v2([completed])
        self.assertEqual(aggregate["complete_count"], 1)
        self.assertEqual(completed["duration_seconds"], 5)

    def test_new_incomplete_revision_persists_canonical_private_state(self) -> None:
        with private_directory() as directory:
            path = Path(directory) / "records.json"
            result = collect_revision_observation(path, observation(1, 0, complete=False))
            self.assertEqual(result["action"], "inserted")
            self.assertEqual(result["record"]["status"], "incomplete")
            self.assertEqual(stat_mode(path), 0o600)
            self.assertEqual(stat_mode(path.with_name("records.json.lock")), 0o600)
            payload = path.read_text(encoding="utf-8")
            self.assertTrue(payload.endswith("\n"))
            self.assertEqual(payload, json.dumps(json.loads(payload), separators=(",", ":"), sort_keys=True) + "\n")

    def test_later_incomplete_observation_updates_one_record(self) -> None:
        with private_directory() as directory:
            path = Path(directory) / "records.json"
            collect_revision_observation(path, observation(1, 0, complete=False))
            result = collect_revision_observation(path, observation(1, 5, complete=False))
            ledger = read_revision_ledger(path)
            self.assertEqual(result["action"], "updated")
            self.assertEqual(len(ledger["records"]), 1)
            self.assertEqual(ledger["records"][0]["last_observed_at"], observation(1, 5, complete=False)["observed_at"])

    def test_later_complete_observation_finishes_one_record(self) -> None:
        with private_directory() as directory:
            path = Path(directory) / "records.json"
            collect_revision_observation(path, observation(1, 0, complete=False))
            result = collect_revision_observation(path, observation(1, 10, complete=True))
            self.assertEqual(result["record"]["status"], "complete")
            self.assertEqual(result["record"]["duration_seconds"], 10)
            self.assertEqual(result["aggregate"]["complete_count"], 1)

    def test_newer_revision_does_not_close_an_older_incomplete_record(self) -> None:
        with private_directory() as directory:
            path = Path(directory) / "records.json"
            collect_revision_observation(path, observation(1, 0, complete=False))
            collect_revision_observation(path, observation(2, 2, complete=True))
            records = read_revision_ledger(path)["records"]
            self.assertEqual([record["status"] for record in records], ["incomplete", "complete"])

    def test_stale_and_completed_updates_preserve_ledger_bytes(self) -> None:
        with private_directory() as directory:
            path = Path(directory) / "records.json"
            collect_revision_observation(path, observation(1, 0, complete=False))
            before = path.read_bytes()
            with self.assertRaises(LedgerError):
                collect_revision_observation(path, observation(1, 0, complete=False))
            self.assertEqual(path.read_bytes(), before)
            collect_revision_observation(path, observation(1, 5, complete=True))
            complete_bytes = path.read_bytes()
            with self.assertRaises(LedgerError):
                collect_revision_observation(path, observation(1, 6, complete=True))
            self.assertEqual(path.read_bytes(), complete_bytes)

    def test_corrupt_ledger_rejects_before_observation(self) -> None:
        with private_directory() as directory:
            path = Path(directory) / "records.json"
            path.write_text("not-json\n", encoding="utf-8")
            os.chmod(path, 0o600)
            calls = 0

            def provider() -> dict[str, Any]:
                nonlocal calls
                calls += 1
                return observation(1, 0, complete=False)

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                status = run(["--records-path", str(path)], observation_provider=provider)
            self.assertEqual(status, 1)
            self.assertEqual(calls, 0)
            self.assertEqual(path.read_text(encoding="utf-8"), "not-json\n")

    def test_invalid_paths_reject_before_observation(self) -> None:
        calls = 0

        def provider() -> dict[str, Any]:
            nonlocal calls
            calls += 1
            return observation(1, 0, complete=False)

        for records_path in ("relative.json", "/missing-parent-for-anton-m2/records.json"):
            with self.subTest(records_path=records_path):
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    self.assertEqual(run(["--records-path", records_path], observation_provider=provider), 1)
        self.assertEqual(calls, 0)

    def test_symlink_and_public_ledger_reject(self) -> None:
        with private_directory() as directory:
            parent = Path(directory)
            target = parent / "target.json"
            write_raw_ledger(target, [])
            symlink = parent / "linked.json"
            symlink.symlink_to(target)
            with self.assertRaises(LedgerError):
                read_revision_ledger(symlink)

            os.chmod(target, 0o644)
            with self.assertRaises(LedgerError):
                read_revision_ledger(target)

    def test_traversable_parent_directory_rejects(self) -> None:
        with TemporaryDirectory() as directory:
            os.chmod(directory, 0o755)
            path = Path(directory) / "records.json"
            with self.assertRaisesRegex(LedgerError, "mode 0700"):
                read_revision_ledger(path)

    def test_dry_run_observes_but_creates_no_files(self) -> None:
        with private_directory() as directory:
            path = Path(directory) / "records.json"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                status = run(
                    ["--records-path", str(path), "--dry-run"],
                    observation_provider=lambda: observation(1, 0, complete=False),
                )
            self.assertEqual(status, 0)
            self.assertEqual(list(Path(directory).iterdir()), [])
            self.assertTrue(json.loads(stdout.getvalue())["dry_run"])

    def test_preflight_and_observation_failures_write_nothing_and_redact(self) -> None:
        with private_directory() as directory:
            path = Path(directory) / "records.json"
            failures = (
                TargetPreflightError("private-context https://private-endpoint"),
                ObservationError("private-context https://private-endpoint"),
            )
            for failure in failures:
                with self.subTest(failure=type(failure).__name__):
                    stderr = io.StringIO()

                    def provider(error: Exception = failure) -> dict[str, Any]:
                        raise error

                    with contextlib.redirect_stderr(stderr):
                        self.assertEqual(run(["--records-path", str(path)], observation_provider=provider), 1)
                    self.assertNotIn("private-context", stderr.getvalue())
                    self.assertNotIn("private-endpoint", stderr.getvalue())
                    self.assertEqual(list(Path(directory).iterdir()), [])

    def test_collector_rejects_observed_time_override_before_cluster_read(self) -> None:
        calls = 0

        def provider() -> dict[str, Any]:
            nonlocal calls
            calls += 1
            return observation(1, 0, complete=False)

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
            run(
                ["--records-path", "/private/tmp/records.json", "--observed-at", "2026-01-01T00:00:00Z"],
                observation_provider=provider,
            )
        self.assertEqual(raised.exception.code, 2)
        self.assertEqual(calls, 0)
        self.assertIn("unrecognized arguments: --observed-at", stderr.getvalue())

    def test_persisted_schema_omits_forbidden_observer_fields(self) -> None:
        with private_directory() as directory:
            path = Path(directory) / "records.json"
            collect_revision_observation(path, observation(1, 0, complete=False))
            payload = json.loads(path.read_text(encoding="utf-8"))
            serialized = json.dumps(payload, sort_keys=True).lower()
            for forbidden_key in ("context", "endpoint", "address", "message", "ready_reason", "source_ref"):
                self.assertNotIn(f'"{forbidden_key}"', serialized)

    def test_duplicate_and_tied_records_reject_without_rewrite(self) -> None:
        with private_directory() as directory:
            path = Path(directory) / "records.json"
            first = new_revision_record_v2(observation(1, 0, complete=False))
            write_raw_ledger(path, [first, first])
            before = path.read_bytes()
            with self.assertRaises(LedgerError):
                read_revision_ledger(path)
            self.assertEqual(path.read_bytes(), before)

            second = new_revision_record_v2(observation(2, 0, complete=False))
            second["source"]["artifact_last_update_time"] = first["source"]["artifact_last_update_time"]
            second["start_event_time"] = first["start_event_time"]
            write_raw_ledger(path, [first, second])
            before = path.read_bytes()
            with self.assertRaises(LedgerError):
                read_revision_ledger(path)
            self.assertEqual(path.read_bytes(), before)

    def test_concurrent_distinct_revisions_serialize(self) -> None:
        with private_directory() as directory:
            path = Path(directory) / "records.json"
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(collect_revision_observation, path, observation(index, 0, complete=False))
                    for index in (1, 2)
                ]
                for future in futures:
                    future.result()
            self.assertEqual(len(read_revision_ledger(path)["records"]), 2)

    def test_concurrent_duplicate_revision_leaves_one_record(self) -> None:
        with private_directory() as directory:
            path = Path(directory) / "records.json"
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(collect_revision_observation, path, observation(1, 0, complete=False))
                    for _ in range(2)
                ]
                outcomes = []
                for future in futures:
                    try:
                        future.result()
                        outcomes.append("written")
                    except LedgerError:
                        outcomes.append("rejected")
            self.assertEqual(sorted(outcomes), ["rejected", "written"])
            self.assertEqual(len(read_revision_ledger(path)["records"]), 1)

    def test_lock_contention_times_out_without_writing_ledger(self) -> None:
        with private_directory() as directory:
            path = Path(directory) / "records.json"
            lock_path = path.with_name("records.json.lock")
            lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            os.fchmod(lock_fd, 0o600)
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            try:
                with self.assertRaisesRegex(LedgerError, "timed out"):
                    collect_revision_observation(
                        path,
                        observation(1, 0, complete=False),
                        lock_timeout_seconds=0,
                    )
                self.assertFalse(path.exists())
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                os.close(lock_fd)

    def test_atomic_replace_failure_preserves_previous_bytes(self) -> None:
        with private_directory() as directory:
            path = Path(directory) / "records.json"
            collect_revision_observation(path, observation(1, 0, complete=False))
            before = path.read_bytes()
            with mock.patch.object(ledger_module.os, "replace", side_effect=OSError("fixture failure")):
                with self.assertRaisesRegex(LedgerError, "atomic write failed"):
                    collect_revision_observation(path, observation(2, 0, complete=False))
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(
                [item.name for item in Path(directory).iterdir() if ".tmp-" in item.name],
                [],
            )

    def test_directory_sync_failure_reports_installed_unconfirmed_state(self) -> None:
        with private_directory() as directory:
            path = Path(directory) / "records.json"
            collect_revision_observation(path, observation(1, 0, complete=False))
            real_fsync = ledger_module.os.fsync
            calls = 0

            def fail_directory_sync(fd: int) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("fixture directory sync failure")
                real_fsync(fd)

            with mock.patch.object(ledger_module.os, "fsync", side_effect=fail_directory_sync):
                with self.assertRaisesRegex(LedgerCommitUncertainError, "replacement succeeded"):
                    collect_revision_observation(path, observation(2, 0, complete=False))
            self.assertEqual(len(read_revision_ledger(path)["records"]), 2)

    def test_nonfinite_lock_timeout_rejects_before_state_creation(self) -> None:
        with private_directory() as directory:
            path = Path(directory) / "records.json"
            for timeout in (float("nan"), float("inf")):
                with self.subTest(timeout=timeout), self.assertRaisesRegex(LedgerError, "finite"):
                    collect_revision_observation(
                        path,
                        observation(1, 0, complete=False),
                        lock_timeout_seconds=timeout,
                    )
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_rolling_thirty_v2_records_keep_nearest_rank_math(self) -> None:
        records = [new_revision_record_v2(observation(index, index, complete=True)) for index in range(1, 31)]
        aggregate = aggregate_revision_records_v2(records)
        self.assertTrue(aggregate["eligible"])
        self.assertEqual(aggregate["p50_seconds"], 15)
        self.assertEqual(aggregate["p95_seconds"], 29)
        self.assertEqual(aggregate["maximum_seconds"], 30)


def stat_mode(path: Path) -> int:
    return os.stat(path, follow_symlinks=False).st_mode & 0o777


if __name__ == "__main__":
    unittest.main()
