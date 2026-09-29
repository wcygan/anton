"""Real Git fixtures for the committed-source bundle boundary."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("security_source_export", REPO / "scripts/export-security-source.py")
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


class SecuritySourceExportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.repository = self.root / "website"
        self.repository.mkdir()
        self.destination = self.root / "bundles"
        self.environment = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
        self.git("init", "-q")
        self.write("package.json", "{}")
        self.write("Dockerfile", "FROM nginx:alpine\nCOPY public /usr/share/nginx/html\n")
        self.write("src/index.ts", "export const message = 'committed'\n")
        self.write(".gitignore", ".env\n")
        self.write("k8s/secret.yaml", "operator fixture excluded\n")
        self.write("docs/operator.md", "operator documentation excluded\n")
        self.commit()
        self.revision = self.git("rev-parse", "HEAD").strip()

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repository), *args],
                                       text=True, env=self.environment, stderr=subprocess.DEVNULL)

    def write(self, name, text):
        path = self.repository / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def commit(self):
        self.git("add", "-A")
        self.git("-c", "commit.gpgsign=false", "-c", "user.name=Fixture",
                 "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture")

    def test_exports_exact_commit_without_worktree_or_operator_files(self):
        self.write("src/index.ts", "local edit\n")
        self.write("src/untracked.ts", "untracked\n")
        self.write(".env", "ignored fixture\n")
        metadata = exporter.export_source(self.repository, self.revision, self.destination)
        self.assertEqual(metadata["sourceRevision"], self.revision)
        with tarfile.open(self.destination / metadata["archive"], "r:gz") as archive:
            self.assertEqual(archive.extractfile("src/index.ts").read(), b"export const message = 'committed'\n")
            self.assertEqual(sorted(m.name for m in archive.getmembers() if m.isfile()),
                             ["Dockerfile", "package.json", "src/index.ts"])
        self.assertEqual(json.loads((self.destination / metadata["manifest"]).read_text()), metadata)
        self.assertEqual(hashlib.sha256((self.destination / metadata["archive"]).read_bytes()).hexdigest(), metadata["sha256"])
        for name in (metadata["archive"], metadata["manifest"]):
            self.assertEqual((self.destination / name).stat().st_mode & 0o777, 0o600)

    def test_future_commit_regenerates_a_separate_identified_bundle(self):
        first = exporter.export_source(self.repository, self.revision, self.destination)
        self.write("src/index.ts", "new committed source\n")
        self.commit()
        second = exporter.export_source(self.repository, "HEAD", self.destination)
        self.assertNotEqual(first["sourceRevision"], second["sourceRevision"])
        self.assertNotEqual(first["archive"], second["archive"])
        self.assertTrue((self.destination / first["archive"]).exists())

    def test_symlink_stops_before_writing_a_bundle(self):
        (self.repository / "src/link").symlink_to("../k8s/secret.yaml")
        self.commit()
        with self.assertRaisesRegex(ValueError, "link or submodule"):
            exporter.export_source(self.repository, "HEAD", self.destination)
        self.assertFalse(self.destination.exists())

    def test_committed_credential_like_file_stops_before_export(self):
        self.write("src/age.key", "synthetic fixture, not a credential\n")
        self.commit()
        with self.assertRaisesRegex(ValueError, "credential-like"):
            exporter.export_source(self.repository, "HEAD", self.destination)
        self.assertFalse(self.destination.exists())

    def test_task_passes_hostile_revision_as_data(self):
        marker = self.root / "unexpected-execution"
        result = subprocess.run([
            "task", "--taskfile", str(REPO / "Taskfile.yaml"), "security:source-export",
            f"REPOSITORY={self.repository}", f"REVISION=$(touch {marker})",
        ], capture_output=True, text=True, env=self.environment)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Export stopped", result.stderr)
        self.assertFalse(marker.exists())
