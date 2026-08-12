#!/usr/bin/env python3
"""Validate the SparkApplication shadow fixture source contract."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "kubernetes/apps/lakehouse/shadow-fixture/app"
TEXT = "\n".join(path.read_text() for path in APP.glob("*.yaml"))
REQUIRED = (
    "apiVersion: spark.apache.org/v1", "kind: SparkApplication", "image: $${SPARK_RUNTIME_IMAGE}",
    "sparkVersion: 4.1.3", "type: Never", "instances: 1", "memory: 768m", "memoryOverhead: 256m",
    "ICEBERG_WAREHOUSE", "s3://iceberg-shadow", "org.apache.iceberg", "ExternalSecret",
)
missing = [item for item in REQUIRED if item not in TEXT]
if missing:
    print("[shadow.fixture] missing: " + ", ".join(missing), file=sys.stderr)
    raise SystemExit(1)
print("Shadow fixture contract: PASS")
