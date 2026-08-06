---
status: Accepted
date: 2026-08-06
deciders: ['@wcygan']
affects: demos
intent: learning
supersedes: []
superseded-by: null
retrospective: false
review-by: 2026-08-20
---

# 0031 — Adopt SeaweedFS Iceberg REST log lakehouse demo

> Anton will use SeaweedFS's built-in Iceberg REST catalog to demonstrate GitOps-managed log ETL with Spark and Trino.

## Status

`Accepted`

## Context

Anton already has Flux, Harbor, SeaweedFS S3, ESO, Longhorn, and Loki. We want a small but realistic lakehouse exercise that processes logs into derived analytical tables without introducing a streaming broker, a separate catalog database, or manual UI configuration. The demo should also preserve a credible path toward Spark, Flink, and Trino sharing Iceberg tables later.

Apache Iceberg provides the table format, while SeaweedFS can provide both the S3-compatible warehouse and a built-in Iceberg REST catalog. The current SeaweedFS operator may require a small declarative overlay to expose the catalog port; that integration must be verified before rollout. This is a contained learning experiment, not a new Tier-0 analytics platform.

## Decision

Anton will adopt a GitOps-managed log lakehouse demo using SeaweedFS's built-in Iceberg REST catalog, Iceberg tables stored in a dedicated SeaweedFS bucket, a pinned Spark batch image stored in Harbor, and Trino deployed from its official Helm chart for SQL queries. Flux will own the Kubernetes resources, ESO will provide credentials, and no Polaris, Nessie, Hive Metastore, Kafka, Flink, Spark Operator, Airflow, or Dagster will be added for this demo.

The first gate uses deterministic JSONL input and produces `logs.normalized` and `logs.hourly` Iceberg tables. A second gate may replace the fixture with a Loki snapshot CronJob without changing the table or query interfaces. Spark will run through native Kubernetes submission and the first schedule will be a Kubernetes Job or CronJob; Temporal remains a later orchestration option.

## Alternatives considered

- **Do nothing** — preserves the current platform but provides no hands-on ETL, Iceberg, or Trino learning path.
- **Apache Polaris** — a strong standalone catalog, but adds a catalog service, PostgreSQL persistence, authentication configuration, and an idempotent bootstrap Job that are unnecessary for this minimal experiment.
- **Iceberg Hadoop/path catalog** — requires almost no service configuration, but is not a normal supported catalog type for the current Trino Iceberg connector and would weaken the multi-engine demo.

## Consequences

### Accepted costs

- The SeaweedFS operator integration must be verified and may need an extra argument plus an internal Service for the Iceberg REST port.
- A dedicated lakehouse bucket, ESO credentials, Spark image, Trino HelmRelease, and batch workload increase the repository and Renovate-PR surface.
- Spark and Trino consume CPU and memory on the three-node cluster; resource requests must remain bounded.
- Demo data is disposable and does not receive a production restore guarantee; the manifests and validation evidence remain the durable learning artifact.
- This experiment is time-boxed for review on 2026-08-20. If the demo does not produce a useful end-to-end result, remove its namespace and manifests rather than letting it become permanent platform debt.

## Follow-ups

- [ ] Verify the current SeaweedFS image and operator can expose the built-in Iceberg REST catalog declaratively.
- [ ] Author the dedicated lakehouse bucket, credentials, Spark image, Trino catalog, and batch-job manifests.
- [ ] Complete the deterministic JSONL gate and validate the same tables through Trino.
- [ ] Add the Loki snapshot gate only after the fixture path is green.
- [ ] Review the experiment on 2026-08-20 and retain, revise, or remove it based on evidence.
