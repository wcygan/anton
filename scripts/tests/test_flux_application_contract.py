"""Tests for Anton's shared Flux application contract."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "lib"))

from flux_application_contract import validate_repository  # noqa: E402


KS_TEMPLATE = """---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: {name}
spec:
  path: ./kubernetes/apps/{namespace}/{name}/app
  sourceRef:
    kind: GitRepository
    name: flux-system
    namespace: flux-system
{extra}"""


class FluxApplicationContractTests(unittest.TestCase):
    def create_raw_app(
        self,
        root: Path,
        namespace: str,
        name: str,
        *,
        manifest: str = "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: demo\n",
        extra: str = "",
    ) -> Path:
        namespace_root = root / "kubernetes" / "apps" / namespace
        app_root = namespace_root / name
        app_dir = app_root / "app"
        app_dir.mkdir(parents=True, exist_ok=True)
        namespace_root.joinpath("kustomization.yaml").write_text(
            f"---\nresources:\n  - ./{name}/ks.yaml\n", encoding="utf-8"
        )
        app_root.joinpath("ks.yaml").write_text(
            KS_TEMPLATE.format(namespace=namespace, name=name, extra=extra), encoding="utf-8"
        )
        app_dir.joinpath("kustomization.yaml").write_text(
            "---\nresources:\n  - ./resource.yaml\n", encoding="utf-8"
        )
        app_dir.joinpath("resource.yaml").write_text(manifest, encoding="utf-8")
        return app_root

    def codes(self, root: Path) -> set[str]:
        return {violation.code for violation in validate_repository(root)}

    def test_accepts_complete_raw_application(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.create_raw_app(root, "default", "demo")
            self.assertEqual(validate_repository(root), [])

    def test_accepts_complete_helm_application(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = self.create_raw_app(root, "default", "demo")
            app.joinpath("app", "resource.yaml").unlink()
            app.joinpath("app", "helmrelease.yaml").write_text(
                "apiVersion: helm.toolkit.fluxcd.io/v2\nkind: HelmRelease\n", encoding="utf-8"
            )
            app.joinpath("app", "ocirepository.yaml").write_text(
                "apiVersion: source.toolkit.fluxcd.io/v1\nkind: OCIRepository\n", encoding="utf-8"
            )
            self.assertEqual(validate_repository(root), [])

    def test_requires_exactly_one_helm_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = self.create_raw_app(root, "default", "demo")
            app.joinpath("app", "helmrelease.yaml").write_text(
                "apiVersion: helm.toolkit.fluxcd.io/v2\nkind: HelmRelease\n", encoding="utf-8"
            )
            app.joinpath("app", "ocirepository.yaml").write_text(
                "apiVersion: source.toolkit.fluxcd.io/v1\nkind: OCIRepository\n", encoding="utf-8"
            )
            app.joinpath("app", "helmrepository.yaml").write_text(
                "apiVersion: source.toolkit.fluxcd.io/v1\nkind: HelmRepository\n", encoding="utf-8"
            )
            self.assertIn("flux.source.count", self.codes(root))

    def test_requires_namespace_registration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = self.create_raw_app(root, "default", "demo")
            app.parent.joinpath("kustomization.yaml").write_text("---\nresources: []\n", encoding="utf-8")
            self.assertIn("flux.registration.missing", self.codes(root))

    def test_requires_namespace_kustomization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = self.create_raw_app(root, "default", "demo")
            app.parent.joinpath("kustomization.yaml").unlink()
            self.assertIn("flux.registration.missing", self.codes(root))

    def test_commented_namespace_registration_does_not_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = self.create_raw_app(root, "default", "demo")
            app.parent.joinpath("kustomization.yaml").write_text(
                "---\nresources: []\n# ./demo/ks.yaml\n",
                encoding="utf-8",
            )
            self.assertIn("flux.registration.missing", self.codes(root))

    def test_rejects_raw_app_without_material(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = self.create_raw_app(root, "default", "demo")
            app.joinpath("app", "kustomization.yaml").write_text(
                "---\nlabels:\n  - includeSelectors: true\n",
                encoding="utf-8",
            )
            self.assertIn("flux.raw.empty", self.codes(root))

    def test_rejects_raw_app_with_empty_or_non_producing_material(self) -> None:
        invalid_kustomizations = (
            "---\nresources: [ ]\n",
            "---\nresources:\n  - # placeholder\n",
            "---\npatches:\n  - path: patch.yaml\n",
            "---\ntransformers:\n  - labels.yaml\n",
        )
        for kustomization in invalid_kustomizations:
            with self.subTest(kustomization=kustomization), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                app = self.create_raw_app(root, "default", "demo")
                app.joinpath("app", "kustomization.yaml").write_text(kustomization, encoding="utf-8")
                self.assertIn("flux.raw.empty", self.codes(root))

    def test_requires_cross_namespace_dependency_for_custom_resource(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.create_raw_app(root, "observability", "consumer", manifest="apiVersion: external-secrets.io/v1\nkind: ExternalSecret\n")
            self.assertIn("flux.dependency.missing", self.codes(root))

    def test_accepts_explicit_cross_namespace_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.create_raw_app(
                root,
                "observability",
                "consumer",
                manifest="apiVersion: external-secrets.io/v1\nkind: ExternalSecret\n",
                extra="  dependsOn:\n    - name: external-secrets\n      namespace: external-secrets\n",
            )
            self.create_raw_app(root, "external-secrets", "external-secrets", extra="  wait: true\n")
            self.assertEqual(validate_repository(root), [])

    def test_requires_provider_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.create_raw_app(root, "network", "envoy-gateway")
            self.assertIn("flux.provider.readiness", self.codes(root))

    def test_namespace_guidance_is_not_an_application_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.create_raw_app(root, "storage", "demo")
            guidance = root / "kubernetes" / "apps" / "storage" / "AGENTS.md"
            guidance.write_text("# storage\n", encoding="utf-8")
            from flux_application_contract import app_root_for

            self.assertIsNone(app_root_for(guidance, root))


if __name__ == "__main__":
    unittest.main()
