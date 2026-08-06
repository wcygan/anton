"""Idempotent JSONL fixture load for the SeaweedFS Iceberg REST demo."""
import os

from pyspark.sql import SparkSession, functions as F, types as T

CATALOG = "lake"
CATALOG_URI = os.getenv(
    "ICEBERG_CATALOG_URI", "http://seaweedfs-iceberg.storage.svc.cluster.local:8181"
)
S3_ENDPOINT = os.getenv(
    "ICEBERG_S3_ENDPOINT", "http://seaweedfs-s3.storage.svc.cluster.local:8333"
)
WAREHOUSE = os.getenv("ICEBERG_WAREHOUSE", "s3://iceberg-warehouse")


def main() -> None:
    builder = (
        SparkSession.builder.appName("iceberg-log-fixture")
        .config(f"spark.sql.catalog.{CATALOG}", "org.apache.iceberg.spark.SparkCatalog")
        .config(f"spark.sql.catalog.{CATALOG}.catalog-impl", "org.apache.iceberg.rest.RESTCatalog")
        .config(f"spark.sql.catalog.{CATALOG}.uri", CATALOG_URI)
        .config(f"spark.sql.catalog.{CATALOG}.warehouse", WAREHOUSE)
        .config(f"spark.sql.catalog.{CATALOG}.io-impl", "org.apache.iceberg.aws.s3.S3FileIO")
        .config(f"spark.sql.catalog.{CATALOG}.s3.endpoint", S3_ENDPOINT)
        .config(f"spark.sql.catalog.{CATALOG}.s3.path-style-access", "true")
        .config(
            f"spark.sql.catalog.{CATALOG}.s3.region",
            os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1")),
        )
        # Iceberg's AWS SDK S3FileIO resolves AWS_ACCESS_KEY_ID and
        # AWS_SECRET_ACCESS_KEY from the ESO-provided driver/executor env.
        .config("spark.sql.extensions", "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions")
    )
    access_key = os.getenv("AWS_ACCESS_KEY_ID")
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    if access_key and secret_key:
        # SeaweedFS REST exchanges this credential at /v1/oauth/tokens.
        # Keep it in Spark's runtime configuration; never print it.
        builder = builder.config(
            f"spark.sql.catalog.{CATALOG}.credential", f"{access_key}:{secret_key}"
        )
    spark = builder.getOrCreate()
    schema = T.StructType([
        T.StructField("event_id", T.StringType(), False), T.StructField("ts", T.TimestampType(), False),
        T.StructField("service", T.StringType(), False), T.StructField("level", T.StringType(), False),
        T.StructField("message", T.StringType(), False),
    ])
    raw = spark.read.schema(schema).json("/opt/spark/work-dir/fixture.jsonl")
    # iceberg-raw is provisioned for the optional bounded Loki snapshot gate;
    # this first deterministic gate intentionally reads its fixture locally.
    normalized = raw.dropDuplicates(["event_id"]).withColumn("event_date", F.to_date("ts"))
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {CATALOG}.logs")
    spark.sql(f"""CREATE TABLE IF NOT EXISTS {CATALOG}.logs.normalized (
      event_id string, ts timestamp, service string, level string, message string,
      event_date date
    ) USING iceberg PARTITIONED BY (event_date)""")
    normalized.createOrReplaceTempView("incoming_normalized")
    spark.sql(f"""MERGE INTO {CATALOG}.logs.normalized t USING incoming_normalized s
      ON t.event_id = s.event_id WHEN MATCHED THEN UPDATE SET *
      WHEN NOT MATCHED THEN INSERT *""")
    hourly = (normalized.withColumn("hour", F.date_trunc("hour", "ts"))
              .groupBy("hour", "service", "level").agg(F.count("*").alias("event_count")))
    spark.sql(f"""CREATE TABLE IF NOT EXISTS {CATALOG}.logs.hourly (
      hour timestamp, service string, level string, event_count bigint
    ) USING iceberg PARTITIONED BY (days(hour))""")
    hourly.createOrReplaceTempView("incoming_hourly")
    # Rebuild the tiny derived aggregate from the deduplicated normalized table.
    # This avoids an Iceberg 1.5/Spark 3.5 MERGE planner bug with transformed
    # day partitions while remaining idempotent: every run has the same rows.
    spark.sql(f"DELETE FROM {CATALOG}.logs.hourly")
    spark.sql(f"INSERT INTO {CATALOG}.logs.hourly SELECT hour, service, level, event_count FROM incoming_hourly")
    print(f"expected normalized rows=5 actual={normalized.count()}")
    print(f"expected hourly rows=5 actual={hourly.count()}")
    spark.stop()


if __name__ == "__main__":
    main()
