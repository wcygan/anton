---
status: Superseded-by 0033
date: 2026-08-06
deciders: ['@wcygan']
affects: demos
intent: learning
supersedes: []
superseded-by: 0033
retrospective: false
review-by: 2026-08-20
edition: condensed-public
slug: /decisions/0031-adopt-seaweedfs-iceberg-log-demo
---

# 0031 — Adopt a SeaweedFS Iceberg log demo

> Build a small, disposable log ETL demo with SeaweedFS's Iceberg catalog, Spark, and Trino.

_Public edition condensed on 2026-10-21; original decision date and meaning retained._

:::caution Superseded
Replaced by [ADR 0033](0033-adopt-airflow-spark-operator-lakehouse.md). Read it before applying this decision.
:::

## Context

The cluster already ran Loki, SeaweedFS S3, Flux, and supporting storage and observability. A small lakehouse demo could give hands-on Spark, Iceberg, and Trino experience without a streaming broker or a separate catalog database. It was explicitly contained learning, not a durable analytics platform.

## Decision

Build a GitOps-managed log ETL demo from:

- SeaweedFS's built-in Iceberg REST catalog and a dedicated bucket;
- a pinned Spark batch image, submitted natively to Kubernetes with a Job or CronJob;
- Trino from its official chart.

Flux owns the resources, and External Secrets supplies credentials. Do not add Polaris, Nessie, Hive Metastore, Kafka, Flink, Spark Operator, Airflow, or Dagster to this first demo.

Start with deterministic JSONL input that produces normalized and hourly Iceberg tables. Only once that fixture path works may a later gate source snapshots from Loki, without changing table or query interfaces. Temporal was a possible later orchestrator. Review by 2026-08-20, and remove the namespace and manifests if no useful result emerges.

## Alternatives considered

- **Do nothing:** no ETL learning.
- **Polaris:** adds a service, persistence, authentication, and bootstrap work.
- **A path-based Hadoop catalog:** weakens multi-engine compatibility.

## Consequences

The chosen path requires verifying SeaweedFS's catalog exposure and OAuth behavior. It adds a bucket, credentials, a Spark image, a Trino release, and compute load. The data is disposable; the manifests and validation evidence are what last.

[ADR 0033](0033-adopt-airflow-spark-operator-lakehouse.md) later replaced this simple scheduling model with an Airflow and Spark Operator learning platform.
