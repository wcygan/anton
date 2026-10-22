---
status: Superseded-by 0037
date: 2026-08-13
deciders: ['@wcygan']
affects: all
intent: learning
supersedes: [0033, 0035]
superseded-by: 0037
retrospective: false
review-by: 2026-09-10
edition: condensed-public
slug: /decisions/0036-continue-airflow-lakehouse-without-metadata-recovery
---

# 0036 — Continue the lakehouse without metadata recovery

> Cut the lakehouse over to Airflow without metadata backup and without keeping the legacy writer as a fallback.

_Public edition condensed on 2026-10-21; original decision date and meaning retained._

:::caution Superseded
Replaced by [ADR 0037](0037-remove-extended-airflow-observation-gate.md). Read it before applying this decision.
:::

## Context

[ADR 0033](0033-adopt-airflow-spark-operator-lakehouse.md) chose Airflow and the Spark Operator, and [ADR 0035](0035-defer-airflow-metadata-backups.md) accepted metadata loss during learning. Five consecutive shadow runs and controlled recovery checks passed, so the writer cutover was ready. The metadata was still disposable, and keeping both a legacy writer and a database recovery path added work without protecting anything valuable.

## Decision

Proceed without Airflow metadata backup or restore, and accept total metadata loss. Do not keep the legacy writer after cutover.

1. Stop the legacy writer before Airflow receives authoritative write access.
2. Run one manual authoritative Workflow Run, and require it to pass Spark and read-only Trino validation.
3. Remove the legacy writer configuration through reviewed Git.
4. Start the Airflow schedule.

After that, repair failures on the Airflow and Spark Operator path.

This decision grants no live-operations authority. Git edits, Flux actions, workload removal, and storage deletion each remain a separate boundary. Authoritative Iceberg data and required evidence stay protected from control-plane cleanup. The learning deployment keeps its review date.

## Alternatives considered

- **Prove metadata recovery first:** the metadata had no durable value.
- **Keep a fallback writer:** maintains two workflow paths.
- **Delay cutover:** unnecessary after the shadow and recovery evidence.

## Consequences

Losing the CNPG volume can erase all workflow history, and in-flight work may need a fresh run. The removed legacy path cannot be restored from Git without reconfiguration.

[ADR 0037](0037-remove-extended-airflow-observation-gate.md) later refined the scheduled-observation requirement.
