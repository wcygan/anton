---
status: Superseded-by 0039
date: 2026-08-14
deciders: ['@wcygan']
affects: compute
intent: learning
supersedes: []
superseded-by: null
retrospective: false
review-by: 2026-09-15
---

# 0038 — Extend Airflow Spark lakehouse learning review

> Anton keeps the learning platform through 2026-09-15 to complete two bounded evidence checks.

## Status

`Accepted`

## Context

The scheduled authoritative run passed the full Ticket 11 evidence path.
Flux cleanup removed the shadow control plane without deleting shadow data.

Current Trino checks confirm the authoritative table contract and hourly snapshots.
Two learning checks remain incomplete.
The platform has not passed a concrete-need intake for permanent retention.

## Decision

Anton will extend the learning deployment once through 2026-09-15.
The extension will prove Spark 4.1.3 reads authoritative tables without writes.
It will also prove 30-day event-log retention and storage-owned expiry.

Anton will remove the learning platform after this date unless a concrete need passes intake.
The removal will preserve the authoritative warehouse, retained evidence, and the Trino read path.
Bucket or object deletion remains a separate storage decision.

## Alternatives considered

- **Keep permanently** — rejected because no concrete need has passed intake.
- **Remove now** — rejected because two bounded learning checks remain.
- **Extend without an end date** — rejected because learning work needs a fixed removal trigger.

## Consequences

### Accepted costs

- Operators maintain Airflow, Spark Operator, History Server, and CNPG through 2026-09-15.
- Airflow metadata loss remains an accepted risk under ADR 0037.
- Operators review image and chart upgrades during the extension.
- The platform must not receive more learning extensions.

## Follow-ups

- [ ] Prove a read-only Spark 4.1.3 read of authoritative tables.
- [ ] Verify event-log expiry after 30 days through the storage owner.
- [ ] Remove the platform unless a concrete need passes intake by 2026-09-15.
