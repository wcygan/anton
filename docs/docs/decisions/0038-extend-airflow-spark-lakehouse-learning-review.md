---
status: Superseded-by 0039
date: 2026-08-14
deciders: ['@wcygan']
affects: compute
intent: learning
supersedes: []
superseded-by: 0039
retrospective: false
review-by: 2026-09-15
edition: condensed-public
slug: /decisions/0038-extend-airflow-spark-lakehouse-learning-review
---

# 0038 — Extend the Airflow and Spark learning review once

> Extend the Airflow and Spark learning deployment once, to 2026-09-15, to finish two checks.

_Public edition condensed on 2026-10-21; original decision date and meaning retained._

:::caution Superseded
Replaced by [ADR 0039](0039-retain-airflow-spark-learning-platform.md). Read it before applying this decision.
:::

## Context

The scheduled authoritative run passed its evidence checks, and Flux removed the shadow control plane without deleting data. Trino confirmed the authoritative table contract and snapshots. Two learning checks were unfinished, and the platform had not passed concrete-need intake for permanent retention.

## Decision

Extend the learning deployment once, through 2026-09-15, to prove two things:

1. Spark can read authoritative tables without writing to them.
2. Event logs expire after 30 days under storage ownership.

After that date, remove the platform unless a concrete need passes intake. Preserve the authoritative warehouse, retained evidence, and the Trino read path. Bucket or object deletion remains a separate storage decision.

## Alternatives considered

- **Retain permanently:** no concrete need.
- **Remove immediately:** leaves two bounded checks unfinished.
- **Extend open-ended:** removes the learning timebox.

## Consequences

The extension keeps maintenance, upgrades, and the accepted metadata-loss risk for another month. No further extension was intended.

[ADR 0039](0039-retain-airflow-spark-learning-platform.md) later superseded the fixed removal date.
