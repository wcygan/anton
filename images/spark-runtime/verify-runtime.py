#!/usr/bin/env python3
"""Record and verify the immutable Spark runtime contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import zipfile
from pathlib import Path


SPARK_HOME = Path(os.environ.get("SPARK_HOME", "/opt/spark"))
JARS = SPARK_HOME / "jars"
EVIDENCE = SPARK_HOME / "runtime-contract"
EXPECTED = {
    "spark": "4.1.3",
    "scala": "2.13",
    "java": "21",
    "python": "3.12",
    "iceberg": "1.11.0",
    "hadoop": "3.4.2",
}


def fail(message: str) -> None:
    raise RuntimeError(message)


def jar_inventory() -> list[dict[str, str]]:
    return [
        {"name": jar.name, "sha256": hashlib.file_digest(jar.open("rb"), "sha256").hexdigest()}
        for jar in sorted(JARS.glob("*.jar"))
    ]


def aws_sdk_classes() -> dict[str, set[str]]:
    classes: dict[str, set[str]] = {}
    for jar in JARS.glob("*.jar"):
        with zipfile.ZipFile(jar) as archive:
            for name in archive.namelist():
                if not name.startswith("software/amazon/awssdk/") or not name.endswith(".class"):
                    continue
                classes.setdefault(name, set()).add(hashlib.sha256(archive.read(name)).hexdigest())
    return classes


def write_build_evidence() -> None:
    inventory = jar_inventory()
    aws_classes = aws_sdk_classes()
    incompatible = sorted(name for name, hashes in aws_classes.items() if len(hashes) > 1)
    if incompatible:
        fail(f"incompatible AWS SDK classes: {', '.join(incompatible[:5])}")
    if not any(item["name"].startswith("iceberg-spark-runtime-4.1_2.13-1.11.0") for item in inventory):
        fail("Iceberg Spark 4.1 runtime is absent")
    if not any(item["name"].startswith("hadoop-aws-3.4.2") for item in inventory):
        fail("Hadoop S3A 3.4.2 is absent")
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "jar-inventory.json").write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    (EVIDENCE / "aws-sdk-classes.json").write_text(
        json.dumps({name: sorted(hashes) for name, hashes in sorted(aws_classes.items())}, indent=2) + "\n",
        encoding="utf-8",
    )
    dependency_tree = (EVIDENCE / "dependency-tree.txt").read_text(encoding="utf-8")
    aws_sdk_versions = sorted(set(re.findall(r"software\.amazon\.awssdk:[^:]+:jar:([0-9.]+)", dependency_tree)))
    if len(aws_sdk_versions) != 1:
        fail(f"expected one AWS SDK v2 version, found: {', '.join(aws_sdk_versions) or 'none'}")
    (EVIDENCE / "effective-versions.json").write_text(
        json.dumps({**EXPECTED, "aws_sdk_version": aws_sdk_versions[0]}, indent=2) + "\n",
        encoding="utf-8",
    )


def require_prefix(label: str, actual: str, expected: str) -> None:
    if not actual.startswith(expected):
        fail(f"{label} is {actual!r}; expected {expected!r}")


def check_runtime() -> None:
    import pyspark
    from pyspark.sql import SparkSession

    require_prefix("Python", f"{sys.version_info.major}.{sys.version_info.minor}", EXPECTED["python"])
    require_prefix("PySpark", pyspark.__version__, EXPECTED["spark"])
    spark = SparkSession.builder.master("local[1]").appName("runtime-contract").getOrCreate()
    try:
        jvm = spark.sparkContext._jvm
        require_prefix("Spark", spark.version, EXPECTED["spark"])
        require_prefix("Scala", jvm.scala.util.Properties.versionNumberString(), EXPECTED["scala"])
        require_prefix("Java", jvm.java.lang.System.getProperty("java.version"), EXPECTED["java"])
        require_prefix("Hadoop", jvm.org.apache.hadoop.util.VersionInfo.getVersion(), EXPECTED["hadoop"])
    finally:
        spark.stop()


def storage_contract() -> None:
    required = ("ICEBERG_CATALOG_URI", "S3_ENDPOINT", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        fail(f"storage contract needs: {', '.join(missing)}")
    from pyspark.sql import SparkSession

    suffix = hashlib.sha256(os.urandom(16)).hexdigest()[:12]
    catalog = "contract"
    table = f"{catalog}.runtime_contract_{suffix}"
    s3a_path = f"s3a://spark-runtime-contract/runtime-contract-{suffix}.txt"
    spark = (
        SparkSession.builder.master("local[1]").appName("storage-contract")
        .config(f"spark.sql.catalog.{catalog}", "org.apache.iceberg.spark.SparkCatalog")
        .config(f"spark.sql.catalog.{catalog}.catalog-impl", "org.apache.iceberg.rest.RESTCatalog")
        .config(f"spark.sql.catalog.{catalog}.uri", os.environ["ICEBERG_CATALOG_URI"])
        .config(f"spark.sql.catalog.{catalog}.warehouse", os.environ.get("ICEBERG_WAREHOUSE", "s3://iceberg-shadow"))
        .config(f"spark.sql.catalog.{catalog}.io-impl", "org.apache.iceberg.aws.s3.S3FileIO")
        .config(f"spark.sql.catalog.{catalog}.s3.endpoint", os.environ["S3_ENDPOINT"])
        .config(f"spark.sql.catalog.{catalog}.s3.path-style-access", "true")
        .config("spark.hadoop.fs.s3a.endpoint", os.environ["S3_ENDPOINT"])
        .config("spark.hadoop.fs.s3a.path.style.access", "true")
        .config("spark.hadoop.fs.s3a.access.key", os.environ["AWS_ACCESS_KEY_ID"])
        .config("spark.hadoop.fs.s3a.secret.key", os.environ["AWS_SECRET_ACCESS_KEY"])
        .getOrCreate()
    )
    try:
        spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {catalog}")
        spark.sql(f"CREATE TABLE {table} (id INT) USING iceberg")
        spark.sql(f"INSERT INTO {table} VALUES (1)")
        if spark.table(table).count() != 1:
            fail("Iceberg S3FileIO read/write did not round-trip")
        jvm = spark.sparkContext._jvm
        path = jvm.org.apache.hadoop.fs.Path(s3a_path)
        filesystem = path.getFileSystem(spark.sparkContext._jsc.hadoopConfiguration())
        stream = filesystem.create(path, True)
        stream.write(bytearray(b"s3a-runtime-contract"))
        stream.close()
        reader = filesystem.open(path)
        payload = bytes(reader.readAllBytes())
        reader.close()
        filesystem.delete(path, False)
        if payload != b"s3a-runtime-contract":
            fail("Hadoop S3A read/write did not round-trip")
    finally:
        spark.stop()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--storage", action="store_true")
    args = parser.parse_args()
    try:
        if args.build:
            write_build_evidence()
        else:
            check_runtime()
            if args.storage:
                storage_contract()
    except RuntimeError as error:
        print(f"Spark runtime contract: FAIL: {error}", file=sys.stderr)
        return 1
    print("Spark runtime contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
