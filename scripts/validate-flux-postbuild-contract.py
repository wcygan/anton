#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Validate strict Flux postBuild substitution for application renders."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
APPLICATIONS = REPO / "kubernetes" / "apps"
COMMAND_TIMEOUT_SECONDS = 10
VALIDATION_WORKERS = 4
FIXED_SUBSTITUTIONS = {
    "SECRET_DOMAIN": "example.invalid",
    "SECRET_DOMAIN_TWO": "example-two.invalid",
    "SECRET_DOMAIN_THREE": "example-three.invalid",
    "TAILNET_SUFFIX": "tailnet.invalid",
}
CONFIGMAP_GENERATOR = re.compile(r"(?m)^configMapGenerator:\s*$")
FLUX_KUSTOMIZATION_API_VERSION = "kustomize.toolkit.fluxcd.io/v1"
FLUX_KUSTOMIZATION_KIND = "Kustomization"


class DiscoveryError(RuntimeError):
    """Report a Kustomization that cannot be inspected safely."""


def discover_application_roots(repo: Path = REPO) -> tuple[Path, ...]:
    """Return every current application root with a Kustomization file."""

    applications = repo / "kubernetes" / "apps"
    return tuple(sorted(path.parent for path in applications.glob("**/app/kustomization.yaml")))


def discover_configmap_roots(repo: Path = REPO) -> tuple[Path, ...]:
    """Return application roots that generate ConfigMaps."""

    return tuple(
        path
        for path in discover_application_roots(repo)
        if CONFIGMAP_GENERATOR.search((path / "kustomization.yaml").read_text(encoding="utf-8"))
    )


def ks_declares_postbuild(ks: Path, repo: Path = REPO) -> bool:
    """Return whether a Flux Kustomization declares spec.postBuild."""

    try:
        result = subprocess.run(
            ["yq", "-o=json", ".", str(ks)],
            capture_output=True,
            text=True,
            env=strict_environment(),
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        raise DiscoveryError(f"cannot inspect {ks}: {error}") from error

    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or f"exit status {result.returncode}"
        raise DiscoveryError(f"cannot inspect {ks}: {message}")

    try:
        document = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise DiscoveryError(f"cannot parse {ks}: {error.msg}") from error

    if not isinstance(document, dict):
        raise DiscoveryError(f"{ks}: expected a YAML mapping")
    if document.get("apiVersion") != FLUX_KUSTOMIZATION_API_VERSION:
        raise DiscoveryError(f"{ks}: unexpected apiVersion")
    if document.get("kind") != FLUX_KUSTOMIZATION_KIND:
        raise DiscoveryError(f"{ks}: unexpected kind")

    spec = document.get("spec")
    if not isinstance(spec, dict):
        raise DiscoveryError(f"{ks}: spec must be a mapping")

    try:
        expected_path = f"./{(ks.parent / 'app').relative_to(repo).as_posix()}"
    except ValueError as error:
        raise DiscoveryError(f"{ks}: is outside repository {repo}") from error
    if spec.get("path") != expected_path:
        raise DiscoveryError(f"{ks}: spec.path must be {expected_path}")

    if "postBuild" not in spec:
        return False
    if not isinstance(spec["postBuild"], dict):
        raise DiscoveryError(f"{ks}: spec.postBuild must be a non-null mapping")
    return True


def discover_postbuild_roots(repo: Path = REPO) -> tuple[Path, ...]:
    """Return app roots whose sibling ks.yaml declares spec.postBuild."""

    applications = repo / "kubernetes" / "apps"
    return tuple(
        sorted(
            ks.parent / "app"
            for ks in applications.glob("**/ks.yaml")
            if ks_declares_postbuild(ks, repo)
        )
    )


def strict_environment() -> dict[str, str]:
    """Return the only environment available to strict Flux substitution."""

    try:
        path = os.environ["PATH"]
    except KeyError as error:
        raise RuntimeError("PATH is required to run Flux substitution") from error
    return {"PATH": path, **FIXED_SUBSTITUTIONS}


def validate_postbuild_root(root: Path) -> str | None:
    """Return an error when a postBuild application root fails strict substitution."""

    kustomization = root / "kustomization.yaml"
    if not root.is_dir():
        return "application root is missing"
    if not kustomization.is_file():
        return "application root is missing kustomization.yaml"

    try:
        environment = strict_environment()
        rendered = subprocess.run(
            ["kustomize", "build", str(root)],
            capture_output=True,
            text=True,
            env=environment,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
        if rendered.returncode != 0:
            return f"Kustomize render failed: {rendered.stderr.strip()}"
        if not rendered.stdout.strip():
            return "Kustomize render failed: no resources were rendered"

        strict = subprocess.run(
            ["flux", "envsubst", "--strict"],
            input=rendered.stdout,
            capture_output=True,
            text=True,
            env=environment,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
        if strict.returncode != 0:
            return f"strict Flux postBuild substitution failed: {strict.stderr.strip()}"
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        return f"strict Flux postBuild substitution check failed: {error}"
    return None


def validate_postbuild_roots(roots: tuple[Path, ...]) -> tuple[str | None, ...]:
    """Validate roots concurrently and preserve discovery order in results."""

    with ThreadPoolExecutor(max_workers=VALIDATION_WORKERS) as executor:
        return tuple(executor.map(validate_postbuild_root, roots))


def main() -> int:
    try:
        roots = discover_postbuild_roots()
    except DiscoveryError as error:
        print(f"[flux.postbuild] {error}", file=sys.stderr)
        return 1

    failures: list[str] = []
    if not roots:
        failures.append("no postBuild application roots were discovered")
    for root, failure in zip(roots, validate_postbuild_roots(roots), strict=True):
        if failure is not None:
            failures.append(f"{root.relative_to(REPO)}: {failure}")

    if failures:
        for failure in failures:
            print(f"[flux.postbuild] {failure}", file=sys.stderr)
        return 1
    print(f"Flux postBuild substitution contract: PASS ({len(roots)} of {len(discover_application_roots())} roots)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
