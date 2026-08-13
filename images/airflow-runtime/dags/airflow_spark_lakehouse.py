"""Scheduled shadow lakehouse workflow owned by Airflow."""

from __future__ import annotations

import pendulum

from airflow.sdk import dag

from anton_airflow.spark import ApacheSparkApplicationOperator


SHADOW_APPLICATION_SPEC = {
    "spec": {
        "type": "Python",
        "pythonVersion": "3",
        "mode": "cluster",
        "image": "192.168.1.106/library/spark-runtime@sha256:28efc7381ed7560ee806aeead8ba864daf989126bdb8f0f5b7d668beeafcb056",
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
            "spark.hadoop.fs.s3a.endpoint": "http://seaweedfs-s3.storage.svc.cluster.local:8333",
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
                    "secretName": "shadow-fixture-s3",
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
                {"name": "event-log-hadoop-config", "mountPath": "/etc/hadoop-event-log", "readOnly": True}
            ],
            "envFrom": [{"secretRef": {"name": "shadow-fixture-s3"}}],
            "env": [
                {"name": "AWS_REGION", "value": "us-east-1"},
                {"name": "HADOOP_CONF_DIR", "value": "/etc/hadoop-event-log"},
                {"name": "ICEBERG_WAREHOUSE", "value": "s3://iceberg-shadow"},
                {"name": "ICEBERG_CATALOG_URI", "value": "http://seaweedfs-iceberg.storage.svc.cluster.local:8181"},
                {"name": "S3_ENDPOINT", "value": "http://seaweedfs-s3.storage.svc.cluster.local:8333"},
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
                {"name": "event-log-hadoop-config", "mountPath": "/etc/hadoop-event-log", "readOnly": True}
            ],
            "envFrom": [{"secretRef": {"name": "shadow-fixture-s3"}}],
            "env": [
                {"name": "AWS_REGION", "value": "us-east-1"},
                {"name": "HADOOP_CONF_DIR", "value": "/etc/hadoop-event-log"},
            ],
        },
    }
}


@dag(
    dag_id="airflow_spark_lakehouse",
    schedule="23 * * * *",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    tags=["anton", "lakehouse", "spark"],
)
def airflow_spark_lakehouse():
    """Run one shadow Spark Attempt for each Airflow Workflow Run."""

    ApacheSparkApplicationOperator(
        task_id="run_shadow_spark_attempt",
        application_spec=SHADOW_APPLICATION_SPEC,
        target="shadow",
        namespace="lakehouse",
        poll_interval=10.0,
        deferrable=True,
    )


spark_lakehouse_dag = airflow_spark_lakehouse()
