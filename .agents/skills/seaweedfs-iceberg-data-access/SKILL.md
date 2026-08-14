---
name: seaweedfs-iceberg-data-access
description: >-
  Read and validate Anton's SeaweedFS Iceberg tables through Spark and Trino.
  Use for Spark catalog configuration, Iceberg table reads and writes, Trino
  SQL, cross-engine comparisons, table schemas and locations, or data-access
  troubleshooting in the internal lakehouse demo.
---

# SeaweedFS Iceberg Data Access

This skill covers the data plane for Anton's internal SeaweedFS Iceberg
lakehouse. Use `seaweedfs-iceberg-lakehouse` for storage, catalog service,
Harbor, legacy fixture deployment, credential prerequisites, and teardown.
Use `airflow-spark-lakehouse` for workflow operations.

The shared contract is:

```text
Spark / Trino
    |
    +-- Iceberg REST catalog: http://seaweedfs-iceberg.storage.svc.cluster.local:8181
    +-- S3 data files:         http://seaweedfs-s3.storage.svc.cluster.local:8333
    +-- warehouse:             s3://iceberg-warehouse
    +-- namespace:             logs
    +-- tables:                normalized, hourly
```

The learning platform is internal and reviewed by 2026-09-10 under ADR 0033.
Keep the catalog and S3 endpoint private. Keep one catalog service.

## Read first

1. Read repository `AGENTS.md`.
2. Read `context/adrs/0033-adopt-airflow-spark-operator-lakehouse.md` for the
   current architectural contract.
3. Read `context/plans/0023-roll-out-airflow-spark-lakehouse.md` for current
   writer ownership.
   After schedule enablement, read
   `.agents/skills/airflow-spark-lakehouse/references/scheduled-observation.md`.
4. Read ADR 0031 and Plan 0020 for the underlying table history.
5. Read `docs/docs/notes/seaweedfs-iceberg-log-lakehouse.md` for the table
   layout and known limitations.
6. Read the source configuration in:
   - `images/airflow-runtime/dags/airflow_spark_lakehouse.py`
   - `images/spark-runtime/`
   - `images/iceberg-log-spark/transform.py` for the legacy writer
   - `kubernetes/apps/iceberg-demo/trino/app/helmrelease.yaml`
   - `kubernetes/apps/iceberg-demo/trino/validation.sql`

Use `mise exec --` for cluster commands. In the current checkout,
`KUBECONFIG=./kubeconfig` is the equivalent explicit form.

## Data-access safety

- Read-only inspection and queries are the default.
- Never print, paste, or log `AWS_ACCESS_KEY_ID` or
  `AWS_SECRET_ACCESS_KEY` values.
- Spark writes change Iceberg snapshots. Run the fixture or any write only
  with explicit operator approval.
- Trino `SELECT`, `SHOW`, and `DESCRIBE` queries are safe; avoid `DROP`,
  `DELETE`, `INSERT`, `MERGE`, or `ALTER` unless the operator explicitly asks.
- Obtain explicit operator approval before `kubectl exec` or a localhost-only
  port-forward, and close the port-forward during cleanup. Do not create an
  Ingress, HTTPRoute, LoadBalancer, or public DNS record for this demo.
- Preserve unrelated dirty-worktree changes when editing access code or docs.

## Table contract

### `iceberg.logs.normalized`

```text
event_id string
ts timestamp
service string
level string
message string
event_date date
```

- Location: `s3://iceberg-warehouse/logs/normalized`
- Partitioning: `event_date`
- Input is deduplicated by `event_id`.
- Spark updates existing IDs with `MERGE` and inserts new IDs.

### `iceberg.logs.hourly`

```text
hour timestamp
service string
level string
event_count bigint
```

- Location: `s3://iceberg-warehouse/logs/hourly`
- Partitioning: `day(hour)`
- It retains bounded `DELETE` followed by `INSERT` through the platform
  migration. A transformed-partition `MERGE` remains a separate experiment.
- The two table writes are not one atomic transaction.

## Trino access

Trino is the simplest read path because the coordinator already has the
warehouse credentials and catalog configuration injected by ESO.

### In-cluster CLI

First verify that the release and pods are healthy:

```sh
mise exec -- flux get hr -n iceberg-demo trino
mise exec -- kubectl -n iceberg-demo get pods -l app.kubernetes.io/instance=trino
```

Run a read-only query from the coordinator:

```sh
mise exec -- kubectl -n iceberg-demo exec deploy/trino-coordinator -- \
  /usr/bin/trino --server http://localhost:8080 --user validation \
  --output-format TSV_HEADER --execute \
  "SELECT service, level, sum(event_count) AS events \
   FROM iceberg.logs.hourly \
   GROUP BY service, level \
   ORDER BY service, level"
```

Run the deterministic acceptance query:

```sh
mise exec -- kubectl -n iceberg-demo exec deploy/trino-coordinator -- \
  /usr/bin/trino --server http://localhost:8080 --user validation \
  --output-format TSV_HEADER --execute \
  "SELECT (SELECT count(*) FROM iceberg.logs.normalized) AS normalized_count, \
   (SELECT count(*) FROM iceberg.logs.hourly) AS hourly_count, \
   (SELECT coalesce(sum(event_count), 0) FROM iceberg.logs.hourly) AS hourly_event_count_sum"
```

Expected result:

```text
normalized_count  hourly_count  hourly_event_count_sum
5                 5             5
```

### Laptop CLI through a port-forward

With operator approval for the local connection:

```sh
mise exec -- kubectl -n iceberg-demo port-forward svc/trino 18082:8080
mise exec -- trino --server http://127.0.0.1:18082 --user validation
```

The Trino server retains its ESO-backed catalog credentials; the local CLI
does not need the secret values.

### Maintained read-only checks

Use the repository command for the standard counts, table definitions, and
snapshot checks. It verifies the Anton target before one fixed `SELECT` or
`SHOW` query. It accepts no arbitrary SQL.

```sh
mise exec -- task airflow:trino-summary
mise exec -- task airflow:trino-contract
mise exec -- task airflow:trino-snapshots
```

Obtain approval before this coordinator `exec`. Keep its JSON output with the
related Workflow Run or Spark Attempt evidence.

### Schema and location checks

```sql
SHOW SCHEMAS FROM iceberg;
SHOW TABLES FROM iceberg.logs;
SHOW COLUMNS FROM iceberg.logs.normalized;
SHOW COLUMNS FROM iceberg.logs.hourly;
SHOW CREATE TABLE iceberg.logs.normalized;
SHOW CREATE TABLE iceberg.logs.hourly;
```

The `SHOW CREATE TABLE` output should report the two warehouse locations and
partitioning listed above.

### Deterministic hourly rows

```sql
SELECT hour, service, level, event_count
FROM iceberg.logs.hourly
ORDER BY hour, service, level;
```

Expected rows are:

```text
2026-08-06 10:00:00 UTC | api    | INFO  | 1
2026-08-06 10:00:00 UTC | api    | WARN  | 1
2026-08-06 11:00:00 UTC | worker | ERROR | 1
2026-08-06 11:00:00 UTC | worker | INFO  | 1
2026-08-06 12:00:00 UTC | api    | INFO  | 1
```

## Spark access

Airflow-created `SparkApplication` resources own the current shadow workflow.
The Flux-owned legacy CronJob remains authoritative until approved cutover.

Use `airflow-spark-lakehouse` before any Spark run, retry, or writer change.
For legacy read-only inspection, require both submission and driver results:

```sh
mise exec -- kubectl -n iceberg-demo get pods -l spark-role=driver -o wide
mise exec -- kubectl -n iceberg-demo logs pod/<driver-name> --all-containers=true \
  | rg 'expected normalized|expected hourly|ERROR|Exception'
```

### Spark catalog settings

For an approved ad hoc Spark reader using the pinned Spark image, configure
the same catalog and environment-backed credentials as the fixture:

```python
import os
from pyspark.sql import SparkSession

spark = (
    SparkSession.builder
    .config("spark.sql.catalog.lake", "org.apache.iceberg.spark.SparkCatalog")
    .config("spark.sql.catalog.lake.catalog-impl", "org.apache.iceberg.rest.RESTCatalog")
    .config("spark.sql.catalog.lake.uri", "http://seaweedfs-iceberg.storage.svc.cluster.local:8181")
    .config("spark.sql.catalog.lake.warehouse", "s3://iceberg-warehouse")
    .config("spark.sql.catalog.lake.io-impl", "org.apache.iceberg.aws.s3.S3FileIO")
    .config("spark.sql.catalog.lake.s3.endpoint", "http://seaweedfs-s3.storage.svc.cluster.local:8333")
    .config("spark.sql.catalog.lake.s3.path-style-access", "true")
    .config("spark.sql.catalog.lake.s3.region", "us-east-1")
    .config(
        "spark.sql.catalog.lake.credential",
        f"{os.environ['AWS_ACCESS_KEY_ID']}:{os.environ['AWS_SECRET_ACCESS_KEY']}",
    )
    .getOrCreate()
)
```

The credential is exchanged at the SeaweedFS OAuth endpoint. Keep it in the
Spark runtime configuration and never print it. Read the tables with:

```python
spark.table("lake.logs.normalized").show(truncate=False)
spark.table("lake.logs.hourly").orderBy("hour", "service", "level").show()
```

Use the committed Airflow DAG and Spark runtime for current shadow work. Keep
the legacy transform only for rollback until the cutover observation gate passes.

## Cross-engine comparison

Use the same predicate in both engines and compare values, not formatting:

```sql
SELECT count(*) AS row_count FROM iceberg.logs.normalized;
SELECT count(*) AS row_count FROM iceberg.logs.hourly;
SELECT coalesce(sum(event_count), 0) AS event_count FROM iceberg.logs.hourly;
```

Deterministic fixture acceptance requires Spark output of `5 / 5` followed by
Trino output of `5 / 5 / 5`. Loki-source runs use their retained window counts.
If Trino can read the table but Spark cannot, inspect Spark's REST
credential and catalog URI first. If Spark succeeds but Trino cannot read,
inspect the Trino catalog file, worker environment, and S3 endpoint.

## Data-access troubleshooting

- `401` or `403` from the REST catalog: check ESO status and the warehouse
  identity. It needs ordinary S3 warehouse actions plus
  `s3tables:*:iceberg-warehouse`.
- `not authorized to create namespace`: the generated Seaweed S3 Deployment
  may have started before the refreshed Secret was mounted. With approval,
  restart it, then verify a request log contains the S3 Tables action.
- `NoSuchNamespace` or `table not found`: confirm the `lake`/`iceberg` catalog,
  `logs` namespace, and `s3://iceberg-warehouse` warehouse spelling. Do not
  create a second catalog to work around a routing error.
- S3 `AccessDenied` after catalog authentication: distinguish catalog OAuth
  authorization from direct S3 file access and verify the warehouse endpoint,
  path-style setting, region, and credentials.
- Spark submission says `Complete` but the driver is `Error`: treat the
  driver as authoritative and inspect its logs.
- Non-fatal `RESTMetricsReporter` `Path not found` warnings do not invalidate
  a run when the driver succeeds and Trino reads the expected rows.

## Report format

```text
Status: passed | failed | blocked
Engine: Spark | Trino | both
Catalog: <URI and warehouse, never credentials>
Query/write: <exact command or SQL>
Evidence: <driver phase, row counts, schemas, partitions, locations>
Next step: <safe read-only follow-up or explicit approval needed>
```
