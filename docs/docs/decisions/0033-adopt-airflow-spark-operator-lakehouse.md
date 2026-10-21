---
status: Superseded-by 0036
date: 2026-08-11
deciders: ['@wcygan']
affects: all
intent: learning
supersedes: [0031]
superseded-by: 0036
retrospective: false
review-by: 2026-09-10
edition: condensed-public
slug: /decisions/0033-adopt-airflow-spark-operator-lakehouse
---

# 0033 — Adopt Airflow and Spark Operator for the lakehouse

> Move the lakehouse to Airflow for orchestration and the Spark Operator for execution, as a learning platform.

_Public edition condensed on 2026-10-21; original decision date and meaning retained._

:::caution Superseded
Replaced by [ADR 0036](0036-continue-airflow-lakehouse-without-metadata-recovery.md). Read it before applying this decision.
:::

## Context

The CronJob and `spark-submit` demo from [ADR 0031](0031-adopt-seaweedfs-iceberg-log-demo.md) could not provide the workflow control plane the experiment wanted, and short-lived Spark pods could exit before their logs were collected. The goal was to learn a production-style Kubernetes design while keeping Apache `SparkApplication` as the workload boundary.

## Decision

### Ownership

- **Airflow** owns fixture ingestion, Spark processing, Iceberg validation, Trino checks, and later log-snapshot work. It uses KubernetesExecutor and a dedicated CNPG metadata database.
- A typed, deferrable operator creates and watches `SparkApplication` resources. It does not run `spark-submit` in a generic pod.
- **The Spark Operator** owns execution.

Pinned custom images carry their dependencies, with no downloads at runtime. Each component starts as a single replica with bounded resources.

### Safety

- Trino stays read-only.
- Each write target has a Lease. Airflow retries are bounded and identity-aware, and Spark's restart policy is `Never`.
- Runtime logs go to Loki; event history goes to SeaweedFS for the History Server.
- Separate namespaces and narrowly scoped Roles isolate the control planes.

### Cutover

Shadow tests use a separate bucket and catalog. Five successful shadow runs come before cutover, and the legacy writer stops before Airflow gets authoritative access.

## Alternatives considered

- **Keep CronJob submission:** bypasses the chosen control plane.
- **`KubernetesPodOperator` running `spark-submit`:** the same.
- **An operator targeting an older Spark API:** the same.

## Consequences

The design adds Airflow, the Spark Operator, the History Server, custom images, and a metadata database. Compatibility and restore checks increase maintenance. The learning deployment had a 2026-09-10 review date.

[ADR 0036](0036-continue-airflow-lakehouse-without-metadata-recovery.md) later changed the recovery and cutover requirements.
