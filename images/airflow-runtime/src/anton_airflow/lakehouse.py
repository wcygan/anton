"""Shared SparkApplication specifications for the lakehouse workflows."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


SPARK_RUNTIME_IMAGE = (
    "192.168.1.106/library/spark-runtime@"
    "sha256:28efc7381ed7560ee806aeead8ba864daf989126bdb8f0f5b7d668beeafcb056"
)
CATALOG_URI = "http://seaweedfs-iceberg.storage.svc.cluster.local:8181"
S3_ENDPOINT = "http://seaweedfs-s3.storage.svc.cluster.local:8333"


def _application_spec(*, secret_name: str) -> dict[str, Any]:
    return {
        "spec": {
            "type": "Python",
            "pythonVersion": "3",
            "mode": "cluster",
            "image": SPARK_RUNTIME_IMAGE,
            "imagePullPolicy": "IfNotPresent",
            "mainApplicationFile": "local:///opt/spark/work-dir/transform.py",
            "sparkVersion": "4.1.3",
            "timeToLiveSeconds": 604800,
            "sparkConf": {
                "spark.eventLog.enabled": "true",
                "spark.eventLog.dir": "s3a://spark-events/events/",
                "spark.eventLog.compress": "true",
                "spark.eventLog.rolling.enabled": "true",
                "spark.eventLog.rolling.maxFileSize": "64m",
                "spark.hadoop.fs.s3a.endpoint": S3_ENDPOINT,
                "spark.hadoop.fs.s3a.path.style.access": "true",
                "spark.hadoop.fs.s3a.connection.ssl.enabled": "false",
                "spark.sql.catalog.lake": "org.apache.iceberg.spark.SparkCatalog",
                "spark.sql.catalog.lake.io-impl": "org.apache.iceberg.aws.s3.S3FileIO",
                "spark.sql.iceberg.write.format-version": "2",
            },
            "volumes": [
                {
                    "name": "event-log-hadoop-config",
                    "secret": {
                        "secretName": secret_name,
                        "items": [{"key": "core-site.xml", "path": "core-site.xml"}],
                    },
                }
            ],
            "driver": {
                "cores": 1,
                "coreRequest": "100m",
                "memory": "768m",
                "memoryOverhead": "256m",
                "serviceAccount": "shadow-fixture",
                "volumeMounts": [
                    {
                        "name": "event-log-hadoop-config",
                        "mountPath": "/etc/hadoop-event-log",
                        "readOnly": True,
                    }
                ],
                "envFrom": [{"secretRef": {"name": secret_name}}],
                "env": [
                    {"name": "AWS_REGION", "value": "us-east-1"},
                    {"name": "HADOOP_CONF_DIR", "value": "/etc/hadoop-event-log"},
                    {"name": "ICEBERG_WAREHOUSE", "value": "s3://iceberg-shadow"},
                    {"name": "ICEBERG_CATALOG_URI", "value": CATALOG_URI},
                    {"name": "S3_ENDPOINT", "value": S3_ENDPOINT},
                ],
            },
            "executor": {
                "instances": 1,
                "deleteOnTermination": False,
                "cores": 1,
                "coreRequest": "100m",
                "memory": "768m",
                "memoryOverhead": "256m",
                "volumeMounts": [
                    {
                        "name": "event-log-hadoop-config",
                        "mountPath": "/etc/hadoop-event-log",
                        "readOnly": True,
                    }
                ],
                "envFrom": [{"secretRef": {"name": secret_name}}],
                "env": [
                    {"name": "AWS_REGION", "value": "us-east-1"},
                    {"name": "HADOOP_CONF_DIR", "value": "/etc/hadoop-event-log"},
                ],
            },
        }
    }


SHADOW_APPLICATION_SPEC = _application_spec(secret_name="shadow-fixture-s3")
LOKI_APPLICATION_SPEC = _application_spec(secret_name="loki-source-s3")


def clone_application_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Return a mutable copy for a workflow-specific input URI."""
    return deepcopy(spec)
