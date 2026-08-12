#!/usr/bin/env python3
"""Validate the committed immutable Spark runtime contract."""

from __future__ import annotations

import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
RUNTIME = REPO / "images" / "spark-runtime"


def main() -> int:
    files = {
        "Dockerfile": RUNTIME / "Dockerfile",
        "Maven dependency lock": RUNTIME / "pom.xml",
        "runtime verifier": RUNTIME / "verify-runtime.py",
    }
    failures = [f"missing {name}: {path.relative_to(REPO)}" for name, path in files.items() if not path.is_file()]
    if failures:
        print("\n".join(f"[spark.runtime] {failure}" for failure in failures), file=sys.stderr)
        return 1
    dockerfile = files["Dockerfile"].read_text(encoding="utf-8")
    pom = files["Maven dependency lock"].read_text(encoding="utf-8")
    verifier = files["runtime verifier"].read_text(encoding="utf-8")
    required = {
        "Dockerfile": (
            "ubuntu:22.04@sha256:3b06811b2afd352be909dd088a004166d665dc76d38b13eada33522a9d915c6f",
            "maven:3.9.12-eclipse-temurin-21@sha256:c3c9d3ac4ce8431a3995c0318b8d390f448e693dd4fabc16e9b68d2e1f3d7b46",
            "apache/spark:4.1.3-scala2.13-java21-python3-ubuntu@sha256:",
            "ARG PYTHON_VERSION=3.12.11",
            "ARG PYTHON_SHA256=7b8d59af8216044d2313de8120bfc2cc00a9bd2e542f15795e1d616c51faf3d6",
            "PYSPARK_PYTHON=/opt/python/bin/python3.12",
            "PYTHONPATH=/opt/spark/python/lib/pyspark.zip",
            "python3 --version | grep -E '^Python 3\\\\.12\\\\.'",
            "verify-runtime.py --build",
        ),
        "pom.xml": (
            "iceberg-spark-runtime-4.1_2.13",
            "<iceberg.version>1.11.0</iceberg.version>",
            "<hadoop.version>3.4.2</hadoop.version>",
            "iceberg-aws-bundle",
            "hadoop-aws",
        ),
        "verify-runtime.py": (
            "jar-inventory.json",
            "aws-sdk-classes.json",
            "incompatible AWS SDK classes",
            "aws_sdk_version",
            "S3FileIO read/write did not round-trip",
            "Hadoop S3A read/write did not round-trip",
        ),
    }
    contents = {"Dockerfile": dockerfile, "pom.xml": pom, "verify-runtime.py": verifier}
    for name, values in required.items():
        failures.extend(f"{name} missing {value!r}" for value in values if value not in contents[name])
    if "dependency-tree.txt" not in dockerfile:
        failures.append("Dockerfile does not retain the resolved dependency tree")
    prohibited = ("--packages", "spark.jars.packages", "pip install")
    failures.extend(f"runtime source permits dependency download: {value}" for value in prohibited if value in dockerfile or value in verifier)
    if failures:
        print("\n".join(f"[spark.runtime] {failure}" for failure in failures), file=sys.stderr)
        return 1
    print("Spark runtime contract: PASS (pinned image, dependency identity, and storage checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
