"""Deploy gate: fast-forward-only promotion and the workflow wiring around it."""

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import unittest
from pathlib import Path
from unittest import mock


REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("promote_deploy", REPO / "scripts/promote-deploy.py")
promoter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(promoter)

REPOSITORY = "owner/anton"
MAIN = [f"{index:040x}" for index in range(1, 6)]  # oldest first
STRAY = "f" * 40  # child of MAIN[1] that never reached main


class FakeGitHub:
    """Answers the REST calls promote() makes, enforcing fast-forward like GitHub."""

    def __init__(self, deploy=None):
        self.ancestors = {sha: set(MAIN[:index + 1]) for index, sha in enumerate(MAIN)}
        self.ancestors[STRAY] = set(MAIN[:2]) | {STRAY}
        self.refs = {"main": MAIN[-1]}
        if deploy:
            self.refs["deploy"] = deploy
        self.writes = []
        self.before_write = None
        self.failure = None

    def relation(self, base, head):
        ahead = len(self.ancestors[head] - self.ancestors[base])
        behind = len(self.ancestors[base] - self.ancestors[head])
        if not ahead and not behind:
            return "identical"
        if not behind:
            return "ahead"
        if not ahead:
            return "behind"
        return "diverged"

    def resolve(self, name):
        return self.refs.get(name, name)

    def __call__(self, method, path, body):
        if self.failure:
            return self.failure
        prefix = f"/repos/{REPOSITORY}"
        assert path.startswith(prefix), path
        path = path[len(prefix):]
        if method == "GET" and path.startswith("/compare/"):
            base, head = path[len("/compare/"):].split("?")[0].split("...")
            return 200, {"status": self.relation(self.resolve(base), self.resolve(head))}
        if method == "GET" and path == "/git/ref/heads/deploy":
            if "deploy" not in self.refs:
                return 404, {"message": "Not Found"}
            return 200, {"object": {"sha": self.refs["deploy"]}}
        if self.before_write:
            self.before_write(self)
            self.before_write = None
        if method == "POST" and path == "/git/refs":
            if "deploy" in self.refs:
                return 422, {"message": "Reference already exists"}
            self.refs["deploy"] = body["sha"]
            self.writes.append(("create", body["sha"]))
            return 201, {}
        if method == "PATCH" and path == "/git/refs/heads/deploy":
            if body.get("force") is not False:
                raise AssertionError("promotion must never force-update deploy")
            if self.relation(self.refs["deploy"], body["sha"]) != "ahead":
                return 422, {"message": "Update is not a fast forward"}
            self.refs["deploy"] = body["sha"]
            self.writes.append(("update", body["sha"]))
            return 200, {}
        raise AssertionError(f"unexpected request {method} {path}")


def run(api, commit):
    return promoter.promote(api, REPOSITORY, commit)


class PromotionTests(unittest.TestCase):
    def test_first_passing_commit_creates_deploy(self):
        api = FakeGitHub()
        self.assertEqual(run(api, MAIN[2]), "created")
        self.assertEqual(api.refs["deploy"], MAIN[2])

    def test_passing_commit_fast_forwards_deploy(self):
        api = FakeGitHub(deploy=MAIN[1])
        self.assertEqual(run(api, MAIN[3]), "promoted")
        self.assertEqual(api.writes, [("update", MAIN[3])])

    def test_slow_run_for_an_older_commit_never_rewinds_deploy(self):
        api = FakeGitHub(deploy=MAIN[3])
        self.assertEqual(run(api, MAIN[1]), "current")
        self.assertEqual(api.refs["deploy"], MAIN[3])
        self.assertEqual(api.writes, [])

    def test_rerun_for_the_deployed_commit_changes_nothing(self):
        api = FakeGitHub(deploy=MAIN[2])
        self.assertEqual(run(api, MAIN[2]), "current")
        self.assertEqual(api.writes, [])

    def test_deploy_with_commits_missing_from_main_stops_promotion(self):
        api = FakeGitHub(deploy=STRAY)
        with self.assertRaisesRegex(promoter.PromotionError, "not on main"):
            run(api, MAIN[4])
        self.assertEqual(api.refs["deploy"], STRAY)

    def test_commit_dropped_from_main_is_not_promoted(self):
        api = FakeGitHub(deploy=MAIN[1])
        self.assertEqual(run(api, STRAY), "skipped")
        self.assertEqual(api.writes, [])

    def test_newer_concurrent_promotion_wins(self):
        api = FakeGitHub(deploy=MAIN[1])
        api.before_write = lambda fake: fake.refs.update(deploy=MAIN[4])
        self.assertEqual(run(api, MAIN[3]), "current")
        self.assertEqual(api.refs["deploy"], MAIN[4])

    def test_older_concurrent_promotion_is_fast_forwarded(self):
        api = FakeGitHub(deploy=MAIN[1])
        api.before_write = lambda fake: fake.refs.update(deploy=MAIN[2])
        self.assertEqual(run(api, MAIN[3]), "promoted")
        self.assertEqual(api.refs["deploy"], MAIN[3])

    def test_concurrent_creation_is_reevaluated(self):
        api = FakeGitHub()
        api.before_write = lambda fake: fake.refs.update(deploy=MAIN[3])
        self.assertEqual(run(api, MAIN[2]), "current")
        self.assertEqual(api.refs["deploy"], MAIN[3])

    def test_unexpected_api_answers_fail_closed(self):
        api = FakeGitHub(deploy=MAIN[1])
        api.failure = (502, {"message": "Bad Gateway"})
        with self.assertRaisesRegex(promoter.PromotionError, "HTTP 502"):
            run(api, MAIN[3])
        self.assertEqual(api.refs["deploy"], MAIN[1])

    def test_command_line_refuses_missing_token_and_short_sha(self):
        for environment, commit in (({}, MAIN[2]), ({"GH_TOKEN": "token"}, MAIN[2][:12])):
            with self.subTest(environment=environment, commit=commit), \
                    mock.patch.dict(os.environ, environment, clear=True), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(promoter.main(["--repository", REPOSITORY, "--commit", commit]), 2)


def yq_json(path, expression="."):
    return json.loads(subprocess.check_output(["yq", "-o=json", expression, str(REPO / path)], text=True))


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = yq_json(".github/workflows/deploy-gate.yaml")
        cls.jobs = cls.workflow["jobs"]

    def test_every_check_must_pass_before_promotion(self):
        checks = set(self.jobs) - {"promote"}
        self.assertTrue(checks)
        self.assertEqual(set(self.jobs["promote"]["needs"]), checks)

    def test_only_main_promotes(self):
        condition = self.jobs["promote"]["if"]
        self.assertIn("github.ref == 'refs/heads/main'", condition)
        self.assertIn("github.event_name != 'pull_request'", condition)
        self.assertEqual(set(self.workflow["on"]["push"]["branches"]), {"main"})
        self.assertIn("pull_request", self.workflow["on"])

    def test_write_credentials_stay_in_the_deploy_environment(self):
        self.assertEqual(self.jobs["promote"]["environment"], "deploy")
        self.assertEqual(self.workflow["permissions"], {"contents": "read"})
        for name, job in self.jobs.items():
            with self.subTest(job=name):
                self.assertNotIn("permissions", job)
                for step in job["steps"]:
                    if step.get("uses", "").startswith("actions/checkout@"):
                        self.assertIs(step["with"]["persist-credentials"], False)

    def test_gate_runs_the_full_suite(self):
        commands = [step.get("run", "") for step in self.jobs["contracts"]["steps"]]
        self.assertIn("mise exec -- task contracts:validate", commands)
        validate = yq_json("Taskfile.yaml", '.tasks."contracts:validate".cmds')
        self.assertIn({"task": "contracts:fast"}, validate)
        self.assertTrue(any("unittest discover" in str(command) for command in validate))


class FluxSourceTests(unittest.TestCase):
    def test_flux_reconciles_only_the_promoted_branch(self):
        sync = yq_json("kubernetes/apps/flux-system/flux-instance/app/helmrelease.yaml",
                       ".spec.values.instance.sync")
        self.assertEqual(sync["ref"], "refs/heads/deploy")

    def test_image_automation_writes_through_the_gate(self):
        ref = yq_json("kubernetes/apps/flux-system/flux-instance/app/image-automation-gitrepository.yaml",
                      ".spec.ref")
        self.assertEqual(ref, {"name": "refs/heads/main"})


if __name__ == "__main__":
    unittest.main()
