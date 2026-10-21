---
status: Superseded-by 0040
date: 2026-08-14
deciders: ['@wcygan']
affects: compute
intent: learning
supersedes: [0038]
superseded-by: 0040
retrospective: false
edition: condensed-public
slug: /decisions/0039-retain-airflow-spark-learning-platform
---

# 0039 — Retain Airflow and Spark as a learning platform

> Keep Airflow and Spark as an open-ended learning platform, removing the fixed review date.

_Public edition condensed on 2026-10-21; original decision date and meaning retained._

:::caution Superseded
Replaced by [ADR 0040](0040-retire-lakehouse-and-temporal.md). Read it before applying this decision.
:::

## Context

The lakehouse plan had completed shadow testing, recovery checks, writer cutover, scheduled validation, and shadow control-plane cleanup. A read-only Spark check returned the expected table counts without changing authoritative snapshots. The operator had no production need but wanted to keep learning and experimenting.

## Decision

Retain Airflow, the Spark Operator, the History Server, and the Airflow CNPG cluster as an open-ended learning system, superseding [ADR 0038](0038-extend-airflow-spark-lakehouse-learning-review.md)'s removal date. No review date, event-log expiry check, or removal ticket is required.

Spark remains the only Iceberg writer, and Trino remains a read-only validation path. GitOps ownership, security controls, authoritative storage, and boundaries are unchanged.

## Alternatives considered

- **Keep the fixed removal date, or remove now:** rejected in favor of continued learning.
- **Treat it as production:** there was no production requirement.

## Consequences

This is an explicit exception to the normal learning timebox. The operator accepts ongoing chart and image maintenance, metadata loss, unverified 30-day event-log expiry, and no production service level or restore claim.

[ADR 0040](0040-retire-lakehouse-and-temporal.md) later retired the platform.
