"""Deploy Gate verification: steady-state and follow verdicts from recorded snapshots.

The snapshots mirror what scripts/verify-deploy-gate.py reads from Git, GitHub
and the cluster. Nothing here reaches GitHub, the cluster or a remote.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gate = load("verify_deploy_gate", ROOT / "scripts/verify-deploy-gate.py")
docs = load("validate_documentation", ROOT / "scripts/validate-documentation.py")

MAIN, OLD, AUX = "a" * 40, "b" * 40, "c" * 40
AT_MAIN = f"refs/heads/deploy@sha1:{MAIN}"
AT_OLD = f"refs/heads/deploy@sha1:{OLD}"
RUN_URL = "https://github.com/wcygan/anton/actions/runs/1"


def kustomization(name, applied=AT_MAIN, ready="True", reason="ReconciliationSucceeded", source="flux-system"):
    return {"name": name, "source": source, "applied": applied, "ready": ready, "reason": reason}


def state(**changes):
    snapshot = {
        "main": MAIN, "deploy": MAIN, "deploy_on_main": True, "behind": 0,
        "intent": "refs/heads/deploy",
        "run": {"headSha": MAIN, "status": "completed", "conclusion": "success", "url": RUN_URL},
        "source": {"ref": {"name": "refs/heads/deploy"}, "revision": AT_MAIN, "ready": True},
        "instance": {"ref": "refs/heads/deploy", "ready": True},
        "kustomizations": [
            kustomization("flux-system/cluster-apps"),
            kustomization("flux-system/auxiliary-root", applied=f"refs/heads/main@sha1:{AUX}", source="auxiliary"),
        ],
    }
    snapshot.update(changes)
    return snapshot


def statuses(snapshot):
    return {check["check"]: (check["status"], check["detail"]) for check in gate.evaluate_steady(snapshot)}


def behind_main(run_status="in_progress", conclusion=None):
    """deploy one commit behind main, with Flux settled on the older deploy commit."""
    return state(deploy=OLD, behind=1,
                 run={"headSha": MAIN, "status": run_status, "conclusion": conclusion, "url": RUN_URL},
                 source={"ref": {"name": "refs/heads/deploy"}, "revision": AT_OLD, "ready": True},
                 kustomizations=[kustomization("flux-system/cluster-apps", applied=AT_OLD)])


class SteadyTests(unittest.TestCase):
    def test_a_settled_gate_passes_every_check(self):
        result = statuses(state())
        self.assertEqual({name: status for name, (status, _) in result.items()},
                         dict.fromkeys(["intent", "instance", "source", "promotion", "fetch", "apply"], "pass"))
        self.assertEqual(gate.overall(s for s, _ in result.values()), "pass")

    def test_flux_reading_main_fails_because_commits_skip_the_gate(self):
        result = statuses(state(source={"ref": {"name": "refs/heads/main"}, "revision": f"refs/heads/main@sha1:{MAIN}",
                                        "ready": True}))
        self.assertEqual(result["source"], ("fail", "flux-system GitRepository reads refs/heads/main"))
        self.assertNotIn("fetch", result)

    def test_main_committing_the_old_ref_fails_before_flux_follows_it(self):
        result = statuses(state(intent="refs/heads/main"))
        self.assertEqual(result["intent"][0], "fail")

    def test_a_running_gate_is_not_settled_yet(self):
        result = statuses(behind_main())
        self.assertEqual(result["promotion"],
                         ("wait", f"deploy is 1 behind main; the gate is in_progress for {MAIN[:12]}"))
        self.assertEqual(result["fetch"][0], "pass")
        self.assertEqual(gate.overall(s for s, _ in result.values()), "wait")

    def test_a_failed_gate_holds_deploy_back(self):
        status, detail = statuses(behind_main("completed", "failure"))["promotion"]
        self.assertEqual(status, "fail")
        self.assertTrue(detail.startswith(f"held: the gate run for {MAIN[:12]} ended failure"), detail)

    def test_deploy_with_commits_main_lacks_stops_promotion(self):
        result = statuses(state(deploy=OLD, deploy_on_main=False, behind=None))
        self.assertEqual(result["promotion"], ("fail", "deploy has commits that main lacks; promotion is stopped"))

    def test_flux_still_on_the_previous_deploy_commit_waits(self):
        result = statuses(state(source={"ref": {"name": "refs/heads/deploy"}, "revision": AT_OLD, "ready": True},
                                kustomizations=[kustomization("flux-system/cluster-apps", applied=AT_OLD)]))
        self.assertEqual(result["fetch"][0], "wait")
        self.assertEqual(result["apply"][0], "pass")

    def test_kustomizations_still_applying_wait_and_failed_ones_fail(self):
        applying = statuses(state(kustomizations=[
            kustomization("flux-system/cluster-apps", applied=AT_OLD, ready="Unknown", reason="Progressing")]))
        self.assertEqual(applying["apply"][0], "wait")
        failed = statuses(state(kustomizations=[
            kustomization("storage/longhorn", ready="False", reason="HealthCheckFailed")]))
        self.assertEqual(failed["apply"], ("fail", "not Ready: storage/longhorn (HealthCheckFailed)"))

    def test_kustomizations_on_other_sources_keep_their_own_revision(self):
        self.assertEqual(statuses(state())["apply"][0], "pass")

    def test_branch_and_name_refs_normalize_to_the_same_ref(self):
        self.assertEqual(gate.source_ref({"branch": "deploy"}), "refs/heads/deploy")
        self.assertEqual(gate.source_ref({"name": "refs/heads/deploy"}), "refs/heads/deploy")


PROMOTED = datetime(2026, 10, 24, 15, 59, 37, tzinfo=timezone.utc)


def jobs(contracts="success", render="success", promote="success"):
    return [{"name": "Contracts", "conclusion": contracts, "completedAt": "2026-10-24T15:59:26Z"},
            {"name": "Render", "conclusion": render, "completedAt": "2026-10-24T15:58:46Z"},
            {"name": "Promote", "conclusion": promote, "completedAt": "2026-10-24T15:59:37Z"}]


def observed(seen_after=2, applied_after=29, seen_sha=MAIN, reads="refs/heads/deploy"):
    seen = None if seen_after is None else PROMOTED + timedelta(seconds=seen_after)
    applied = None if applied_after is None else PROMOTED + timedelta(seconds=applied_after)
    return {"reads": reads, "seen_sha": seen_sha if seen else None, "seen_at": seen, "applied_at": applied}


RUN = {"databaseId": 1, "headSha": MAIN, "status": "completed", "conclusion": "success", "url": RUN_URL}


class FollowTests(unittest.TestCase):
    def test_a_commit_fetched_after_promote_passes(self):
        verdict, detail = gate.evaluate_follow(MAIN, observed(), RUN, jobs())
        self.assertEqual(verdict, "pass")
        self.assertIn("2s after Promote finished", detail)

    def test_a_commit_fetched_before_promote_fails_as_a_bypass(self):
        verdict, detail = gate.evaluate_follow(MAIN, observed(seen_after=-60), RUN, jobs())
        self.assertEqual((verdict, detail), ("fail", f"the cluster fetched {MAIN[:12]} 60s before Promote finished"))

    def test_clock_skew_within_tolerance_still_passes(self):
        self.assertEqual(gate.evaluate_follow(MAIN, observed(seen_after=-3), RUN, jobs())[0], "pass")

    def test_an_applied_commit_whose_contracts_failed_fails(self):
        verdict, detail = gate.evaluate_follow(MAIN, observed(), RUN, jobs(contracts="failure"))
        self.assertEqual(verdict, "fail")
        self.assertIn("Contracts job ended failure", detail)

    def test_a_failed_gate_run_holds_the_commit_back(self):
        failed = {**RUN, "conclusion": "failure"}
        verdict, detail = gate.evaluate_follow(MAIN, observed(seen_after=None, applied_after=None), failed,
                                               jobs(contracts="failure", promote="skipped"))
        self.assertEqual(verdict, "fail")
        self.assertTrue(detail.startswith("held:"), detail)

    def test_a_commit_not_fetched_yet_waits(self):
        running = {**RUN, "status": "in_progress", "conclusion": None}
        verdict, _ = gate.evaluate_follow(MAIN, observed(seen_after=None, applied_after=None), running, [])
        self.assertEqual(verdict, "wait")

    def test_flux_reading_main_fails_without_waiting(self):
        verdict, _ = gate.evaluate_follow(MAIN, observed(seen_after=None, applied_after=None,
                                                         reads="refs/heads/main"), None, [])
        self.assertEqual(verdict, "fail")

    def test_a_later_main_commit_can_carry_the_followed_one(self):
        verdict, detail = gate.evaluate_follow(OLD, observed(seen_sha=MAIN), RUN, jobs())
        self.assertEqual(verdict, "pass")
        self.assertIn(f"via later main commit {MAIN[:12]}", detail)

    def test_fetched_but_not_applied_in_time_waits(self):
        self.assertEqual(gate.evaluate_follow(MAIN, observed(applied_after=None), RUN, jobs())[0], "wait")


class HookProbeTests(unittest.TestCase):
    def test_the_probe_page_fails_the_documentation_contract(self):
        with tempfile.TemporaryDirectory() as root:
            probe = Path(root) / gate.PROBE
            probe.parent.mkdir(parents=True)
            probe.write_text("probe\n")
            errors = docs.validate(Path(root))
        name = Path(gate.PROBE).name
        self.assertIn(f"{name}: outside canonical sections", errors)


if __name__ == "__main__":
    unittest.main()
