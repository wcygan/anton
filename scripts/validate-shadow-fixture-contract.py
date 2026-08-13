#!/usr/bin/env python3
"""Validate the SparkApplication shadow fixture source contract."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "kubernetes/apps/lakehouse/shadow-fixture/app"
TEXT = "\n".join(path.read_text() for path in APP.glob("*.yaml"))
REQUIRED = (
    "apiVersion: spark.apache.org/v1", "kind: SparkApplication",
    "spark.kubernetes.container.image: 192.168.1.106/library/spark-runtime@sha256:",
    "runtimeVersions", "sparkVersion: \"4.1.3\"",
    "pyFiles: \"local:///opt/spark/application/transform.py\"", "deploymentMode: ClusterMode",
    "applicationTolerations", "restartPolicy: Never", "resourceRetainPolicy: OnFailure",
    "spark.executor.instances", "spark.driver.memory: 768m", "spark.driver.memoryOverhead: 256m",
    "spark-kubernetes-driver", "spark-kubernetes-executor",
    "AWS_REGION", "us-east-1", "ICEBERG_WAREHOUSE", "s3://iceberg-shadow", "org.apache.iceberg", "ExternalSecret",
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
    "persistentvolumeclaims", "deletecollection",
    "anton.io/retain-failed-pod", "spark.eventLog.enabled", "s3a://spark-events/events/",
    "spark.eventLog.compress", "spark.eventLog.rolling.enabled", "spark.eventLog.rolling.maxFileSize",
    "org.apache.hadoop.fs.s3a.SimpleAWSCredentialsProvider", "core-site.xml",
    "seaweedfs-spark-events/writer-access-key", "seaweedfs-spark-events/writer-secret-key",
    "HADOOP_CONF_DIR", "/etc/hadoop-event-log",
)
missing = [item for item in REQUIRED if item not in TEXT]
if missing:
    print("[shadow.fixture] missing: " + ", ".join(missing), file=sys.stderr)
    raise SystemExit(1)
print("Shadow fixture contract: PASS")
