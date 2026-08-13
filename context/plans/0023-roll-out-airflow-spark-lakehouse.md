---
status: In-progress
opened: 2026-08-11
closed: null
affects: all
intent: learning
related-adrs: [0033, 0035]
review-by: 2026-09-10
---

# 0023 — Roll out Airflow Spark lakehouse

> Migrate Anton's lakehouse to Airflow and Apache Spark Operator through a shadow-first, evidence-gated cutover.

## Goal

Anton runs the complete lakehouse workflow through Airflow-created Apache `SparkApplication` resources. Spark remains the only Iceberg writer. Trino validates each run without write access. Runtime logs survive short-lived pods in Loki, while Spark event logs remain available through History Server. A shadow deployment proves the full path before one controlled writer cutover.

## Acceptance criteria

- [ ] Flux owns healthy Airflow, Spark Operator, History Server, and CNPG resources with bounded resources and namespace-scoped access.
- [ ] The selected Spark runtime passes the complete image, Iceberg, catalog, SeaweedFS, Trino, Kubernetes, and classpath matrix.
- [x] Airflow task logs, Loki runtime logs, and Spark History Server pass success, short-life, and pre-commit failure tests.
- [ ] Five shadow runs and 24 authoritative scheduled runs pass without two active writers or an unexplained failure.
- [ ] Rollback, retention, removal, and the 2026-09-10 learning review have retained evidence.
- [ ] Backup and restore pass before authoritative cutover, as required by ADR 0033.

## Tasks

### Phase 0: Freeze contracts and baseline

- [ ] Record all current image digests, table locations, schemas, partitions, snapshots, row counts, and table format versions.
- [ ] Confirm that authoritative tables remain unchanged during every shadow test.
- [ ] Keep the current `logs.hourly` delete-and-insert behavior through cutover.
- [ ] Create a separate experiment for the proposed transformed-partition `MERGE` change.
- [ ] Record the runtime ladder shown below in build and acceptance evidence.

| Priority | Spark Operator | Spark | Iceberg | Control plane |
|---|---:|---:|---:|---|
| Primary | 1.0.0, chart 1.8.0 | 4.1.3 | 1.11.0 | `spark.apache.org/v1` |
| Compatibility | 1.0.0, chart 1.8.0 | 4.0.4 | 1.11.0 | `spark.apache.org/v1` |
| Final fallback | 0.9.0 | 3.5.3 | 1.5.2 | `spark.apache.org` `SparkApplication` |

- [ ] Treat Kubernetes 1.36 as a local Airflow acceptance target, not an upstream support claim.
- [ ] Reject any planned fallback to `KubernetesPodOperator` or direct `spark-submit` orchestration.
- [ ] Capture the accepted learning ceilings shown below.

| Component | Replicas | CPU request | Memory request | CPU limit | Memory limit |
|---|---:|---:|---:|---:|---:|
| Airflow API server | 1 | 100m | 512Mi | 500m | 1Gi |
| Airflow scheduler | 1 | 250m | 768Mi | 1 | 1536Mi |
| Airflow DAG processor | 1 | 100m | 512Mi | 500m | 1Gi |
| Airflow triggerer | 1 | 100m | 512Mi | 500m | 1Gi |
| Airflow task pod | per task | 100m | 256Mi | 500m | 768Mi |
| Spark operator | 1 | 100m | 512Mi | 500m | 1Gi |
| Spark History Server | 1 | 100m | 512Mi | 500m | 1Gi |
| Spark driver | per attempt | 100m | 1Gi | 1 | 1536Mi |
| Spark executor | 1 | 100m | 1Gi | 1 | 1536Mi |
| Airflow CNPG | 1 | 100m | 512Mi | 500m | 1Gi |

- [ ] Measure peak use before increasing a request, limit, or replica count.

### Phase 1: Build immutable runtime images

- [ ] Pin `apache/spark:4.1.3-scala2.13-java21-python3-ubuntu` by digest.
- [ ] Add `iceberg-spark-runtime-4.1_2.13:1.11.0` and matching Hadoop 3.4.2 components.
- [ ] Keep `hadoop-common`, Hadoop clients, and `hadoop-aws` at 3.4.2.
- [ ] Resolve one AWS SDK v2 family for Iceberg S3FileIO and Hadoop S3A.
- [ ] Add the required AWS HTTP client and exclude every competing SDK bundle.
- [ ] Prefer the Hadoop-compatible SDK family if it also supports Iceberg S3FileIO.
- [ ] If selected, prove `iceberg-aws-bundle` works after excluding the competing Hadoop SDK bundle.
- [ ] Emit the dependency tree, JAR inventory, SHA-256 hashes, `hadoop-aws` version, and AWS SDK version.
- [ ] Run a duplicate-class scan and reject incompatible `software.amazon.awssdk` classes.
- [ ] Fail the image build unless Python reports the selected 3.12 release line.
- [ ] Prove Spark 4.1.3, Scala 2.13.x, Java 21, and Python 3.12.x inside driver and executor pods.
- [ ] Prove Iceberg S3FileIO and Hadoop S3A against SeaweedFS from the final image.
- [ ] Prevent Maven, Ivy, or package downloads during workload startup.
- [ ] Build the Airflow 3.2.2 image with Python 3.12 and official constraints.
- [ ] Pin Kubernetes provider 10.21.0 unless a reproducible acceptance regression requires 10.20.0.
- [ ] Bake DAGs, the typed Spark adapter, and tests into the Airflow image.
- [ ] Publish both images to Harbor and record immutable digests.

### Phase 2: Add storage, database, and identity foundations

- [ ] Add Flux-managed `airflow`, `spark-system`, `lakehouse`, and `trino` namespaces.
- [ ] Move Trino 480 from `iceberg-demo` to `trino` without upgrading it.
- [ ] Keep the CNPG operator in `databases` and SeaweedFS in `storage`.
- [ ] Keep the legacy `iceberg-demo` writer available only during shadow testing.
- [ ] Create the Airflow CNPG `Cluster` in `airflow` with one initial instance.
- [x] Configure Longhorn storage and monitoring for Airflow metadata.
- [ ] Configure an independent backup and test restore before authoritative cutover.
- [ ] Deliver database and object-storage credentials through ESO and 1Password.
- [x] Provision ordinary S3 bucket `spark-events` with prefix `events/`.
- [ ] Provision shadow warehouse `s3://iceberg-shadow` and its separate storage identity.
- [x] Create read-only event-log credentials for History Server.
- [x] Keep event-log deletion authority in the storage-owned lifecycle policy.
- [x] Use a SeaweedFS lifecycle rule for 30-day event-log expiry.
- [ ] Keep authoritative warehouse `s3://iceberg-warehouse` unchanged.

### Phase 3: Install the Spark control plane

- [ ] Add Spark Operator chart 1.8.0 and operator 1.0.0 through the standard Flux app pattern.
- [ ] Disable chart ClusterRoles for operator and workload access.
- [ ] Give the operator a namespace Role that watches only `lakehouse`.
- [ ] Start from chart driver permissions and remove unused optional permissions.
- [ ] Add one fixture `SparkApplication` with restart policy `Never`.
- [ ] Set explicit driver and executor heap plus memory overhead.
- [ ] Prove heap, overhead, and native headroom stay below 1536Mi pod limits.
- [ ] Set `resourceRetainPolicy: OnFailure` and `resourceRetainDurationMillis: 86400000`.
- [ ] Set `ttlAfterStopMillis: 604800000` for seven-day application records.
- [ ] Set `spark.kubernetes.executor.deleteOnTermination=false` only if retention testing requires it.
- [x] Add a narrowly scoped executor cleaner only if operator retention is insufficient.
- [x] Add Spark History Server as a normal one-replica Deployment in `lakehouse`.
- [x] Disable History Server service-account token mounting.
- [x] Set `spark.eventLog.enabled=true` and `spark.eventLog.dir=s3a://spark-events/events/`.
- [x] Enable event-log compression and rolling files.
- [x] Disable the History Server cleaner because its storage identity is read-only.

### Phase 4: Install Airflow and the workflow adapter

- [ ] Add Airflow chart 1.22.0 with the pinned custom image and KubernetesExecutor.
- [ ] Run one API server, scheduler, DAG processor, and triggerer.
- [ ] Connect Airflow to the dedicated CNPG cluster.
- [ ] Use service account `system:serviceaccount:airflow:airflow-spark-submit` for Spark submission.
- [ ] Grant `get`, `list`, `watch`, `create`, and `delete` on `SparkApplication` resources.
- [ ] Grant `get`, `list`, and `watch` on pods and events, plus `get` on pod logs.
- [ ] Grant `get`, `list`, `watch`, `create`, `update`, `patch`, and `delete` on Leases.
- [ ] Do not grant generic pod creation or cluster-wide access to the Airflow service account.
- [ ] Implement a typed deferrable `ApacheSparkApplicationOperator` and `SparkApplicationTrigger`.
- [ ] Use generic Kubernetes CRD create, get, list, watch, and delete operations.
- [ ] Tolerate unknown Spark states while classifying known active and terminal states.
- [ ] Use `stateTransitionHistory` as the outcome record.
- [ ] Do not treat `ResourceReleased` alone as a success or failure result.
- [ ] Record submission, identity, state transitions, terminal state, events, and bounded driver-tail diagnostics.
- [ ] On cancellation, collect diagnostics, delete the exact CR, verify workload stop, then release its Lease.
- [ ] Name attempts `lh-<dag8>-<task8>-<identity12>-a<try>`.
- [ ] Compute `identity12` as the first 12 hexadecimal SHA-256 characters.
- [ ] Hash `dag_id`, `run_id`, `task_id`, and `map_index` with NUL separators.
- [ ] Map the same Airflow try to the same CR, and map a new try to a new CR.
- [ ] Keep `logical_date` as metadata and exclude it from application identity.
- [ ] Put bounded identity hashes in labels and full Airflow identities in annotations.
- [ ] Add `app.kubernetes.io/name=lakehouse-spark` and `app.kubernetes.io/part-of=lakehouse`.
- [ ] Add `anton.io/lakehouse-target=shadow|authoritative` and `anton.io/retain-failed-pod=true`.
- [ ] Add bounded DAG, run, task, and try labels for Loki indexing.
- [ ] Add full `dag_id`, `run_id`, `task_id`, map, and attempt annotations.
- [ ] Copy correlation metadata into driver and executor templates and environments.
- [ ] Create `lakehouse-shadow-writer` and `lakehouse-authoritative-writer` Leases.
- [ ] Set each Lease holder identity to the exact Spark Attempt name.
- [ ] Renew the selected Lease while the task remains deferred.
- [ ] Permit Lease theft only after expiry and proof that the prior application is inactive.
- [ ] Add an Airflow pool with one slot and include deferred tasks as defense in depth.
- [ ] Reattach to the same active attempt after scheduler or triggerer recovery.
- [ ] Reconcile active, succeeded, failed, absent, prior-success, and ambiguous attempt states.
- [ ] Validate prior output before a retry writes another snapshot.
- [ ] Fail closed when application or commit state is ambiguous.
- [ ] Define the DAG schedule as `23 * * * *` in UTC.
- [ ] Set `catchup=False` and `max_active_runs=1`.
- [ ] Ship each schedule change through source, image digest, and Flux.

### Phase 5: Prove logs, history, and retention

- [x] Add a targeted OTel file receiver for Airflow and Spark pod paths.
- [x] Start unseen files at their beginning and store receiver checkpoints persistently.
- [x] Exclude targeted paths from the general receiver to prevent duplicate records.
- [x] Keep the general receiver's current `start_at: end` behavior for other workloads.
- [x] Change global pod garbage collection to exclude `anton.io/retain-failed-pod=true`.
- [x] Mark retained Spark pods and their `SparkApplication` resources with the retention label.
- [x] Run one normal success test with unique markers in Airflow, driver, and executor output.
- [x] Run one deliberately short-lived executor test with unique markers.
- [x] Run one pre-Iceberg-commit failure test with unique markers.
- [x] Find complete runtime markers in Loki after every relevant container exits.
- [x] Find submission, state, and bounded failure diagnostics in the Airflow task log.
- [x] Verify History Server applications, jobs, stages, executors, SQL data, and event-log rollover.
- [x] Do not use standard-output markers as History Server evidence.
- [x] Verify failed driver and executor pods remain visible for at least 24 hours.
- [x] Verify successful resources disappear promptly and retained resources disappear after their limits.
- [ ] Verify event logs remain queryable for 30 days, then expire through the storage owner.

### Phase 6: Pass compatibility and shadow gates

- [x] Configure Trino 480 catalog `iceberg` with `iceberg.security=READ_ONLY`.
- [x] Give Trino read-only authoritative warehouse credentials.
- [x] Add `iceberg_shadow` with read-only shadow warehouse credentials.
- [x] Prove Trino rejects table creation, insert, update, and delete operations.
- [ ] Read existing authoritative tables with Spark 4.1.3 without writing them.
- [x] Create shadow tables with Iceberg format version 2.
- [x] Prove schema, `5 / 5 / 5` row counts, partitions, snapshots, metadata locations, and time travel through Trino.
- [x] Prove normalized `MERGE`, hourly delete-and-insert, idempotency, and expected snapshot changes.
- [x] Run the full fixture workflow five consecutive times against the shadow target.
- [x] Add the bounded Loki-source workflow only after all fixture gates pass.
- [x] Run failure, retry, cancellation, Lease, triggerer-recovery, and scheduler-recovery tests.
- [x] Save image digests, dependency evidence, Kubernetes objects, queries, logs, and history results.
- [x] Reject cutover if any mandatory check lacks retained evidence.

### Phase 6a: Apply the compatibility fallback rule

- [ ] Reproduce a Spark 4.1.3 failure in the shadow target and a minimal application.
- [ ] Exclude configuration, credentials, object storage, and application code as causes.
- [ ] Record two bounded repair attempts before changing the runtime.
- [ ] Test Spark 4.0.4 with operator 1.0.0 and Iceberg 1.11.0.
- [ ] Use Spark 4.0.4 only when it passes the failed mandatory criterion.
- [ ] Document the bounded blocker before testing operator 0.9.0 and Spark 3.5.3.
- [ ] Use the final fallback only while a mandatory criterion remains blocked.
- [ ] Keep the `SparkApplication` boundary for every fallback.

### Phase 7: Cut over one authoritative writer

- [ ] Confirm all five shadow runs and every failure-path test passed.
- [ ] Pause the Airflow schedule before changing writer ownership.
- [ ] Suspend the legacy CronJob through Git and approved Flux reconciliation.
- [ ] Verify no legacy Job, driver, executor, or submission pod remains active.
- [ ] Record authoritative table snapshots, metadata locations, and Trino results.
- [ ] Change the Airflow target from shadow to authoritative through Git.
- [ ] Run one manual authoritative Workflow Run.
- [ ] Require Trino validation before enabling the schedule.
- [ ] Enable the Airflow schedule and observe 24 successful runs across at least 24 hours.
- [ ] Reset the observation window after any unexplained failure.
- [ ] Remove the legacy CronJob only after the observation window passes.
- [ ] Remove remaining `iceberg-demo` resources through a separate reviewed change.
- [ ] Retain the shadow environment for seven additional days.
- [ ] Require separate storage approval before deleting shadow data.

### Phase 8: Review, rollback, or remove

- [ ] Review the learning result on 2026-09-10.
- [ ] Re-run component intake with a concrete need before making the platform permanent.
- [ ] Permit only one explicit timebox extension for additional learning.
- [ ] For cutover rollback, pause Airflow and verify that its Spark workload stops.
- [ ] Restore the legacy CronJob through Git and approved Flux reconciliation.
- [ ] Verify the legacy job becomes the sole authoritative writer before resuming its schedule.
- [ ] For experiment removal, preserve the authoritative warehouse and Trino read path.
- [ ] Remove Airflow, Spark Operator, History Server, CNPG state, and new namespaces through Git.
- [ ] Delete new buckets only after storage approval and required evidence retention.
- [ ] Complete control-plane rollback within 30 minutes, excluding backup or data deletion time.

## Log

- 2026-08-11: Plan opened after ADR 0033 accepted the Airflow and Apache Spark Operator learning architecture.
- 2026-08-11: Round 6 selected Spark 4.1.3, Iceberg 1.11.0, Airflow 3.2.2, provider 10.21.0, and one AWS SDK family.
- 2026-08-11: The review date, learning ceilings, shadow cutover, and architecture-preserving fallback rules became explicit gates.
- 2026-08-12: Ticket 03 added non-overlapping workflow log ingestion, Spark event logs, History Server, and bounded Spark retention. Live acceptance found driver and executor logs in Loki after exit. History Server showed one completed application, 19 jobs, 41 stages, two executors, and 10 SQL records.
- 2026-08-12: SeaweedFS `BucketLifecyclePolicy` became the storage owner for 30-day event-log expiry. This removed the need for a separate delete identity in the History Server path.
- 2026-08-12: Added a read-only five-run shadow-gate ledger validator. It binds each run to the DAG Spark digest and retained evidence. Live gate execution remains pending operator approval.
- 2026-08-12: Implemented Ticket 08's manual shadow-only Loki source workflow. It enforces a five-minute window, a 1000-entry completeness fence, deterministic raw snapshots in `iceberg-raw`, bucket-specific S3A credentials, and the existing Spark Attempt Lease/retry/cancellation path. Image publication, Ticket 07 completion, Flux reconciliation, and one approved source run remain pending.
- 2026-08-13: Published and pinned the Ticket 08 Airflow and Spark runtime images at immutable digests. The Spark image now avoids a recursive ownership layer that duplicated the large runtime payload during source rebuilds. Ticket 07 evidence, Flux rollout, and one approved Loki source run with Trino evidence remain pending.
- 2026-08-13: Recovered the Apache operator rollout by removing its failed stateless Deployment and forcing one Helm reconcile. Helm then created the committed ClusterRole and the operator became ready without RBAC errors.
- 2026-08-13: Live acceptance found and fixed two runtime defects. Spark now stages `transform.py` from `/opt/spark/application`, and the Airflow trigger watches an exact-name filtered custom-resource list.
- 2026-08-13: Five consecutive manual shadow Workflow Runs succeeded with Spark digest `sha256:f76b38d07d0c0b1784e962073c918176f116359f7e3c8e82e0e0efbb939563e7` and Airflow digest `sha256:91c0ed0a723902782a77d602faedaa1b6f612359df1de9191bab0557e83fe4bd`.
- 2026-08-13: The first Ticket 07 candidate lacked separate Trino reader identities. The accepted rotated ledger superseded that incomplete state.
- 2026-08-13: Ticket 07 is resolved. Its rotated ledger reports five passes, `eligible=true`, and no errors.
- 2026-08-13: Ticket 05 passed its focused contract and current shadow runtime checks.
- 2026-08-13: The Ticket 06 read-only audit accepted normal success, short-life logs, and History Server evidence. Controlled recovery tests remained open.
- 2026-08-13: Ticket 06 is resolved. Its live ledger passed failure, retry, cancellation, Lease, duplicate-delivery, scheduler, and triggerer tests.
- 2026-08-13: The accepted pre-commit failure retained driver and executor diagnostics without changing shadow snapshot `6584017577001615138`.

## References

- Related ADR: `context/adrs/0033-adopt-airflow-spark-operator-lakehouse.md`
- Superseded ADR: `context/adrs/0031-adopt-seaweedfs-iceberg-log-demo.md`
- Existing lakehouse plan: `context/plans/0020-implement-seaweedfs-iceberg-log-lakehouse.md`
- Existing Spark workload: `kubernetes/apps/iceberg-demo/spark-fixture/app/job.yaml`
- Existing Trino release: `kubernetes/apps/iceberg-demo/trino/app/helmrelease.yaml`
- Existing OTel receiver: `kubernetes/apps/observability/otel-collector/app/helmrelease.yaml`
- Existing failed-pod collector: `kubernetes/apps/kube-system/pod-gc/app/cronjob.yaml`
- Spark Operator documentation: <https://apache.github.io/spark-kubernetes-operator/>
- Spark Operator 1.0.0 release: <https://github.com/apache/spark-kubernetes-operator/releases/tag/1.0.0>
- Spark 4.1.3 release: <https://spark.apache.org/releases/spark-release-4-1-3.html>
- Iceberg releases and engine support: <https://iceberg.apache.org/releases/> and <https://iceberg.apache.org/multi-engine-support/>
- Iceberg AWS integration: <https://iceberg.apache.org/docs/latest/aws/>
- Hadoop 3.4.2 AWS integration: <https://hadoop.apache.org/docs/r3.4.2/hadoop-aws/tools/hadoop-aws/index.html>
- Airflow Helm chart: <https://airflow.apache.org/docs/helm-chart/stable/index.html>
- Airflow Kubernetes provider changes: <https://airflow.apache.org/docs/apache-airflow-providers-cncf-kubernetes/stable/changelog.html>
- Airflow custom image constraints: <https://airflow.apache.org/docs/docker-stack/build.html>
- Kubernetes provider package record: <https://pypi.org/project/apache-airflow-providers-cncf-kubernetes/10.21.0/>
- Trino Iceberg connector: <https://trino.io/docs/current/connector/iceberg.html>
- Cluster version source: `talos/talenv.yaml`
