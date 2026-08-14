---
status: Superseded-by 0037
date: 2026-08-13
deciders: ['@wcygan']
affects: all
intent: learning
supersedes: [0033, 0035]
superseded-by: null
retrospective: false
review-by: 2026-09-10
---

# 0036 — Continue the Airflow lakehouse without metadata recovery

> Airflow becomes the only maintained lakehouse workflow path without metadata recovery or a legacy writer fallback.

## Status

`Accepted`

## Context

ADR 0033 selected Airflow and Apache Spark Operator for Anton's lakehouse workflow. ADR 0035 accepted total Airflow metadata loss during learning.

Five consecutive shadow Workflow Runs passed with retained runtime evidence. The controlled recovery tests also passed. The new path is ready for writer cutover.

Current Airflow metadata has no durable value. Git, pinned images, DAGs, and external secrets can rebuild the control plane after metadata loss.

Maintaining metadata recovery and the legacy writer adds work without useful protection. Anton will continue learning on the new path after cutover.

## Decision

Anton will not require Airflow metadata backup or restore before authoritative cutover. The learning deployment accepts total Airflow metadata loss.

Anton will not keep a legacy writer fallback after cutover. The legacy writer must stop before Airflow receives authoritative write access.

One manual authoritative Workflow Run must pass Spark and read-only Trino validation. The legacy writer configuration can then be removed through Git.

The Airflow schedule can start after Flux removes the legacy writer. Later failures will be repaired on the Airflow and Spark Operator path.

This decision does not authorize live changes. Git changes, Flux actions, workload removal, and storage deletion remain separate authority boundaries.

## Alternatives considered

- **Prove metadata backup and restore** — rejected because current workflow metadata has no durable value.
- **Keep the legacy writer as a fallback** — rejected because Anton will maintain one workflow path after cutover.
- **Delay cutover** — rejected because the accepted shadow and recovery evidence supports the writer transfer.

## Consequences

### Accepted costs

- A CNPG volume loss can remove all Airflow history, task state, and metadata.
- In-flight work can require a new Workflow Run after control-plane recovery.
- Historical Airflow state cannot be restored after metadata loss.
- Legacy writer recovery is unavailable after its Git configuration is removed.
- Operators must repair failures on the Airflow and Spark Operator path.
- Authoritative Iceberg data and required evidence remain protected from control-plane cleanup.
- The learning deployment still requires review by 2026-09-10.

## Follow-ups

- [ ] Update Plan 0023, the implementation specification, and Tickets 09 through 12.
- [ ] Transfer writer ownership without concurrent authoritative writers.
- [ ] Remove the legacy writer through reviewed Git and approved Flux actions.
- [ ] Observe 24 authoritative scheduled runs across at least 24 hours.
- [ ] Complete the learning review by 2026-09-10.
