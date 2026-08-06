---
title: SeaweedFS Iceberg log lakehouse demo
---

# SeaweedFS Iceberg log lakehouse demo

This is a time-boxed internal learning demo for review on 2026-08-20. It
keeps SeaweedFS as both the S3 warehouse and the built-in Iceberg REST catalog;
it does not add Polaris, Nessie, Hive Metastore, Kafka, Flink, Spark Operator,
Airflow, or Dagster.

## Source of truth

- ADR: `context/adrs/0031-adopt-seaweedfs-iceberg-log-demo.md`
- Plan: `context/plans/0020-implement-seaweedfs-iceberg-log-lakehouse.md`
- Seaweed CR: `kubernetes/apps/storage/seaweedfs-config/app/seaweed.yaml`
- Iceberg Service: `kubernetes/apps/storage/seaweedfs-config/app/iceberg-service.yaml`
- Spark fixture: `kubernetes/apps/iceberg-demo/spark-fixture/`
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

## Phase 1–3 layout

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

## Build and rebuild prerequisites

The external prerequisites are satisfied for the current time-boxed demo: the
`seaweedfs-iceberg` 1Password item is synced by ESO, both pinned Harbor images
are live, and Flux has reconciled the storage, Spark, and Trino apps. The
following commands remain the reproducible rebuild handoff; credentials stay
out of Git.

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

After the storage Secret and both buckets are Ready, trigger the fixture
without waiting for its hourly schedule:

```sh
kubectl -n iceberg-demo create job --from=cronjob/iceberg-log-spark iceberg-log-spark-manual
kubectl -n iceberg-demo wait --for=condition=complete job/iceberg-log-spark-manual --timeout=15m
kubectl -n iceberg-demo logs job/iceberg-log-spark-manual --all-containers
```

Delete that uniquely named Job before another manual run, or use a new name;
the CronJob itself remains the Flux-owned schedule.

## Validation contract

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

The current `MERGE` plus bounded hourly rebuild intentionally records
additional Iceberg snapshots on each successful rerun even though the final
row set is deduplicated. The Loki snapshot CronJob remains optional and is
deferred until a later review gate.

## Cleanup and risks

Cleanup is operator-only: suspend the demo Kustomizations, retain the
acceptance evidence, then remove the `iceberg-demo` namespace, the two
dedicated buckets, and the 1Password identities if the 2026-08-20 review
rejects the experiment. SeaweedFS uses `defaultReplication: "000"`, so demo
data is disposable and does not receive an independent Seaweed durability
guarantee. The generated Seaweed S3 Deployment also needs an explicit restart
after changes to its credential Secret; the operator does not automatically
roll that generated Deployment.
