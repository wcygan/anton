"""Tests for strict Flux postBuild substitution."""

from __future__ import annotations

from collections.abc import Callable
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO / "scripts" / "validate-flux-postbuild-contract.py"
SPEC = importlib.util.spec_from_file_location("validate_flux_postbuild_contract", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class FluxPostBuildContractTests(unittest.TestCase):
    def generated_root(self, script: str) -> tempfile.TemporaryDirectory[str]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        (root / "script.sh").write_text(script, encoding="utf-8")
        (root / "kustomization.yaml").write_text(
            """---
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
configMapGenerator:
  - name: fixture-script
    files:
      - script.sh=./script.sh
""",
            encoding="utf-8",
        )
        return temporary

    def write_ks(
        self,
        root: Path,
        *,
        postbuild: str | None = None,
        app: bool = True,
        path: str | None = None,
    ) -> Path:
        app_root = root / "kubernetes" / "apps" / "fixture" / "service" / "app"
        app_root.parent.mkdir(parents=True, exist_ok=True)
        ks = app_root.parent / "ks.yaml"
        ks.write_text(
            """---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
spec:
"""
            + f"  path: {path or './kubernetes/apps/fixture/service/app'}\n"
            + (f"  postBuild: {postbuild}\n" if postbuild is not None else "  interval: 1h\n"),
            encoding="utf-8",
        )
        if app:
            app_root.mkdir()
            (app_root / "kustomization.yaml").write_text(
                """---
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources: []
""",
                encoding="utf-8",
            )
        return app_root

    def test_generated_configmap_baseline_remains_two_roots(self) -> None:
        self.assertEqual(
            [path.relative_to(REPO).as_posix() for path in MODULE.discover_configmap_roots()],
            [
                "kubernetes/apps/registries/harbor-config/app",
                "kubernetes/apps/storage/seaweedfs-config/app",
            ],
        )

    def test_discovers_every_current_postbuild_application_root(self) -> None:
        roots = MODULE.discover_postbuild_roots()
        self.assertEqual(len(MODULE.discover_application_roots()), 49)
        self.assertEqual(
            [path.relative_to(REPO).as_posix() for path in roots],
            [
                "kubernetes/apps/bakery-site/server/app",
                "kubernetes/apps/cert-manager/cert-manager/app",
                "kubernetes/apps/databases/cloudnative-pg/app",
                "kubernetes/apps/databases/dragonfly-operator/app",
                "kubernetes/apps/default/echo/app",
                "kubernetes/apps/default/homepage/app",
                "kubernetes/apps/external-secrets/external-secrets/app",
                "kubernetes/apps/external-secrets/onepassword-store/app",
                "kubernetes/apps/flux-system/flux-instance/app",
                "kubernetes/apps/flux-system/flux-operator/app",
                "kubernetes/apps/iceberg-demo/spark-fixture/app",
                "kubernetes/apps/iceberg-demo/trino/app",
                "kubernetes/apps/kube-system/cilium/app",
                "kubernetes/apps/kube-system/coredns/app",
                "kubernetes/apps/kube-system/metrics-server/app",
                "kubernetes/apps/kube-system/reloader/app",
                "kubernetes/apps/kube-system/spegel/app",
                "kubernetes/apps/lakehouse/shadow-fixture/app",
                "kubernetes/apps/network/cloudflare-dns/app",
                "kubernetes/apps/network/cloudflare-tunnel/app",
                "kubernetes/apps/network/envoy-gateway/app",
                "kubernetes/apps/network/k8s-gateway/app",
                "kubernetes/apps/network/multus/app",
                "kubernetes/apps/network/storage-vxlan/app",
                "kubernetes/apps/network/whereabouts/app",
                "kubernetes/apps/observability/kube-prometheus-stack/app",
                "kubernetes/apps/observability/loki/app",
                "kubernetes/apps/observability/ntfy/app",
                "kubernetes/apps/observability/otel-collector/app",
                "kubernetes/apps/observability/talos-log-sink/app",
                "kubernetes/apps/registries/harbor/app",
                "kubernetes/apps/registries/harbor-config/app",
                "kubernetes/apps/spark-system/spark-operator/app",
                "kubernetes/apps/storage/longhorn/app",
                "kubernetes/apps/storage/longhorn-config/app",
                "kubernetes/apps/storage/seaweedfs/app",
                "kubernetes/apps/storage/seaweedfs-config/app",
                "kubernetes/apps/temporal/temporal/app",
                "kubernetes/apps/temporal/temporal-config/app",
            ],
        )

    def test_no_postbuild_ks_is_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app_root = self.write_ks(root)
            self.assertEqual(MODULE.discover_postbuild_roots(root), ())
            self.assertEqual(MODULE.discover_application_roots(root), (app_root,))

    def test_postbuild_ks_missing_app_root_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app_root = self.write_ks(root, postbuild="{}", app=False)
            self.assertEqual(MODULE.discover_postbuild_roots(root), (app_root,))
            self.assertEqual(MODULE.validate_postbuild_root(app_root), "application root is missing")

    def test_postbuild_requires_a_non_null_mapping(self) -> None:
        for postbuild in ("null", "value", "[]"):
            with self.subTest(postbuild=postbuild), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.write_ks(root, postbuild=postbuild)
                with self.assertRaisesRegex(MODULE.DiscoveryError, "spec.postBuild must be a non-null mapping"):
                    MODULE.discover_postbuild_roots(root)

    def test_divergent_ks_path_fails_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_ks(root, postbuild="{}", path="./kubernetes/apps/other/service/app")
            with self.assertRaisesRegex(MODULE.DiscoveryError, "spec.path must be"):
                MODULE.discover_postbuild_roots(root)

    def test_wrong_api_version_or_kind_fails_discovery(self) -> None:
        for source, replacement, message in (
            ("apiVersion: kustomize.toolkit.fluxcd.io/v1", "apiVersion: v1", "unexpected apiVersion"),
            ("kind: Kustomization", "kind: ConfigMap", "unexpected kind"),
        ):
            with self.subTest(replacement=replacement), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                app_root = self.write_ks(root, postbuild="{}")
                ks = app_root.parent / "ks.yaml"
                ks.write_text(ks.read_text(encoding="utf-8").replace(source, replacement), encoding="utf-8")
                with self.assertRaisesRegex(MODULE.DiscoveryError, message):
                    MODULE.discover_postbuild_roots(root)

    def test_strict_environment_has_only_the_fixed_allow_list(self) -> None:
        with patch.dict(os.environ, {"PATH": "/fixture/bin", "UNEXPECTED": "value"}, clear=True):
            environment = MODULE.strict_environment()
        self.assertEqual(
            environment,
            {
                "PATH": "/fixture/bin",
                "SECRET_DOMAIN": "example.invalid",
                "SECRET_DOMAIN_TWO": "example-two.invalid",
                "SECRET_DOMAIN_THREE": "example-three.invalid",
                "TAILNET_SUFFIX": "tailnet.invalid",
            },
        )

    def test_discovery_uses_the_strict_environment(self) -> None:
        environment = {"PATH": "/fixture/bin", "SECRET_DOMAIN": "example.invalid"}
        document = {
            "apiVersion": "kustomize.toolkit.fluxcd.io/v1",
            "kind": "Kustomization",
            "spec": {
                "path": "./kubernetes/apps/fixture/service/app",
                "postBuild": {},
            },
        }
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(MODULE, "strict_environment", return_value=environment),
            patch.object(
                MODULE.subprocess,
                "run",
                return_value=subprocess.CompletedProcess(["yq"], 0, json.dumps(document), ""),
            ) as run,
        ):
            root = Path(temporary)
            ks = root / "kubernetes" / "apps" / "fixture" / "service" / "ks.yaml"
            ks.parent.mkdir(parents=True)
            self.assertTrue(MODULE.ks_declares_postbuild(ks, root))

        self.assertEqual(run.call_args.kwargs["env"], environment)

    def test_validation_workers_are_bounded_and_results_stay_ordered(self) -> None:
        roots = (Path("first"), Path("second"))
        worker_count: list[int] = []

        class RecordingExecutor:
            def __init__(self, *, max_workers: int) -> None:
                worker_count.append(max_workers)

            def __enter__(self) -> "RecordingExecutor":
                return self

            def __exit__(self, *_: object) -> None:
                return None

            def map(
                self,
                function: Callable[[Path], str | None],
                values: tuple[Path, ...],
            ) -> tuple[str | None, ...]:
                return tuple(function(value) for value in values)

        with (
            patch.object(MODULE, "ThreadPoolExecutor", RecordingExecutor),
            patch.object(MODULE, "validate_postbuild_root", side_effect=("first failure", "second failure")),
        ):
            results = MODULE.validate_postbuild_roots(roots)

        self.assertEqual(worker_count, [4])
        self.assertEqual(results, ("first failure", "second failure"))

    def test_unescaped_runtime_variable_fails_strict_substitution(self) -> None:
        with self.generated_root('value="${runtime_var}"\n') as temporary:
            failure = MODULE.validate_postbuild_root(Path(temporary))
        self.assertIsNotNone(failure)
        self.assertIn("strict Flux postBuild substitution failed", failure)

    def test_kustomize_and_flux_use_the_same_strict_environment(self) -> None:
        environment = {"PATH": "/fixture/bin", "SECRET_DOMAIN": "example.invalid"}
        completed = (
            subprocess.CompletedProcess(["kustomize"], 0, "apiVersion: v1\nkind: ConfigMap\n", ""),
            subprocess.CompletedProcess(["flux"], 0, "", ""),
        )
        with (
            self.generated_root("value=fixture\n") as temporary,
            patch.object(MODULE, "strict_environment", return_value=environment),
            patch.object(MODULE.subprocess, "run", side_effect=completed) as run,
        ):
            self.assertIsNone(MODULE.validate_postbuild_root(Path(temporary)))

        self.assertEqual(run.call_args_list[0].kwargs["env"], environment)
        self.assertEqual(run.call_args_list[1].kwargs["env"], environment)
        self.assertIs(run.call_args_list[0].kwargs["env"], run.call_args_list[1].kwargs["env"])

    def test_escaped_runtime_variable_survives_strict_substitution(self) -> None:
        with self.generated_root('value="$${runtime_var}"\n') as temporary:
            failure = MODULE.validate_postbuild_root(Path(temporary))
        self.assertIsNone(failure)

    def test_empty_render_output_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "kustomization.yaml").write_text(
                """---
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources: []
""",
                encoding="utf-8",
            )
            failure = MODULE.validate_postbuild_root(root)
        self.assertEqual(failure, "Kustomize render failed: no resources were rendered")


if __name__ == "__main__":
    unittest.main()
