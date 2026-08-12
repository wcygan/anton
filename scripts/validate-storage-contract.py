#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Validate the source shape of Anton's shared SeaweedFS provisioner."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
APP = REPO / "kubernetes" / "apps" / "storage" / "seaweedfs-config" / "app"
SCRIPT = APP / "provision-buckets.sh"
CRONJOB = APP / "buckets-cronjob.yaml"
KUSTOMIZATION = APP / "kustomization.yaml"
LAKEHOUSE_SKILL = REPO / ".agents" / "skills" / "seaweedfs-iceberg-lakehouse" / "SKILL.md"
STORAGE_GUIDANCE = REPO / "kubernetes" / "apps" / "storage" / "AGENTS.md"


def validate_provisioner_postbuild_substitution() -> str | None:
    """Return a strict Flux substitution error for the generated ConfigMap."""
    try:
        rendered = subprocess.run(
            ["kustomize", "build", str(APP)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if rendered.returncode != 0:
            return f"Kustomize render: {rendered.stderr.strip()}"

        provisioner = subprocess.run(
            [
                "yq",
                'select(.kind == "ConfigMap" and .metadata.name == "seaweedfs-bucket-provisioner")',
                "-",
            ],
            input=rendered.stdout,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if provisioner.returncode != 0:
            return f"ConfigMap selection: {provisioner.stderr.strip()}"
        if not provisioner.stdout.strip():
            return "ConfigMap selection: seaweedfs-bucket-provisioner was not rendered"

        strict = subprocess.run(
            ["flux", "envsubst", "--strict"],
            input=provisioner.stdout,
            capture_output=True,
            text=True,
            env={"PATH": os.environ["PATH"]},
            timeout=10,
        )
        if strict.returncode != 0:
            return f"strict Flux postBuild substitution: {strict.stderr.strip()}"
    except (KeyError, OSError, subprocess.TimeoutExpired) as error:
        return f"strict Flux postBuild substitution check: {error}"
    return None


def main() -> int:
    failures: list[str] = []
    syntax = subprocess.run(["/bin/sh", "-n", str(SCRIPT)], capture_output=True, text=True, timeout=10)
    if syntax.returncode != 0:
        failures.append(f"provisioner shell syntax: {syntax.stderr.strip()}")

    cronjob = CRONJOB.read_text(encoding="utf-8")
    required_cronjob = (
        "name: seaweedfs-buckets-ensure",
        "value: harbor loki iceberg-raw",
        "value: iceberg-warehouse iceberg-shadow",
        "automountServiceAccountToken: false",
        "readOnlyRootFilesystem: true",
        "name: seaweedfs-bucket-provisioner",
    )
    failures.extend(f"CronJob missing {value!r}" for value in required_cronjob if value not in cronjob)

    kustomization = KUSTOMIZATION.read_text(encoding="utf-8")
    required_kustomization = (
        "configMapGenerator:",
        "provision-buckets.sh=./provision-buckets.sh",
        "./buckets-cronjob.yaml",
    )
    failures.extend(
        f"Kustomization missing {value!r}" for value in required_kustomization if value not in kustomization
    )

    postbuild_substitution_failure = validate_provisioner_postbuild_substitution()
    if postbuild_substitution_failure is not None:
        failures.append(postbuild_substitution_failure)

    removed = (
        APP / "harbor-bucket-cronjob.yaml",
        APP / "lakehouse-buckets-cronjob.yaml",
        REPO / "kubernetes" / "apps" / "observability" / "loki" / "app" / "bucket-cronjob.yaml",
    )
    failures.extend(f"repeated provisioner still exists: {path.relative_to(REPO)}" for path in removed if path.exists())

    lakehouse_skill = LAKEHOUSE_SKILL.read_text(encoding="utf-8")
    required_skill = (
        "cronjob seaweedfs-buckets-ensure",
        "batch.kubernetes.io/cronjob-name=seaweedfs-buckets-ensure",
    )
    failures.extend(
        f"lakehouse skill missing {value!r}" for value in required_skill if value not in lakehouse_skill
    )
    obsolete_job_names = (
        "seaweedfs-lakehouse-buckets-ensure",
        "harbor-bucket-ensure",
        "loki-bucket-ensure",
    )
    failures.extend(
        f"lakehouse skill still references removed job {value!r}"
        for value in obsolete_job_names
        if value in lakehouse_skill
    )

    storage_guidance = STORAGE_GUIDANCE.read_text(encoding="utf-8")
    if "seaweedfs-config/app/buckets-cronjob.yaml" not in storage_guidance:
        failures.append("storage guidance must point to the shared bucket provisioner")

    if failures:
        for failure in failures:
            print(f"[storage.provisioning] {failure}", file=sys.stderr)
        return 1
    print("SeaweedFS provisioning contract: PASS (ordinary S3 + S3 Tables adapters)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
