"""Shared SparkApplication specifications for the lakehouse workflows."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


SPARK_RUNTIME_IMAGE = (
    "192.168.1.106/library/spark-runtime@"
    "sha256:77a9e545a49b5eb6ea23fe8e92d78f1ef751ea5aae5a209afd02e0caa46beaf3"
)
CATALOG_URI = "http://seaweedfs-iceberg.storage.svc.cluster.local:8181"
S3_ENDPOINT = "http://seaweedfs-s3.storage.svc.cluster.local:8333"
# Container names the Apache submission worker expects in the pod template.
ADAPTER_DRIVER_CONTAINER = "spark-kubernetes-driver"
ADAPTER_EXECUTOR_CONTAINER = "spark-kubernetes-executor"


def _application_spec(*, secret_name: str) -> dict[str, Any]:
    """Return one Apache ``spark.apache.org/v1`` SparkApplication spec.

    The Apache operator drives the driver and executor as full Kubernetes pod
    templates. The container image, service account, executor count, and
    resources are carried in ``sparkConf``, and the entrypoint is ``pyFiles``.
    """
    shared_env = [
        {"name": "AWS_REGION", "value": "us-east-1"},
        {"name": "HADOOP_CONF_DIR", "value": "/etc/hadoop-event-log"},
        {"name": "ICEBERG_WAREHOUSE", "value": "s3://iceberg-shadow"},
        {"name": "ICEBERG_CATALOG_URI", "value": CATALOG_URI},
        {"name": "S3_ENDPOINT", "value": S3_ENDPOINT},
    ]
    event_log_secret_volume = {
        "name": "event-log-hadoop-config",
        "secret": {
            "secretName": secret_name,
            "items": [{"key": "core-site.xml", "path": "core-site.xml"}],
        },
    }
    event_log_volume_mount = {
        "name": "event-log-hadoop-config",
        "mountPath": "/etc/hadoop-event-log",
        "readOnly": True,
    }
    driver_pod = {
        "containers": [
            {
                "name": ADAPTER_DRIVER_CONTAINER,
                "imagePullPolicy": "IfNotPresent",
                "envFrom": [{"secretRef": {"name": secret_name}}],
                "env": deepcopy(shared_env),
                "volumeMounts": [deepcopy(event_log_volume_mount)],
            }
        ],
        "volumes": [deepcopy(event_log_secret_volume)],
    }
    executor_pod = {
        "containers": [
            {
                "name": ADAPTER_EXECUTOR_CONTAINER,
                "imagePullPolicy": "IfNotPresent",
                "envFrom": [{"secretRef": {"name": secret_name}}],
                "env": deepcopy(shared_env),
                "volumeMounts": [deepcopy(event_log_volume_mount)],
            }
        ],
        "volumes": [deepcopy(event_log_secret_volume)],
    }
    return {
        "spec": {
            "pyFiles": "local:///opt/spark/work-dir/transform.py",
            "deploymentMode": "ClusterMode",
            "runtimeVersions": {"sparkVersion": "4.1.3"},
            "sparkConf": {
                "spark.kubernetes.container.image": SPARK_RUNTIME_IMAGE,
                "spark.kubernetes.authenticate.driver.serviceAccountName": "spark",
                "spark.executor.instances": "1",
                "spark.driver.cores": "1",
                "spark.driver.memory": "768m",
                "spark.driver.memoryOverhead": "256m",
                "spark.executor.cores": "1",
                "spark.executor.memory": "768m",
                "spark.executor.memoryOverhead": "256m",
                "spark.kubernetes.driver.request.cores": "100m",
                "spark.kubernetes.executor.request.cores": "100m",
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
            "driverSpec": {
                "podTemplateSpec": {
                    "metadata": {"labels": {"anton.io/retain-failed-pod": "true"}},
                    "spec": driver_pod,
                },
            },
            "executorSpec": {
                "podTemplateSpec": {
                    "metadata": {"labels": {"anton.io/retain-failed-pod": "true"}},
                    "spec": executor_pod,
                },
            },
            "applicationTolerations": {
                "restartConfig": {"restartPolicy": "Never"},
                "resourceRetainPolicy": "OnFailure",
            },
        }
    }


SHADOW_APPLICATION_SPEC = _application_spec(secret_name="shadow-fixture-s3")
LOKI_APPLICATION_SPEC = _application_spec(secret_name="loki-source-s3")


def clone_application_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Return a mutable copy for a workflow-specific input URI."""
    return deepcopy(spec)
