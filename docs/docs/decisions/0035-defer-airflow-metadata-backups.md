---
status: Superseded-by 0036
date: 2026-08-12
deciders: ['@wcygan']
affects: databases
intent: learning
supersedes: [0034]
superseded-by: 0036
retrospective: false
review-by: 2026-09-10
edition: condensed-public
slug: /decisions/0035-defer-airflow-metadata-backups
---

# 0035 — Defer Airflow metadata backups

> Defer Airflow metadata backups during the learning phase and accept total metadata loss.

_Public edition condensed on 2026-10-21; original decision date and meaning retained._

:::caution Superseded
Replaced by [ADR 0036](0036-continue-airflow-lakehouse-without-metadata-recovery.md). Read it before applying this decision.
:::

## Context

[ADR 0034](0034-adopt-barman-cloud-plugin-cnpg-backups.md) proposed the Barman Cloud plugin, but no database used its `ObjectStore` resources. Airflow was still an experimental learning system, and its metadata had no durable value. An off-cluster backup target and restore drills cost more than the protection was worth at that stage. Longhorn replication could survive some node failures but is not a backup.

## Decision

- Defer Airflow metadata backup and restore during the learning phase.
- Remove the unused plugin and its cluster-wide CRD.
- Accept complete loss of Airflow metadata if the CNPG volume is lost.

Git, pinned images, DAGs, and external secrets can rebuild the service, but not its history. This only removes backup and restore from the learning work; [ADR 0033](0033-adopt-airflow-spark-operator-lakehouse.md) still required them before an authoritative cutover.

## Alternatives considered

- **Keep the unused plugin:** a controller with no consumer.
- **Back up to in-cluster SeaweedFS:** shares the failure domain.
- **An independent object store now:** deferred until the metadata has durable value.

## Consequences

The accepted recovery point allows total metadata loss, and recovery time includes reconciliation and database initialization. The learning review must revisit this risk, and an independent target would still be needed before an authoritative cutover.

[ADR 0036](0036-continue-airflow-lakehouse-without-metadata-recovery.md) later superseded this decision and changed the cutover gate explicitly.
