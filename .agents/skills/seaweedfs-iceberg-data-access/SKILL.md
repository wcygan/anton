---
name: seaweedfs-iceberg-data-access
description: >-
  Read and validate Anton's SeaweedFS Iceberg tables through Spark and Trino.
  Use for Spark catalog configuration, Iceberg table reads and writes, Trino
  SQL, cross-engine comparisons, table schemas and locations, or data-access
  troubleshooting in the internal lakehouse demo.
---

# SeaweedFS Iceberg Data Access

This skill covers the data plane for Anton's internal SeaweedFS Iceberg demo.
Use `seaweedfs-iceberg-lakehouse` for deployment, Flux, credentials, Harbor,
reconciliation, and teardown operations.

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

The demo is internal and time-boxed for review on 2026-08-20. Never expose the
catalog or S3 endpoint publicly, and never add a second catalog service.

## Read first

1. Read repository `AGENTS.md`.
2. Read `context/adrs/0031-adopt-seaweedfs-iceberg-log-demo.md` for the
   architectural contract.
3. Read `context/plans/0020-implement-seaweedfs-iceberg-log-lakehouse.md` for
   current acceptance evidence.
4. Read `docs/docs/notes/seaweedfs-iceberg-log-lakehouse.md` for the table
   layout and known limitations.
5. Read the source configuration in:
   - `images/iceberg-log-spark/transform.py`
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
- It is rebuilt with bounded `DELETE` followed by `INSERT` because the pinned
  Spark 3.5.3/Iceberg 1.5.2 combination has a transformed-partition `MERGE`
  planner failure.
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
trino --server http://127.0.0.1:18082 --user validation
```

The Trino server retains its ESO-backed catalog credentials; the local CLI
does not need the secret values.

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

Spark is deployed as native Kubernetes submission, not as a notebook or a
long-running Spark service. The Flux-owned CronJob is the canonical writer:

```sh
mise exec -- kubectl -n iceberg-demo create job \
  --from=cronjob/iceberg-log-spark iceberg-log-spark-manual-<timestamp>
```

Require both the submission Job and the driver result. A submission Job can
finish even when the driver failed, so inspect the driver explicitly:

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

For the committed fixture, use the existing
`images/iceberg-log-spark/transform.py` and CronJob rather than inventing a
second credential or warehouse configuration.

## Cross-engine comparison

Use the same predicate in both engines and compare values, not formatting:

```sql
SELECT count(*) AS row_count FROM iceberg.logs.normalized;
SELECT count(*) AS row_count FROM iceberg.logs.hourly;
SELECT coalesce(sum(event_count), 0) AS event_count FROM iceberg.logs.hourly;
```

Acceptance requires Spark driver output of `5 / 5` followed by Trino output of
`5 / 5 / 5`. If Trino can read the table but Spark cannot, inspect Spark's REST
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
