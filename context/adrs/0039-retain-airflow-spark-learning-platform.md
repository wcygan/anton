---
status: Accepted
date: 2026-08-14
deciders: ['@wcygan']
affects: compute
intent: learning
supersedes: [0038]
superseded-by: null
retrospective: false
---

# 0039 — Retain Airflow and Spark as a learning platform

> Anton keeps Airflow and Spark for open-ended operator learning and experiments.

## Status

`Accepted`

## Context

Plan 0023 completed the shadow rollout, recovery tests, writer cutover, scheduled run, and shadow control-plane cleanup.

A read-only Spark 4.1.3 check returned the expected table counts. Both authoritative snapshot identifiers remained unchanged.

The operator has no production need for this platform. The operator needs Airflow and Spark for continued learning and experiments.

The operator explicitly declined a review date. The operator also declined the 30-day expiry check and a future removal ticket.

This decision supersedes the fixed removal trigger in ADR 0038.

## Decision

Anton will retain Airflow, Spark Operator, History Server, and the Airflow CNPG cluster.

The platform is an open-ended learning system. It has no fixed review date or automatic removal trigger.

Spark remains the only Iceberg writer. Trino remains a read-only validation path.

The authoritative warehouse, current GitOps ownership, security controls, and storage boundaries remain unchanged.

No new ticket is required for event-log expiry or platform removal.

## Alternatives considered

- **Keep the fixed removal trigger** — rejected by the operator.
- **Remove the platform now** — rejected because the platform supports current learning.
- **Treat the platform as production** — rejected because no production need exists.

## Consequences

### Accepted costs

- This decision is an explicit exception to the usual learning timebox.
- Operators keep the current chart, image, and dependency maintenance work.
- Airflow metadata loss remains an accepted risk under ADR 0037.
- The 30-day event-log expiry remains unverified and is not a completion gate.
- The platform has no production service level or restore claim.
- A future operator decision can supersede this ADR and remove the platform.

## Follow-ups

- [x] Retain the Spark 4.1.3 read-only evidence.
- [x] Close Plan 0023 without new review or removal tickets.
