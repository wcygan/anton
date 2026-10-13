"""Exercise shared root defaults and ownership-transfer overrides through Kustomize."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


def build(path):
    rendered = subprocess.check_output(["kustomize", "build", str(path)], text=True, timeout=30)
    parsed = subprocess.run(
        ["yq", "-o=json", "-I=0", "."], input=rendered,
        capture_output=True, text=True, check=True, timeout=30,
    )
    return [json.loads(line) for line in parsed.stdout.splitlines() if line.strip()]


def apply_patches(document, patches):
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "resource.yaml").write_text(json.dumps(document), encoding="utf-8")
        (root / "kustomization.yaml").write_text(json.dumps({
            "apiVersion": "kustomize.config.k8s.io/v1beta1",
            "kind": "Kustomization", "resources": ["resource.yaml"], "patches": patches,
        }), encoding="utf-8")
        return build(root)[0]


class FluxChildDefaultsTests(unittest.TestCase):
    def child(self):
        return {
            "apiVersion": "kustomize.toolkit.fluxcd.io/v1", "kind": "Kustomization",
            "metadata": {"name": "fixture", "namespace": "default"},
            "spec": {"interval": "1h", "prune": True, "suspend": False},
        }

    def test_both_roots_apply_child_and_helm_defaults(self):
        roots = [
            build(REPO / "kubernetes/flux/cluster")[0],
            next(obj for obj in build(REPO / "kubernetes/apps/flux-system/auxiliary/app")
                 if obj["kind"] == "Kustomization"),
        ]
        for root in roots:
            with self.subTest(root=root["metadata"]["name"]):
                child = apply_patches(self.child(), root["spec"]["patches"])
                self.assertEqual(child["spec"]["decryption"], {"provider": "sops"})
                self.assertEqual(child["spec"]["deletionPolicy"], "WaitForTermination")
                self.assertTrue(child["spec"]["prune"])
                release = apply_patches({
                    "apiVersion": "helm.toolkit.fluxcd.io/v2", "kind": "HelmRelease",
                    "metadata": {"name": "fixture"}, "spec": {"interval": "1h"},
                }, child["spec"]["patches"])
                self.assertEqual(release["spec"], {
                    "interval": "1h",
                    "install": {"crds": "CreateReplace", "strategy": {"name": "RetryOnFailure"}},
                    "rollback": {"cleanupOnFail": True, "recreate": True},
                    "upgrade": {
                        "cleanupOnFail": True, "crds": "CreateReplace",
                        "strategy": {"name": "RemediateOnFailure"},
                        "remediation": {"remediateLastFailure": True, "retries": 2},
                    },
                })

    def test_handoff_override_runs_after_shared_defaults(self):
        for path, name in [
            ("kubernetes/flux/cluster", "cluster-apps"),
            ("kubernetes/apps/flux-system/auxiliary/app", "auxiliary-root"),
        ]:
            with self.subTest(root=name), tempfile.TemporaryDirectory() as temporary:
                self.check_handoff_override(Path(temporary), path, name)

    def check_handoff_override(self, root, path, name):
        entry = root / path
        shutil.copytree(REPO / path, entry)
        shutil.copytree(REPO / "kubernetes/components/flux-child-defaults",
                        root / "kubernetes/components/flux-child-defaults")
        override = {
            "apiVersion": "kustomize.toolkit.fluxcd.io/v1", "kind": "Kustomization",
            "metadata": {"name": "fixture"},
            "spec": {"suspend": True, "prune": False, "deletionPolicy": "Orphan"},
        }
        append = [{"op": "add", "path": "/spec/patches/-", "value": {
            "patch": json.dumps(override),
            "target": {"group": "kustomize.toolkit.fluxcd.io", "kind": "Kustomization",
                       "name": "fixture", "namespace": "default"},
        }}]
        config_file = entry / "kustomization.yaml"
        config = json.loads(subprocess.check_output(
            ["yq", "-o=json", ".", str(config_file)], text=True, timeout=30,
        ))
        config["patches"] = [{
            "target": {"kind": "Kustomization", "name": name},
            "patch": json.dumps(append),
        }]
        config_file.write_text(json.dumps(config), encoding="utf-8")
        parent = next(obj for obj in build(entry) if obj["kind"] == "Kustomization")
        child = apply_patches(self.child(), parent["spec"]["patches"])
        self.assertTrue(child["spec"]["suspend"])
        self.assertFalse(child["spec"]["prune"])
        self.assertEqual(child["spec"]["deletionPolicy"], "Orphan")
        self.assertEqual(child["spec"]["decryption"], {"provider": "sops"})

if __name__ == "__main__":
    unittest.main()
