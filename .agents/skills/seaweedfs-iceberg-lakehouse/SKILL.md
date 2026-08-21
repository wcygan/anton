---
name: seaweedfs-iceberg-lakehouse
description: >-
  Operate Anton's SeaweedFS and Iceberg lakehouse data path. Use for volume
  capacity, topology maintenance, S3 cache faults, catalog service, Harbor
  image handoff, ESO prerequisites, validation, or storage cleanup.
---

# SeaweedFS Iceberg Lakehouse

Use this skill for the SeaweedFS, Iceberg, Trino, and Harbor data path retained
by ADR 0039. ADR 0031 and Plan 0020 remain historical storage evidence.

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
                                              |
                                      Trino 480 reads the same tables
```

This is an open-ended learning lakehouse, not a production service. Keep it
internal. ADR 0039 defines no fixed review date or production service level.

## Read first

1. Read the repository `AGENTS.md` and verify the Kubernetes context.
2. Read `context/adrs/0039-retain-airflow-spark-learning-platform.md` for the
   current platform decision.
3. Read `context/plans/0023-roll-out-airflow-spark-lakehouse.md` for the
   completed writer cutover.
4. Read ADR 0033 for architecture. Read ADR 0031 and Plan 0020 for storage
   history.
5. Read `docs/docs/notes/seaweedfs-iceberg-log-lakehouse.md` for storage
   evidence and the maintenance procedure.
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
- Retain old evidence until the operator records the run and authorizes
  removal.

## Source files and contracts

- Seaweed CR and catalog argument: `kubernetes/apps/storage/seaweedfs-config/app/seaweed.yaml`
- Catalog Service: `kubernetes/apps/storage/seaweedfs-config/app/iceberg-service.yaml`
- ESO identities and permissions: `kubernetes/apps/storage/seaweedfs-config/app/externalsecret.yaml`
- Shared bucket provisioner: `kubernetes/apps/storage/seaweedfs-config/app/buckets-cronjob.yaml`
- Provisioning implementation: `kubernetes/apps/storage/seaweedfs-config/app/provision-buckets.sh`
- Raw S3 smoke test: `kubernetes/apps/storage/seaweedfs-config/app/lakehouse-s3-smoke-job.yaml`
- Airflow DAG and adapter: `images/airflow-runtime/`
- Spark runtime image: `images/spark-runtime/`
- Authoritative credentials: `kubernetes/apps/lakehouse/authoritative-writer/app/`
- Spark control plane: `kubernetes/apps/spark-system/spark-operator/app/`
- Trino HelmRelease and query: `kubernetes/apps/iceberg-demo/trino/`
- Historical Spark fixture: `kubernetes/apps/iceberg-demo/spark-fixture/app/`
- Historical Spark image: `images/iceberg-log-spark/`

The warehouse identity needs both ordinary S3 bucket actions and the
bucket-scoped SeaweedFS S3 Tables action `s3tables:*:iceberg-warehouse`.
The Seaweed operator does not automatically roll the generated S3 Deployment
when the mounted credential Secret changes; restart that Deployment only with
approval, then verify the new action list in its startup/request logs.

## Health pulse

Run this before interpreting a failed fixture or query:

```sh
mise exec -- kubectl config current-context
mise exec -- flux get ks -A | rg 'seaweedfs-config|airflow|authoritative-writer|spark-operator|spark-history|trino'
mise exec -- flux get hr -A | rg 'airflow|spark-operator|trino'
mise exec -- kubectl -n storage get seaweed,deploy,svc -l app.kubernetes.io/instance=seaweedfs -o wide
mise exec -- kubectl -n storage get externalsecret seaweedfs-s3-config
mise exec -- kubectl -n airflow get pods
mise exec -- kubectl -n lakehouse get sparkapplications,pods,leases
mise exec -- kubectl -n iceberg-demo get deploy,pods
```

The expected steady state is Flux Ready for storage, Airflow, Spark Operator,
History Server, authoritative credentials, and Trino. The Iceberg Service uses
8181. The storage Secret has `Ready=True`.

## Capacity and topology

Check physical bytes and logical volume slots separately. Free Longhorn bytes
do not prove that SeaweedFS can allocate another logical volume.

With approval for the read-only `exec`, record the logical topology:

```sh
printf 'volume.list\n' | mise exec -- kubectl -n storage exec -i \
  pod/seaweedfs-master-0 -c master -- weed shell \
  -master=seaweedfs-master-0.seaweedfs-master-peer.storage:9333
```

Record total and per-node volume use, maximum slots, free slots, and read-only
state. Read current policy values from the source `Seaweed` CR.

The policy limits future allocation. It does not resize existing volume files.
Run `kubectl -n storage get pvc` and inspect the matching Longhorn volumes.

## Volume address cache

A volume pod restart can change its address. S3 gateways can retain the old
address after the master topology becomes correct.

Symptoms include `volume N not found`, `unexpected EOF`, or repeated requests
to an old volume IP. Compare the S3 logs with `volume.list` before repair.

Stop active Spark Attempts and confirm that no writer Lease exists. With
approval, restart only the S3 Deployment:

```sh
mise exec -- kubectl -n storage rollout restart deployment/seaweedfs-s3
mise exec -- kubectl -n storage rollout status deployment/seaweedfs-s3 --timeout=10m
```

Do not overlap this restart with an Iceberg writer. The writer can lose its S3
connection while it plans or commits a table change.

After the restart, run a fresh S3 write, read, and delete smoke test. Then use
`airflow-spark-lakehouse` for one authoritative workflow and snapshot check.

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

### 2. Authoritative Spark workflow

Airflow owns the only current writer. Use `airflow-spark-lakehouse` before any
Workflow Run, Spark Attempt, retry, cancellation, or Lease action.

Do not treat submission as success. Require `Succeeded`, `ResourceReleased`,
an empty writer Lease, complete runtime evidence, and Trino validation.

The normalized table uses `MERGE`. The hourly table uses bounded delete and
insert. These two table writes are not one atomic transaction.

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

### 4. Record the result

After storage maintenance, run one exact authoritative Workflow Run. Counts
must remain five in both tables, with an event total of five.

Record Flux revision, Workflow Run, Spark Attempt, state history, Trino output,
and Iceberg snapshots. Keep Plans 0020 and 0023 as historical evidence.

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
