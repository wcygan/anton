---
title: SeaweedFS Iceberg log lakehouse demo
---

# SeaweedFS Iceberg log lakehouse demo

> This page preserves the ADR 0031 baseline. ADR 0033 superseded that design.
> ADR 0039 retains the current Airflow and Spark learning platform.
> Commands under `iceberg-demo` describe the legacy writer, except Trino.

The original demo was a time-boxed internal learning task. It kept SeaweedFS
as the S3 warehouse and the built-in Iceberg REST catalog. Airflow now owns the
workflow, and Spark remains the only Iceberg writer.

## Source of truth

- Current decision: `context/adrs/0039-retain-airflow-spark-learning-platform.md`
- Completed migration: `context/plans/0023-roll-out-airflow-spark-lakehouse.md`
- Historical ADR: `context/adrs/0031-adopt-seaweedfs-iceberg-log-demo.md`
- Historical plan: `context/plans/0020-implement-seaweedfs-iceberg-log-lakehouse.md`
- Seaweed CR: `kubernetes/apps/storage/seaweedfs-config/app/seaweed.yaml`
- Iceberg Service: `kubernetes/apps/storage/seaweedfs-config/app/iceberg-service.yaml`
- Airflow DAG: `images/airflow-runtime/dags/airflow_spark_lakehouse.py`
- Historical Spark fixture: `kubernetes/apps/iceberg-demo/spark-fixture/`
- Trino catalog: `kubernetes/apps/iceberg-demo/trino/`

## Phase 0 evidence

The pinned SeaweedFS image is `chrislusf/seaweedfs:4.40`; the operator
HelmRelease is chart `0.1.36` (live operator image `1.0.33`). The live CRD
accepts `spec.s3.extraArgs`, but the generated S3 Service only publishes
8333. SeaweedFS 4.40's `weed s3 -h` exposes `-port.iceberg` with default port
8181. The declarative overlay therefore adds `-port.iceberg=8181` and a
Flux-managed internal `ClusterIP` Service on 8181 selecting the generated S3
pods.

The first disposable integration test also established two catalog-specific
requirements: `iceberg-warehouse` must be a SeaweedFS S3 Table bucket rather
than an ordinary S3 bucket, and Spark/Trino must exchange their warehouse
credential at `/v1/oauth/tokens`. The bucket provisioner now uses the S3
Tables API and the engine configurations use OAuth2; ordinary-bucket
collisions fail closed.

Read-only checks used:

```sh
mise exec -- kubectl get nodes -o wide
mise exec -- kubectl -n storage get seaweed seaweedfs -o yaml
mise exec -- kubectl -n storage get deploy,svc -l app.kubernetes.io/instance=seaweedfs -o wide
mise exec -- kubectl -n storage exec <s3-pod> -- weed s3 -h
mise exec -- kubectl -n storage exec <s3-pod> -- weed version
```

At inspection time all Seaweed components were Ready (3 masters, 3 volumes,
2 filers, 2 S3 pods), S3 `/healthz` returned 200, 11 volume slots were free,
and the three 100 Gi PVCs had roughly 288 GiB free. Node usage was 10–11% CPU
and 12–15% memory. These are point-in-time observations, not reservations.

## Current capacity policy

On 2026-08-21, all 36 logical volume slots were allocated. The three 120 GiB
PVCs still had byte capacity. The warning was slot exhaustion, not disk
exhaustion.

The maintenance change separated these two capacity limits:

| Control | Before | Current policy | Purpose |
| --- | --- | --- | --- |
| Growth batch | Seven volumes | One volume | Avoid unused sparse slots. |
| Slots per server | 12 | 20 | Provide 60 cluster slots. |
| New volume size | 10 GB | 5 GB | Allow smaller future allocation units. |
| PVC size | 120 GiB | 120 GiB | Preserve existing Longhorn storage. |

The current topology has 36 used slots and 24 free slots. Each server has
12 used slots and eight free slots. Existing volume files were not resized.

This change was useful because byte metrics alone hid the limiting resource.
The master topology showed `36/36` slots before any PVC was full.

Future capacity reviews must record both limits. Check Longhorn bytes, logical
slots, per-node balance, and read-only state before a maintenance change.

## Volume-server maintenance

A volume pod restart can change its address. The S3 gateways can retain the old
address after the master topology is correct.

The 2026-08-21 rollout reproduced this behavior. S3 requests retried old volume
IPs until the gateways restarted. One Spark run overlapped the restart and
failed before its first Iceberg commit.

Use this order for future maintenance:

1. Stop active writers and confirm that no writer Lease exists.
2. Record master topology, PVC state, and Longhorn health.
3. Reconcile the SeaweedFS policy and wait for stable volume pods.
4. Compare master topology with S3 errors and old volume addresses.
5. Restart only the S3 gateways when their cache is stale.
6. Run a fresh S3 write, read, and delete smoke test.
7. Run one authoritative Airflow workflow and compare Iceberg snapshots.

If a writer fails, compare pre-run and post-run snapshots before retrying.
An unchanged snapshot set proves that the failed run made no table commit.

## Historical Phase 1–3 layout

The storage config provisions dedicated `iceberg-raw` and
`iceberg-warehouse` buckets and adds least-privilege Seaweed identities. The
bucket CronJob is idempotent; the one-shot
`seaweedfs-lakehouse-s3-smoke` Job writes, reads, compares, and deletes a
unique object using the scoped raw identity. The Spark CronJob reads the
deterministic JSONL fixture, deduplicates by `event_id`, and uses Iceberg
`MERGE` for the normalized table. The tiny hourly derived table is rebuilt
with a bounded delete followed by insert because the Spark 3.5.3/Iceberg
1.5.2 planner fails on a `MERGE` against its transformed `days(hour)`
partition. The final result is deterministic and idempotent, but the two
writes are not one atomic transaction. It maintains:

- `logs.normalized` — five unique fixture events
- `logs.hourly` — five `(hour, service, level)` aggregate rows

The same disposable SeaweedFS 4.40 integration was run twice with the local
Spark image. Direct Iceberg queries reported `normalized 5` and `hourly 5`
after each run. The runtime logged non-fatal `RESTMetricsReporter` path-not-
found warnings for the optional metrics route; no table write or read failed.

A disposable Trino 480 container, configured with the same REST catalog,
`fs.native-s3.enabled=true`, and warehouse, then returned
`normalized_count=5`, `hourly_count=5`, and `hourly_event_count_sum=5` through
the Trino HTTP statement API. Trino 480 rejects the newer `fs.s3.enabled`
switch as unused, so the manifest intentionally keeps the versioned native
filesystem key. This proves the engine configuration shape locally; it is not
live-cluster acceptance.

The Trino HelmRelease uses the official chart (`1.42.2`, Trino image `480`),
one bounded worker, an internal `ClusterIP`, and an Iceberg REST catalog aimed
at `http://seaweedfs-iceberg.storage.svc.cluster.local:8181`.

## Historical build and rebuild prerequisites

At the legacy demo closeout, the `seaweedfs-iceberg` 1Password item was synced.
Both pinned Harbor images were live. Flux had reconciled storage, Spark, and
Trino. These commands preserve that historical rebuild handoff.

1. Keep the 1Password item `seaweedfs-iceberg` in vault `anton` with
   `raw-access-key`, `raw-secret-key`, `warehouse-access-key`, and
   `warehouse-secret-key`.
2. Build the image from `images/iceberg-log-spark/Dockerfile`, push it to
   Harbor project `library`, and pin the returned digest in
   `kubernetes/apps/iceberg-demo/spark-fixture/app/job.yaml`.
3. Build Trino for the cluster architecture (`linux/amd64`), push it to
   Harbor, and pin the returned digest in
   `kubernetes/apps/iceberg-demo/trino/app/helmrelease.yaml`.
4. Review the Flux diff before repeating a live reconcile. Harbor was reached
   from this laptop through a temporary Kubernetes port-forward; the tunnel
   is not part of the committed configuration.

The image handoff can use these operator-run commands from a host that can
reach Harbor (authenticate with the existing Harbor robot/user; do not commit
the credentials):

```sh
docker build --platform linux/amd64 \
  -t 192.168.1.106/library/iceberg-log-spark:0.1.0 \
  -f images/iceberg-log-spark/Dockerfile .
docker push 192.168.1.106/library/iceberg-log-spark:0.1.0
docker buildx build --platform linux/amd64 --provenance=false --sbom=false \
  --file /tmp/trino-amd64/Dockerfile \
  --tag 192.168.1.106/library/trino:480-amd64 \
  --push /tmp/trino-amd64
crane digest --insecure 192.168.1.106/library/iceberg-log-spark:0.1.0
crane digest --insecure 192.168.1.106/library/trino:480-amd64
```

Replace both Spark markers and the Trino marker with the returned Harbor
digests, then stop for review before pushing or reconciling Git.

The live storage smoke test was run with:

```sh
kubectl -n storage delete job seaweedfs-lakehouse-s3-smoke --ignore-not-found
flux reconcile kustomization seaweedfs-config -n storage
```

The legacy Spark CronJob no longer exists. Use the
`airflow-spark-lakehouse` skill for an authorized Workflow Run.

## Historical validation contract

Local, non-mutating checks:

```sh
find kubernetes/apps/iceberg-demo kubernetes/apps/storage/seaweedfs-config/app \
  -type f \( -name '*.yaml' -o -name '*.yml' \) -print0 \
  | xargs -0 -n1 ruby -e 'require "yaml"; YAML.load_stream(File.read(ARGV.fetch(0)))'
python3 -m py_compile images/iceberg-log-spark/transform.py
git diff --check
```

The live acceptance run used two one-off Spark Jobs and the repeatable query
file `kubernetes/apps/iceberg-demo/trino/validation.sql` against the internal
coordinator:

```sql
SELECT count(*) FROM iceberg.logs.normalized; -- 5
SELECT count(*) FROM iceberg.logs.hourly;     -- 5
SELECT sum(event_count) FROM iceberg.logs.hourly; -- 5
```

Observed live evidence:

- Spark driver 1: `Succeeded`, `expected normalized rows=5 actual=5`,
  `expected hourly rows=5 actual=5`.
- Spark driver 2 (identical input): `Succeeded`, the same two row-count lines.
- Trino aggregate: `normalized_count=5`, `hourly_count=5`,
  `hourly_event_count_sum=5`.
- Trino DDL: `logs.normalized` is partitioned by `event_date` and located at
  `s3://iceberg-warehouse/logs/normalized`; `logs.hourly` is partitioned by
  `day(hour)` and located at `s3://iceberg-warehouse/logs/hourly`.

The `MERGE` plus bounded hourly rebuild records more Iceberg snapshots after
each successful run. The final row set remains deduplicated.

## Historical cleanup and current risks

ADR 0039 retained the platform without a fixed review date. The old
2026-08-20 cleanup gate no longer applies.

SeaweedFS uses `defaultReplication: "000"`. Longhorn owns storage durability,
and SeaweedFS does not keep an independent data copy.

The generated S3 Deployment does not roll after credential changes. It can
also keep stale volume addresses after volume pod changes.

Restart the S3 gateways only with approval and after all active writers stop.
Then run the storage smoke test and one authoritative workflow.
