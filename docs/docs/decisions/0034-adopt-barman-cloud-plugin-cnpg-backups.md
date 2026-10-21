---
status: Superseded-by 0035
date: 2026-08-12
deciders: ['@wcygan']
affects: databases
intent: concrete-need
supersedes: []
superseded-by: 0035
retrospective: false
edition: condensed-public
slug: /decisions/0034-adopt-barman-cloud-plugin-cnpg-backups
---

# 0034 — Adopt the Barman Cloud plugin for CNPG backups

> Back up CNPG databases with the official Barman Cloud plugin, to an independent target with a passing restore drill.

_Public edition condensed on 2026-10-21; original decision date and meaning retained._

:::caution Superseded
Replaced by [ADR 0035](0035-defer-airflow-metadata-backups.md). Read it before applying this decision.
:::

## Context

Airflow's metadata database needed scheduled backups and a successful restore drill. Longhorn replication does not protect against cluster loss or operator error, and the first backup target shared the cluster's failure domain. CloudNativePG was also deprecating its built-in Barman integration in favor of a plugin.

## Decision

Use the official Barman Cloud plugin for CNPG backup and recovery.

- Each durable database writes to an independent object-store target.
- A backup is accepted only after a restore drill passes.
- Credentials are scoped to a private backup bucket.

The plugin's `ObjectStore` resources are namespaced; its controller and CRD are cluster-wide. Removal must preserve remote objects and go consumer-first.

## Alternatives considered

- **Do nothing:** Airflow metadata is unrecoverable after cluster loss.
- **SeaweedFS on Longhorn as the target:** shares the cluster's failure domain.
- **CNPG's built-in integration:** being deprecated.
- **Scheduled `pg_dump` jobs:** deferred in favor of physical backups and WAL archives.

## Consequences

The plugin adds a controller, a CRD, a sidecar per database, credentials, upgrade work, and a standing requirement for restore evidence. The independent target and restore verification remained follow-ups.

[ADR 0035](0035-defer-airflow-metadata-backups.md) later superseded this plan and deferred backups during the learning phase.
