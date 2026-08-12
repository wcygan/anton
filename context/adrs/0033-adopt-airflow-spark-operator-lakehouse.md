---
status: Accepted
date: 2026-08-11
deciders: ['@wcygan']
affects: all
intent: learning
supersedes: [0031]
superseded-by: null
retrospective: false
review-by: 2026-09-10
---

# 0033 — Adopt Airflow and Spark Operator for the lakehouse

> Airflow will own Anton's lakehouse workflow through Apache Spark Operator `SparkApplication` resources and durable observability paths.

## Status

`Accepted`

## Context

ADR 0031 proved a small Spark, Iceberg, SeaweedFS, and Trino workflow. A Kubernetes CronJob now runs `spark-submit` each hour. This design cannot provide the intended workflow control plane. Short-lived Spark pods can also exit before the current log receiver reads their files.

Anton uses this migration to learn a production-oriented Kubernetes architecture. The migration must preserve the Apache `SparkApplication` boundary. It must not optimize for the existing `spark-submit` path.

### Terminology

This decision uses these terms:

- A **Workflow Run** is one Airflow DAG run.
- A **Spark Attempt** is one `SparkApplication` for one Airflow task attempt.
- **Runtime Logs** are Airflow, driver, and executor standard streams stored in Loki.
- **Application History** is Spark event data stored in SeaweedFS and read by Spark History Server.

## Decision

Airflow will own the fixture, Spark, Iceberg, Trino validation, and later Loki-source workflow. The DAG source will define the `23 * * * *` UTC schedule. It will disable catchup and permit one active run. Schedule changes will ship through the custom Airflow image and its Flux-managed digest.

Airflow will use chart 1.22.0, Airflow 3.2.2, Python 3.12, and Kubernetes provider 10.21.0. The image build will use official Airflow constraints. KubernetesExecutor will give each task an isolated pod. A dedicated one-instance CNPG cluster will store Airflow metadata during learning.

A typed deferrable Airflow operator will create and watch `spark.apache.org/v1` `SparkApplication` resources. The adapter will use Airflow's generic Kubernetes resource facilities. It will not use `SparkKubernetesOperator` or `KubernetesPodOperator` with `spark-submit`.

The primary runtime will use Spark Operator chart 1.8.0, operator 1.0.0, Spark 4.1.3, and Iceberg 1.11.0. Spark 4.0.4 is the first compatibility option. Operator 0.9.0, Spark 3.5.3, and Iceberg 1.5.2 are the final compatibility fallback. Every option keeps the Apache `SparkApplication` control plane.

The Spark image will extend the official Java 21, Scala 2.13, and Python Spark image. It will use one AWS SDK v2 dependency family. It will pin all artifacts and contain no runtime dependency downloads. Iceberg tables will use format version 2. Existing table formats will not change during shadow testing.

Airflow will use a Kubernetes Lease for each writable target. The active Spark Attempt will hold the Lease during deferred waits. Spark restart policy will be `Never`. Airflow will own bounded, identity-aware retries. Trino 480 will remain read-only through connector policy and read-only storage credentials.

Control planes will use separate namespaces. Airflow and its metadata cluster will run in `airflow`. The CNPG operator will remain in `databases`. The Spark operator will run in `spark-system`. Spark applications and History Server will run in `lakehouse`. Trino 480 will move to `trino`. Storage and observability namespaces will retain their current ownership.

Namespace Roles will grant only required access. Airflow may manage `SparkApplication` resources and their diagnostics in `lakehouse`. The Spark operator will watch only `lakehouse`. History Server will not receive a Kubernetes API token.

Loki will remain the source for complete runtime logs. A targeted receiver will read new Airflow and Spark files from their beginning. Persistent checkpoints will prevent loss and duplicates. The general cluster receiver can retain its current end-of-file behavior.

Spark event logs will use `s3a://spark-events/events/` with 30-day retention. History Server will use the pinned Spark image and read-only storage credentials. Failed Spark resources will remain for 24 hours. Spark application records will remain for seven days.

Shadow runs will use `s3://iceberg-shadow` and Trino catalog `iceberg_shadow`. Authoritative data will remain in `s3://iceberg-warehouse` and catalog `iceberg`. Five shadow runs must pass before cutover begins. The legacy writer will stop before Airflow receives authoritative write access.

All control-plane components will start with one replica. Resource values are learning ceilings, not production capacity guidance. Spark heap, overhead, and native headroom must remain below each pod memory limit.

## Alternatives considered

- **Keep the CronJob and `spark-submit`** — rejected because it preserves the control-plane gap.
- **Use `KubernetesPodOperator` with `spark-submit`** — rejected because it avoids the selected `SparkApplication` architecture.
- **Use Airflow `SparkKubernetesOperator`** — rejected because it targets the older `sparkoperator.k8s.io/v1beta2` API.
- **Start with Spark 4.2** — rejected because Iceberg 1.11.0 does not publish a Spark 4.2 runtime.
- **Combine migration and write optimization** — rejected because it would obscure platform compatibility failures.

## Consequences

### Accepted costs

- Anton adds Airflow, the Spark operator, Spark History Server, and an Airflow metadata cluster.
- Operators must maintain two pinned custom images and their dependency evidence.
- The custom Airflow adapter becomes Anton-owned integration code until native support exists.
- Airflow compatibility with Kubernetes 1.36 requires local acceptance because upstream coverage stops at 1.35.
- The migration requires three observability proofs: Airflow task logs, Loki runtime logs, and Spark application history.
- CNPG backup and restore must pass before cutover.
- Each added chart and image increases the Renovate review load.
- The learning deployment must be reviewed by 2026-09-10.
- Removal must restore the legacy writer before removing Airflow-owned write access.

## Follow-ups

- [ ] Execute Plan 0023 and retain all compatibility evidence.
- [ ] Review the learning deployment on 2026-09-10.
- [ ] Keep the platform only after a concrete-need review or one explicit learning extension.
