"""Pre-push hook: real git pushes to a local remote, with mise and task faked.

The fake `task` fails when the checked tree contains a file named FAIL, so each
test controls the check result through the commit being pushed.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
TASKFILE = "version: '3'\ntasks:\n  contracts:fast:\n    cmds: [true]\n"
FAKE_MISE = '#!/bin/sh\nwhile [ "$#" -gt 0 ] && [ "$1" != "--" ]; do shift; done\nshift\nexec "$@"\n'
FAKE_TASK = ('#!/bin/sh\n[ "$1" = "--dir" ] && [ "$3" = "contracts:fast" ] || exit 64\n'
             'printf "%s\\n" "$2" >> "$TASK_LOG"\ntest ! -e "$2/FAIL"\n')


class PrePushHookTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        for name, text in (("mise", FAKE_MISE), ("task", FAKE_TASK)):
            (bin_dir / name).write_text(text)
            (bin_dir / name).chmod(0o755)
        self.task_log = self.root / "task.log"
        self.environment = {
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "TASK_LOG": str(self.task_log),
        }
        self.environment.pop("ANTON_BREAK_GLASS", None)
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.root / "remote.git")],
                       check=True, env=self.environment)
        self.work = self.root / "work"
        subprocess.run(["git", "clone", "-q", str(self.root / "remote.git"), str(self.work)],
                       check=True, env=self.environment, stderr=subprocess.DEVNULL)
        for source in (".githooks/pre-push", "scripts/lib/common.sh", "scripts/install-git-hooks.sh"):
            target = self.work / source
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / source, target)
        self.write("Taskfile.yaml", TASKFILE)
        self.base = self.commit("base")
        self.git("push", "-q", "--no-verify", "origin", "HEAD:refs/heads/main")
        self.git("config", "core.hooksPath", str(self.work / ".githooks"))

    def git(self, *args, check=True):
        result = subprocess.run(["git", "-C", str(self.work), *args], env=self.environment,
                                capture_output=True, text=True)
        if check and result.returncode:
            self.fail(f"git {' '.join(args)} failed:\n{result.stdout}{result.stderr}")
        return result

    def write(self, name, text=""):
        path = self.work / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def commit(self, message):
        self.git("add", "-A")
        self.git("-c", "commit.gpgsign=false", "-c", "user.name=Fixture",
                 "-c", "user.email=fixture@example.invalid", "commit", "-qm", message)
        return self.git("rev-parse", "HEAD").stdout.strip()

    def push(self, *refspecs, break_glass=False):
        environment = dict(self.environment)
        if break_glass:
            environment["ANTON_BREAK_GLASS"] = "1"
        return subprocess.run(["git", "-C", str(self.work), "push", "origin", *refspecs],
                              env=environment, capture_output=True, text=True)

    def remote(self, branch):
        result = subprocess.run(["git", "-C", str(self.root / "remote.git"), "rev-parse", "--verify", "-q", branch],
                                env=self.environment, capture_output=True, text=True)
        return result.stdout.strip() or None

    def checked_trees(self):
        return self.task_log.read_text().split() if self.task_log.exists() else []

    def test_passing_commit_is_checked_in_a_throwaway_worktree(self):
        self.write("app.yaml", "ok\n")
        head = self.commit("passing change")
        result = self.push("HEAD:refs/heads/main")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.remote("main"), head)
        [tree] = self.checked_trees()
        self.assertNotEqual(Path(tree).resolve(), self.work.resolve())
        self.assertFalse(Path(tree).exists())
        worktrees = self.git("worktree", "list", "--porcelain").stdout.splitlines()
        self.assertEqual(sum(line.startswith("worktree ") for line in worktrees), 1)

    def test_failing_check_blocks_the_push(self):
        self.write("FAIL")
        self.commit("breaks the contracts")
        result = self.push("HEAD:refs/heads/main")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Fast contract checks failed", result.stdout + result.stderr)
        self.assertEqual(self.remote("main"), self.base)

    def test_uncommitted_files_cannot_change_the_result(self):
        self.write("app.yaml", "ok\n")
        head = self.commit("passing change")
        self.write("FAIL")  # untracked; not part of the pushed commit
        result = self.push("HEAD:refs/heads/main")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.remote("main"), head)

        self.commit("breaks the contracts")  # now FAIL is committed
        os.remove(self.work / "FAIL")  # while the working tree looks clean
        self.assertNotEqual(self.push("HEAD:refs/heads/main").returncode, 0)
        self.assertEqual(self.remote("main"), head)

    def test_deleting_a_branch_runs_no_checks(self):
        self.assertEqual(self.push("--no-verify", "HEAD:refs/heads/feature").returncode, 0)
        result = self.push(":refs/heads/feature")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(self.remote("feature"))
        self.assertEqual(self.checked_trees(), [])

    def test_commit_that_predates_the_fast_checks_is_skipped(self):
        self.write("Taskfile.yaml", "version: '3'\ntasks: {}\n")
        self.write("FAIL")
        head = self.commit("old layout")
        result = self.push("HEAD:refs/heads/legacy")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("predates contracts:fast", result.stdout + result.stderr)
        self.assertEqual(self.remote("legacy"), head)

    def test_deploy_requires_break_glass(self):
        result = self.push("HEAD:refs/heads/deploy")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ANTON_BREAK_GLASS=1", result.stdout + result.stderr)
        self.assertIsNone(self.remote("deploy"))

        result = self.push("HEAD:refs/heads/deploy", break_glass=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.remote("deploy"), self.base)

    def test_break_glass_refuses_a_commit_missing_from_main(self):
        self.write("hotfix.yaml", "fix\n")
        head = self.commit("hotfix")
        result = self.push("HEAD:refs/heads/deploy", break_glass=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not on origin/main", result.stdout + result.stderr)
        self.assertIsNone(self.remote("deploy"))

        result = self.push("--atomic", "HEAD:refs/heads/main", "HEAD:refs/heads/deploy", break_glass=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.remote("main"), self.remote("deploy")), (head, head))
        self.assertEqual(len(self.checked_trees()), 1)

    def test_installed_shim_runs_the_pushing_worktrees_hook(self):
        self.git("config", "--unset", "core.hooksPath")
        install = subprocess.run([str(self.work / "scripts/install-git-hooks.sh")], cwd=self.work,
                                 env=self.environment, capture_output=True, text=True)
        self.assertEqual(install.returncode, 0, install.stderr)
        self.assertEqual(subprocess.run([str(self.work / "scripts/install-git-hooks.sh")], cwd=self.work,
                                        env=self.environment, capture_output=True).returncode, 0)
        self.write("FAIL")
        self.commit("breaks the contracts")
        self.assertNotEqual(self.push("HEAD:refs/heads/main").returncode, 0)
        self.assertEqual(self.remote("main"), self.base)

    def test_installer_keeps_a_foreign_hook(self):
        self.git("config", "--unset", "core.hooksPath")
        foreign = self.work / ".git/hooks/pre-push"
        foreign.write_text("#!/bin/sh\nexit 0\n")
        install = subprocess.run([str(self.work / "scripts/install-git-hooks.sh")], cwd=self.work,
                                 env=self.environment, capture_output=True, text=True)
        self.assertNotEqual(install.returncode, 0)
        self.assertEqual(foreign.read_text(), "#!/bin/sh\nexit 0\n")


if __name__ == "__main__":
    unittest.main()
