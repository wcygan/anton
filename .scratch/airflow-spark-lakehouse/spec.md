# Airflow Spark Lakehouse Implementation Specification

**Status:** ready-for-agent

## Problem Statement

Anton has a working Spark, Iceberg, SeaweedFS, and Trino learning workflow. A Kubernetes CronJob currently starts `spark-submit` each hour. This path does not provide the selected production-oriented workflow control plane.

The current log receiver starts at the end of new container log files. A short-lived Spark pod can exit before the receiver collects its complete output. Operators then lose the evidence needed to diagnose failed drivers and executors.

The migration must introduce Airflow and Apache Spark Operator without allowing two authoritative Iceberg writers. It must also prove Spark 4 compatibility against Anton's exact catalog, object storage, Trino, Kubernetes, and logging paths.

## Solution

Airflow will own each Workflow Run. A typed deferrable adapter will create and watch an Apache `SparkApplication`. Apache Spark Operator will create the driver and executor pods.

The first workflow will process the deterministic fixture. Spark will write Iceberg format version 2 tables in a separate shadow warehouse. Trino will validate the result with read-only access. A later workflow will add bounded Loki-source ingestion after the fixture path passes.

Runtime Logs will flow to Loki from the beginning of each Airflow and Spark container log. Spark event logs will flow to SeaweedFS. Spark History Server will provide Application History.

The migration will use a shadow-first cutover. A Kubernetes Lease will enforce one writer for each target. The legacy CronJob will stop before Airflow receives authoritative write access.

## User Stories

1. As an Anton operator, I want Airflow to own each Workflow Run, so that one control plane records workflow progress.
2. As an Anton operator, I want Airflow to create `SparkApplication` resources, so that Spark uses the selected Kubernetes control plane.
3. As an Anton operator, I want Spark Operator to create drivers and executors, so that Airflow does not run `spark-submit` pods.
4. As an Anton operator, I want each Airflow task attempt to create one Spark Attempt, so that retries have unique identities.
5. As an Anton operator, I want the same task try to find the same Spark Attempt, so that scheduler recovery is idempotent.
6. As an Anton operator, I want full Airflow identities on Spark resources, so that I can correlate workflows, pods, and logs.
7. As an Anton operator, I want bounded identity labels, so that Loki and Kubernetes can index attempts safely.
8. As an Anton operator, I want a target-specific writer Lease, so that two Spark writers cannot use one warehouse.
9. As an Anton operator, I want deferred tasks to renew their writer Lease, so that long Spark work retains ownership.
10. As an Anton operator, I want expired Lease recovery to check the prior application, so that stale locks do not hide active writers.
11. As an Anton operator, I want Airflow to own bounded retries, so that Spark does not restart work without workflow context.
12. As an Anton operator, I want ambiguous commit state to fail closed, so that retries cannot corrupt authoritative metadata.
13. As an Anton operator, I want cancellation to stop the exact Spark Attempt, so that abandoned work cannot continue writing.
14. As an Anton operator, I want bounded failure diagnostics in the Airflow task log, so that common failures are visible in one place.
15. As an Anton operator, I want complete driver and executor output in Loki, so that short-lived pods remain diagnosable.
16. As an Anton operator, I want Spark event logs in SeaweedFS, so that Application History survives pod deletion.
17. As an Anton operator, I want a read-only History Server, so that history access cannot change cluster resources or event data.
18. As an Anton operator, I want failed Spark pods retained for 24 hours, so that I can inspect their terminal state.
19. As an Anton operator, I want Spark application records retained for seven days, so that recent attempt history remains available.
20. As an Anton operator, I want event logs retained for 30 days, so that I can compare recent Workflow Runs.
21. As an Anton operator, I want successful resources removed promptly, so that normal runs do not create permanent cluster debris.
22. As an Anton operator, I want the global pod collector to preserve marked Spark failures, so that cleanup does not remove evidence early.
23. As an Anton operator, I want Spark 4.1.3 as the primary runtime, so that the learning deployment uses the selected current platform.
24. As an Anton operator, I want an architecture-preserving fallback ladder, so that compatibility issues never force direct `spark-submit` orchestration.
25. As an Anton operator, I want one closed AWS SDK v2 family, so that Iceberg and Hadoop do not load conflicting classes.
26. As an Anton operator, I want a recorded JAR inventory and hashes, so that the Spark runtime can be reproduced and audited.
27. As an Anton operator, I want runtime version checks inside drivers and executors, so that build metadata cannot mask the actual runtime.
28. As an Anton operator, I want Iceberg S3FileIO tested against SeaweedFS, so that table data uses the final object-storage path.
29. As an Anton operator, I want Hadoop S3A tested against SeaweedFS, so that Spark event logging uses the final object-storage path.
30. As an Anton operator, I want no runtime dependency downloads, so that Spark Attempts do not depend on external package services.
31. As an Anton operator, I want existing table formats inspected before migration, so that shadow testing cannot silently change authoritative metadata.
32. As an Anton operator, I want Iceberg format version 2 for new shadow tables, so that Spark and Trino share a stable format.
33. As an Anton operator, I want the current hourly write behavior preserved, so that platform migration does not also change table semantics.
34. As an Anton operator, I want transformed-partition `MERGE` tested later, so that write optimization has separate evidence.
35. As an Anton operator, I want Trino 480 to remain read-only, so that Spark remains the only Iceberg writer.
36. As an Anton operator, I want Trino storage credentials to be read-only, so that connector configuration is not the only write barrier.
37. As an Anton operator, I want Trino to validate schema, counts, partitions, snapshots, locations, and time travel, so that cross-engine compatibility is proven.
38. As an Anton operator, I want a separate shadow warehouse and catalog, so that compatibility tests cannot change authoritative tables.
39. As an Anton operator, I want five consecutive shadow runs, so that cutover requires repeated end-to-end success.
40. As an Anton operator, I want one manual authoritative run before scheduling, so that writer transfer has a controlled gate.
41. As an Anton operator, I want 24 successful scheduled runs across 24 hours, so that cutover proves recurring operation.
42. As an Anton operator, I want the observation window reset after unexplained failure, so that intermittent defects cannot pass the gate.
43. As an Anton operator, I want the legacy writer retained during shadow testing, so that the current authoritative workflow remains available.
44. As an Anton operator, I want the legacy writer stopped before cutover, so that authoritative metadata never has two writers.
45. As an Anton operator, I want rollback to restore the legacy writer through Git, so that recovery preserves GitOps ownership.
46. As an Anton operator, I want Airflow metadata in dedicated PostgreSQL, so that the deployment uses an external production-like database pattern.
47. As an Anton operator, I want Airflow metadata backup and restore proven before cutover, so that workflow state has a tested recovery path.
48. As an Anton operator, I want KubernetesExecutor task pods, so that orchestration tasks have isolated Kubernetes runtimes.
49. As an Anton operator, I want namespace-scoped Airflow and Spark permissions, so that neither control plane needs cluster administration.
50. As an Anton operator, I want one initial replica per control-plane component, so that learning does not add premature high availability.
51. As an Anton operator, I want explicit Spark heap and overhead settings, so that runtime memory fits below pod limits.
52. As an Anton operator, I want peak resource use recorded, so that later sizing changes use measured evidence.
53. As an Anton operator, I want the schedule defined in DAG source, so that schedule changes follow image and Flux review.
54. As an Anton operator, I want fixture acceptance before Loki-source ingestion, so that one platform change is proven at a time.
55. As an Anton operator, I want a September learning review, so that the new platform cannot become unreviewed permanent debt.
56. As an Anton operator, I want a bounded removal path, so that the experiment can be removed without deleting authoritative Iceberg data.

## Implementation Decisions

- Airflow owns the fixture, Spark, Iceberg, Trino validation, and later Loki-source workflow.
- The DAG schedule is `23 * * * *` in UTC with catchup disabled and one active run.
- Schedule changes move through DAG source, the custom image, its digest, and Flux.
- Airflow uses Helm chart 1.22.0, Airflow 3.2.2, Python 3.12, and Kubernetes provider 10.21.0.
- The Airflow image uses official constraints and contains the DAGs, adapter, trigger, and tests.
- Kubernetes provider 10.20.0 is allowed only after a reproducible 10.21.0 regression.
- Airflow uses KubernetesExecutor with one API server, scheduler, DAG processor, and triggerer.
- A dedicated one-instance CNPG cluster stores Airflow metadata during learning.
- The Airflow metadata cluster lives with its consumer. The shared CNPG operator remains platform-owned.
- A typed deferrable `ApacheSparkApplicationOperator` creates and observes custom resources.
- A `SparkApplicationTrigger` watches meaningful state changes and renews the writer Lease.
- The adapter uses generic Kubernetes resource facilities instead of Airflow's legacy Spark operator integration.
- The adapter never launches `spark-submit` through `KubernetesPodOperator`.
- The primary runtime is Spark Operator 1.0.0 from chart 1.8.0, Spark 4.1.3, and Iceberg 1.11.0.
- The first compatibility option is Spark Operator 1.0.0, Spark 4.0.4, and Iceberg 1.11.0.
- The final fallback is Spark Operator 0.9.0, Spark 3.5.3, and Iceberg 1.5.2.
- Every runtime option preserves the Apache `SparkApplication` boundary.
- A fallback requires a minimal reproduction, excluded configuration errors, and two bounded repair attempts.
- The primary Spark image extends the official Java 21, Scala 2.13, and Python image.
- The image is pinned by digest and asserts Python 3.12 during its build.
- The image contains Iceberg's Spark 4.1 runtime and matching Hadoop 3.4.2 components.
- Hadoop common, Hadoop clients, and `hadoop-aws` use the same 3.4.2 version.
- One AWS SDK v2 family serves Iceberg S3FileIO and Hadoop S3A.
- The image contains the required AWS HTTP client and excludes competing SDK bundles.
- The build emits a resolved dependency tree, JAR inventory, SHA-256 hashes, and effective dependency versions.
- The build fails when incompatible `software.amazon.awssdk` classes are present.
- Runtime startup cannot download Maven, Ivy, Python, or operating-system dependencies.
- New shadow tables use Iceberg format version 2.
- Authoritative table format remains unchanged during shadow testing.
- The normalized table retains its current idempotent `MERGE` behavior.
- The hourly table retains its bounded delete-and-insert behavior through cutover.
- Trino remains at version 480 during the migration.
- Both Trino catalogs use `iceberg.security=READ_ONLY` and read-only storage credentials.
- Trino validates data and metadata but never participates in writes.
- A Workflow Run is one Airflow DAG run.
- A Spark Attempt is one `SparkApplication` for one Airflow task attempt.
- Spark Attempt names use bounded DAG and task prefixes, a stable identity hash, and the Airflow try number.
- The identity hash uses DAG, run, task, and map identities with NUL separators.
- Logical date is optional metadata and does not define attempt identity.
- Bounded hashes and the try number use labels. Full identities use annotations.
- Correlation metadata is copied to driver and executor pod templates and environments.
- `lakehouse-shadow-writer` and `lakehouse-authoritative-writer` are the target Locks.
- The Lease holder identity equals the Spark Attempt name.
- Lease takeover requires expiry and proof that the prior Spark application is inactive.
- Spark restart policy is `Never`. Airflow owns retries.
- The same Airflow try reattaches to the same Spark Attempt.
- A new Airflow try creates a new Spark Attempt after prior-state reconciliation.
- Active attempts reattach, succeeded attempts advance to Trino validation, and failed attempts collect diagnostics.
- Prior valid output can satisfy an idempotent retry. Ambiguous state fails closed.
- `stateTransitionHistory` is the outcome record. `ResourceReleased` alone does not define success.
- Cancellation collects bounded diagnostics, deletes the exact custom resource, verifies stop, then releases the Lease.
- Airflow has custom-resource, Lease, pod-read, pod-log, and event-read access in the workload namespace.
- Airflow does not receive generic pod creation or cluster-wide permissions for Spark workloads.
- Spark Operator watches only the workload namespace.
- History Server does not receive a Kubernetes API token.
- Runtime Logs include Airflow, driver, and executor standard streams stored in Loki.
- A targeted receiver reads new Airflow and Spark log files from their beginning.
- Persistent checkpoints and non-overlapping file selection prevent loss and duplicates.
- Application History uses compressed rolling event logs under `s3a://spark-events/events/`.
- History Server uses the pinned Spark image and read-only object-storage credentials.
- A storage-owned identity enforces the 30-day event-log deletion policy.
- Failed Spark resources remain for 24 hours. Spark application records remain for seven days.
- The global failed-pod collector excludes resources marked for Spark failure retention.
- The shadow warehouse is `s3://iceberg-shadow` with Trino catalog `iceberg_shadow`.
- The authoritative warehouse remains `s3://iceberg-warehouse` with Trino catalog `iceberg`.
- Cutover pauses Airflow, stops the legacy writer, proves no active legacy workload, and records authoritative state.
- One manual authoritative Workflow Run and Trino validation precede schedule enablement.
- The legacy deployment is removed only after 24 successful scheduled runs across at least 24 hours.
- The shadow environment remains for seven more days. Data deletion requires separate storage approval.
- Resource values are initial learning ceilings, not production capacity guidance.
- Spark heap, overhead, and native headroom must remain below each 1536Mi pod limit.
- The learning deployment is reviewed on 2026-09-10.
- Permanent retention requires a concrete-need review or one explicit learning extension.

## Testing Decisions

- Tests observe public behavior and stable operator interfaces. They do not assert private helper calls or implementation structure.
- The Spark runtime contract is the first public seam.
- The runtime contract verifies Spark, Scala, Java, Python, Hadoop, Iceberg, and AWS SDK identities.
- The runtime contract records every JAR name and SHA-256 hash.
- The runtime contract fails on duplicate incompatible AWS SDK classes.
- The runtime contract exercises Iceberg S3FileIO and Hadoop S3A from the exact final image.
- The Airflow Spark adapter contract is the second public seam.
- The adapter contract supplies Kubernetes resource and watch events at the external API boundary.
- The adapter contract verifies identity, state classification, Lease renewal, takeover, retry, recovery, cancellation, and fail-closed behavior.
- The Workflow Run acceptance path is the highest end-to-end seam.
- The acceptance path starts an Airflow Workflow Run and observes its exact Spark Attempt.
- The acceptance path verifies Iceberg schema, `5 / 5 / 5` counts, partitions, snapshots, locations, and time travel through Trino.
- The acceptance path verifies that Trino write statements fail.
- The acceptance path verifies complete unique markers in Airflow task logs and Loki Runtime Logs.
- The acceptance path verifies applications, jobs, stages, executors, and SQL data through History Server.
- Three controlled runs cover normal success, a short-lived executor, and failure before Iceberg commit.
- Recovery tests cover scheduler restart, triggerer restart, duplicate delivery, cancellation, retry, and expired Lease handling.
- Retention tests prove failed driver and executor visibility for 24 hours.
- Cleanup tests prove prompt successful-resource removal and bounded retained-resource removal.
- Kubernetes 1.36 acceptance runs against Anton because Airflow's upstream coverage stops at 1.35.
- Five consecutive shadow runs are required before cutover.
- Twenty-four consecutive authoritative scheduled runs across at least 24 hours are required after cutover.
- Existing fixture output, Trino validation, logging contracts, and storage smoke checks provide prior art.
- Live workload creation, Flux reconciliation, port forwarding, and cutover require explicit operator approval.

## Out of Scope

- Spark 4.2 is not part of this migration.
- Iceberg format version 3 is not part of this migration.
- The hourly transformed-partition `MERGE` optimization is a separate experiment.
- Trino upgrades and Trino write access are excluded.
- High availability for Airflow, CNPG, Spark Operator, or History Server is excluded from the learning phase.
- `KubernetesPodOperator` with `spark-submit` is not an accepted fallback.
- Airflow's legacy `SparkKubernetesOperator` is not used.
- Kafka, Flink, Polaris, Nessie, and Hive Metastore are not added.
- Public Airflow, Trino, or History Server routes are not required.
- Production capacity recommendations are not produced from the initial resource ceilings.
- Shadow data deletion is not authorized by this specification.
- Authoritative Iceberg data deletion is never part of experiment removal.

## Further Notes

ADR 0033 is the durable decision authority. Plan 0023 is the mutable execution record.

Repository changes, live Flux actions, Kubernetes mutations, credential changes, and storage deletion remain separate authority boundaries.

The first implementation frontier contains two independent efforts: Spark runtime qualification and the Airflow Kubernetes foundation.

Ticket completion must retain exact image identities, test outputs, resource states, and failure evidence. Upstream compatibility tables do not replace Anton acceptance.
