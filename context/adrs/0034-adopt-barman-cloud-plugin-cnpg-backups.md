---
status: Accepted
date: 2026-08-12
deciders: ['@wcygan']
affects: databases
intent: concrete-need
supersedes: []
superseded-by: null
retrospective: false
---

# 0034 — Adopt the Barman Cloud plugin for CNPG backups

> Use the official CNPG plugin for off-cluster PostgreSQL backups and tested recovery.

## Status

`Accepted`

## Context

Airflow Ticket 04 requires a scheduled metadata backup and a successful restore drill. Longhorn replication protects against one node failure, but it does not protect against cluster loss or operator error.

The first backup target used SeaweedFS on Longhorn. That target shared the same failure domain as the source data and could not meet the recovery requirement. CloudNativePG 1.30 also deprecates its built-in Barman object-store integration.

Cluster intake accepted the official Barman Cloud plugin. The plugin is stateless, Apache-2.0 licensed, actively maintained, and compatible with standard Kubernetes Secrets.

## Decision

We will use the official Barman Cloud plugin for CNPG backup and recovery. Each durable database must use an independent object-store target and pass a restore drill before its backup is accepted.

## Alternatives considered

- **Do nothing** — rejected because Airflow metadata would remain unrecoverable after cluster loss.
- **Use SeaweedFS on Longhorn** — rejected because source data and backups share one failure domain.
- **Use the built-in Barman integration** — rejected because CloudNativePG deprecates it in favor of the plugin.
- **Run scheduled pg_dump jobs** — deferred because physical backups and WAL archives provide a stronger recovery path.

## Consequences

### Accepted costs

- The plugin adds one operator deployment and one cluster-wide CRD. Its `ObjectStore` resources are namespaced.
- Each protected PostgreSQL pod receives a Barman sidecar.
- Plugin and CRD upgrades add Renovate review work.
- Object-store credentials remain scoped to one private backup bucket.
- Every backup configuration requires a documented restore drill.
- Removal must preserve remote backup objects and follow the documented consumer-first order.

## Follow-ups

- [ ] Select and provision the independent S3-compatible target.
- [ ] Add the plugin through Flux with explicit resource limits.
- [ ] Add ESO credentials, an `ObjectStore`, and a scheduled Airflow backup.
- [ ] Restore Airflow metadata into a temporary cluster and retain evidence.
- [ ] Add backup age and failure alerts.
- [ ] Document removal: remove cluster plugin references, verify remote objects, remove `ObjectStore` resources, then remove the controller and CRD.
- [ ] Verify that plugin Roles and RoleBindings are absent after removal.
