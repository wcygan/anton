---
name: seaweedfs-iceberg-lakehouse
description: >-
  Operate Anton's SeaweedFS and Iceberg lakehouse data path. Use for storage,
  catalog service, legacy fixture deployment, Harbor image handoff, ESO
  prerequisites, infrastructure validation, or storage cleanup.
---

# SeaweedFS Iceberg Lakehouse

Use this skill for the SeaweedFS, Iceberg, Trino, and Harbor data path retained
by ADR 0033. ADR 0031 and Plan 0020 remain historical storage evidence.

Use `seaweedfs-iceberg-data-access` for table schemas, locations, reads,
writes, and cross-engine queries. Use `airflow-spark-lakehouse` for Workflow
Runs, Spark Attempts, shadow gates, writer cutover, retry, and cancellation.

```text
1Password -> ESO -> SeaweedFS S3 identities
                           |
SeaweedFS S3 :8333 <--------+--------> Iceberg REST :8181
       |                                  |
       +-- iceberg-raw                    +-- iceberg-warehouse S3 Table bucket
                                              |
            Airflow -> SparkApplication ----> logs.normalized / logs.hourly
                          legacy CronJob -----^ until approved cutover
                                              |
                                      Trino 480 reads the same tables
```

This is a learning lakehouse, not a production service. Keep it internal and
review the Airflow and Spark platform by 2026-09-10 under ADR 0033.

## Read first

1. Read the repository `AGENTS.md` and verify the Kubernetes context.
2. Read `context/adrs/0033-adopt-airflow-spark-operator-lakehouse.md` as the
   current architectural authority.
3. Read `context/plans/0023-roll-out-airflow-spark-lakehouse.md` for current
   writer ownership and migration state.
4. Read ADR 0031 and Plan 0020 for the underlying storage history.
5. Read `docs/docs/notes/seaweedfs-iceberg-log-lakehouse.md` for the current
   validation evidence and cleanup procedure.
6. When changing manifests, read `kubernetes/apps/AGENTS.md` and
   `kubernetes/apps/storage/AGENTS.md`.

Use the repository's `mise exec --` wrapper for normal cluster commands. In
this checkout, `KUBECONFIG=./kubeconfig` is the equivalent explicit form.

## Safety boundaries

- Read-only inspection is the default: `kubectl get`, `describe`, `logs`, and
  `flux get`. Treat `exec` and `port-forward` as live mutations that require
  explicit operator approval and cleanup.
- Ask for explicit operator approval before `flux reconcile`, `rollout
  restart`, `kubectl create job`, bucket changes, namespace deletion,
  credential rotation, or other live mutations.
- Never print Secret data or credential values. Use ESO status, Secret
  `describe`, and key lengths only.
- Harbor may be reached from a laptop through a temporary Kubernetes
  port-forward. Never commit the tunnel or expose Harbor publicly.
- Preserve unrelated dirty-worktree changes and stage only lakehouse files.
- Do not delete old evidence until the operator has recorded the run and the
  review decision is known.

## Source files and contracts

- Seaweed CR and catalog argument: `kubernetes/apps/storage/seaweedfs-config/app/seaweed.yaml`
- Catalog Service: `kubernetes/apps/storage/seaweedfs-config/app/iceberg-service.yaml`
- ESO identities and permissions: `kubernetes/apps/storage/seaweedfs-config/app/externalsecret.yaml`
- Shared bucket provisioner: `kubernetes/apps/storage/seaweedfs-config/app/buckets-cronjob.yaml`
- Provisioning implementation: `kubernetes/apps/storage/seaweedfs-config/app/provision-buckets.sh`
- Raw S3 smoke test: `kubernetes/apps/storage/seaweedfs-config/app/lakehouse-s3-smoke-job.yaml`
- Legacy Spark CronJob and RBAC: `kubernetes/apps/iceberg-demo/spark-fixture/app/`
- Airflow DAG and adapter: `images/airflow-runtime/`
- Spark runtime image: `images/spark-runtime/`
- Shadow SparkApplication: `kubernetes/apps/lakehouse/shadow-fixture/app/`
- Spark control plane: `kubernetes/apps/spark-system/spark-operator/app/`
- Trino HelmRelease and query: `kubernetes/apps/iceberg-demo/trino/`
- Legacy Spark image: `images/iceberg-log-spark/`

The warehouse identity needs both ordinary S3 bucket actions and the
bucket-scoped SeaweedFS S3 Tables action `s3tables:*:iceberg-warehouse`.
The Seaweed operator does not automatically roll the generated S3 Deployment
when the mounted credential Secret changes; restart that Deployment only with
approval, then verify the new action list in its startup/request logs.

## Health pulse

Run this before interpreting a failed fixture or query:

```sh
mise exec -- kubectl config current-context
mise exec -- flux get ks -A | rg 'seaweedfs-config|iceberg-demo|spark-fixture|trino'
mise exec -- flux get hr -A | rg 'trino'
mise exec -- kubectl -n storage get seaweed,deploy,svc -l app.kubernetes.io/instance=seaweedfs -o wide
mise exec -- kubectl -n storage get externalsecret seaweedfs-s3-config
mise exec -- kubectl -n iceberg-demo get deploy,pods,cronjob
```

The expected steady state is Flux Ready for `seaweedfs-config`, `spark-fixture`,
and `trino`; an internal `seaweedfs-iceberg` Service on 8181; two Ready Trino
pods; and an ESO `Ready=True` condition for the storage Secret.

## Credential and Harbor prerequisites

The 1Password item is `seaweedfs-iceberg` in vault `anton` with these
concealed fields:

```text
raw-access-key
raw-secret-key
warehouse-access-key
warehouse-secret-key
```

Do not retrieve or echo the values. Verify only that ESO is synced. Images are
pinned to Harbor digests in the manifests.

Read [harbor-image-handoff.md](references/harbor-image-handoff.md) before an
image build, archive transfer, local port-forward, or Harbor push.

## Ordered validation flow

Follow the phases in order. Do not skip the storage gate.

### 1. Storage and catalog

```sh
mise exec -- flux get ks -n storage seaweedfs-config
mise exec -- kubectl -n storage get svc seaweedfs-iceberg
mise exec -- kubectl -n storage get cronjob seaweedfs-buckets-ensure
mise exec -- kubectl -n storage get jobs \
  -l batch.kubernetes.io/cronjob-name=seaweedfs-buckets-ensure
mise exec -- kubectl -n storage get job seaweedfs-lakehouse-s3-smoke
```

The bucket job must create or find ordinary `iceberg-raw` and the SeaweedFS S3
Table bucket `iceberg-warehouse`. The smoke job must verify scoped raw
identity write/read/delete. An ordinary bucket named `iceberg-warehouse` is a
collision and must not be replaced automatically.

### 2. Legacy Spark fixture

The legacy CronJob remains the authoritative writer until Ticket 09 completes.
Use `airflow-spark-lakehouse` for shadow or Airflow-owned runs.

After approval for a legacy live run, create a unique Job from the Flux-owned CronJob:

```sh
mise exec -- kubectl -n iceberg-demo create job \
  --from=cronjob/iceberg-log-spark iceberg-log-spark-manual-<timestamp>
```

Do not treat the submission Job's `Complete` condition as sufficient. Inspect
the Spark driver pod and require `Succeeded`:

```sh
mise exec -- kubectl -n iceberg-demo get pods -l spark-role=driver -o wide
mise exec -- kubectl -n iceberg-demo logs pod/<driver-name> --all-containers=true \
  | rg 'expected normalized|expected hourly|ERROR|Exception'
```

Acceptance output is:

```text
expected normalized rows=5 actual=5
expected hourly rows=5 actual=5
```

The normalized table is deduplicated by `event_id`. The migration contract
retains the hourly delete and insert through cutover. Test transformed-partition
`MERGE` in a separate experiment. The two writes are not one atomic transaction.

### 3. Trino cross-engine query

Run the repeatable query from `kubernetes/apps/iceberg-demo/trino/validation.sql`
inside the coordinator, or use an approved local port-forward. A direct
coordinator check is:

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

Also verify the deterministic hourly rows and table contracts:

```sql
SHOW COLUMNS FROM iceberg.logs.normalized;
SHOW COLUMNS FROM iceberg.logs.hourly;
SHOW CREATE TABLE iceberg.logs.normalized;
SHOW CREATE TABLE iceberg.logs.hourly;
```

Expected locations are `s3://iceberg-warehouse/logs/normalized` and
`s3://iceberg-warehouse/logs/hourly`; expected partitions are `event_date`
and `day(hour)` respectively.

### 4. Rerun and record

Run the identical fixture a second time with a new Job name. Counts should
remain five in both tables. The rerun adds Iceberg snapshots even when the
final row set is unchanged. Record Flux revision, driver names and output,
Trino output, and any non-fatal REST metrics warnings in the active ticket and
Plan 0023. Keep Plan 0020 as historical evidence.

## Failure triage

- `exec format error`: the Harbor image architecture is wrong; rebuild and
  repin the image for `linux/amd64`.
- Flux strict substitution rejects `${ENV:...}`: escape runtime placeholders
  as `$${ENV:...}` in the HelmRelease source.
- Trino startup rejects memory defaults: keep coordinator/worker heaps and
  query memory bounded to the demo's explicit values.
- Spark driver says `not authorized to create namespace in this bucket`: verify
  `s3tables:*:iceberg-warehouse` is present in the mounted policy, wait for ESO
  refresh, and restart the generated Seaweed S3 Deployment with approval.
- Spark driver cleanup reports `deletecollection` forbidden: verify the
  namespace-scoped Spark Role includes `deletecollection` and PVC access.
- REST metrics `Path not found` warnings are non-fatal when table writes,
  driver success, and Trino queries pass.

## Cleanup and stop conditions

Stop when the requested storage and data-path checks pass. Route workflow
acceptance and writer changes to `airflow-spark-lakehouse`.

For teardown, retain plan evidence and stop writers before resource removal.
Namespace, bucket, and credential removal require separate operator approval.
SeaweedFS uses `defaultReplication: "000"`; learning data has no independent
Seaweed durability guarantee.

## Report format

Return:

```text
Status: passed | failed | blocked
Flux: <Kustomization/HelmRelease status and revision>
Storage: <catalog Service, ESO, bucket and smoke evidence>
Spark: <driver pod, terminal phase, expected/actual counts>
Trino: <query output, schemas, partitions, locations>
Changes: <paths and commit, if any>
Residual risks: <short list>
Next step: <one safe follow-up or approval-only action>
```
