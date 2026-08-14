---
status: Superseded-by 0036
date: 2026-08-12
deciders: ['@wcygan']
affects: databases
intent: learning
supersedes: [0034]
superseded-by: null
retrospective: false
review-by: 2026-09-10
---

# 0035 — Defer Airflow metadata backups

> Accept complete Airflow metadata loss while Anton remains an experimental learning cluster.

## Status

`Accepted`

## Context

This decision supersedes ADR 0034. Ticket 04 proved the Airflow control plane,
KubernetesExecutor task isolation, and metadata persistence during a scheduler
replacement. No Barman `ObjectStore` or database plugin consumer exists.

Anton is an experimental cluster. Current Airflow metadata is disposable. The
cost of an independent backup target and restore drills exceeds its present
value. Longhorn replication can tolerate some node failures, but it is not a
backup and cannot recover metadata after storage or cluster loss.

ADR 0033 still requires backup and restore before an authoritative lakehouse
cutover. This decision only removes backup and restore from Ticket 04.

## Decision

We will defer Airflow metadata backup and restore during the current learning
phase. We will remove the unused Barman Cloud plugin and accept total metadata
loss if the CNPG volume is lost.

## Alternatives considered

- **Keep the unused plugin** — rejected because it adds a controller and CRD without a consumer.
- **Use SeaweedFS in Anton** — rejected because it shares the cluster failure domain.
- **Use an independent S3 target** — deferred until the metadata has durable value.

## Consequences

### Accepted costs

- A CNPG volume loss can remove all Airflow history, task state, and metadata.
- Git, pinned images, DAGs, and 1Password data can rebuild the service, not its history.
- The current recovery point objective permits complete metadata loss.
- Recovery time includes GitOps reconciliation and database initialization.
- Ticket 04 cannot claim backup or disaster-recovery coverage.
- Backup and restore remain required before authoritative cutover under ADR 0033.

## Follow-ups

- [ ] Remove the unused Barman Cloud plugin and its cluster-wide CRD.
- [ ] Record the accepted risk in Ticket 04 and the Airflow documentation.
- [ ] Reassess the risk during the 2026-09-10 learning review.
- [ ] Add an independent backup target before authoritative cutover.
