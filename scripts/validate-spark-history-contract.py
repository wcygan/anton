#!/usr/bin/env python3
"""Validate Spark event history and resource retention source contracts."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "kubernetes/apps/lakehouse/spark-history-server/app"
ROOT_KUSTOMIZATION = ROOT / "kubernetes/apps/lakehouse/kustomization.yaml"
POD_GC = ROOT / "kubernetes/apps/kube-system/pod-gc/app/cronjob.yaml"
FIXTURE = ROOT / "kubernetes/apps/lakehouse/shadow-fixture/app/sparkapplication.yaml"


def main() -> int:
    failures: list[str] = []
    files = {path.name: path.read_text(encoding="utf-8") for path in APP.iterdir() if path.is_file()}
    text = "\n".join(files.values())

    required = (
        "replicas: 1",
        "org.apache.spark.deploy.history.HistoryServer",
        "s3a://spark-events/events/",
        "spark.history.fs.cleaner.enabled false",
        "software.amazon.awssdk.auth.credentials.EnvironmentVariableCredentialsProvider",
        "automountServiceAccountToken: false",
        "name: spark-events-reader",
        "seaweedfs-spark-events/reader-access-key",
        "seaweedfs-spark-events/reader-secret-key",
        'value: "3600"',
        'value: "86400"',
        "anton.io/retain-failed-pod=true",
    )
    failures.extend(f"history contract missing {item!r}" for item in required if item not in text)

    if text.count("automountServiceAccountToken: false") < 2:
        failures.append("History Server must disable token mounting on its ServiceAccount and pod")

    fixture = FIXTURE.read_text(encoding="utf-8")
    fixture_image = re.search(r"(?m)^  image: (.+@sha256:[0-9a-f]{64})$", fixture)
    history_image = re.search(r"(?m)^          image: (.+@sha256:[0-9a-f]{64})$", text)
    if fixture_image is None or history_image is None or fixture_image.group(1) != history_image.group(1):
        failures.append("History Server must use the exact fixture Spark image digest")

    if "- --selector=anton.io/retain-failed-pod!=true" not in POD_GC.read_text(encoding="utf-8"):
        failures.append("global failed-pod collection must exclude retained Spark pods")

    if "./spark-history-server/ks.yaml" not in ROOT_KUSTOMIZATION.read_text(encoding="utf-8"):
        failures.append("lakehouse namespace must register the History Server Kustomization")

    syntax = subprocess.run(
        ["/bin/sh", "-n", str(APP / "retain-spark-pods.sh")],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if syntax.returncode != 0:
        failures.append(f"retention cleaner shell syntax: {syntax.stderr.strip()}")

    render = subprocess.run(
        ["kustomize", "build", str(APP)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if render.returncode != 0:
        failures.append(f"History Server Kustomize render: {render.stderr.strip()}")

    if failures:
        for failure in failures:
            print(f"[spark.history] {failure}", file=sys.stderr)
        return 1

    print("Spark history contract: PASS (event logs, read-only history, bounded pod retention)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
