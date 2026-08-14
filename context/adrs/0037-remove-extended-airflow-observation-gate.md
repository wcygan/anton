---
status: Accepted
date: 2026-08-14
deciders: ['@wcygan']
affects: all
intent: learning
supersedes: [0036]
superseded-by: null
retrospective: false
review-by: 2026-09-10
---

# 0037 — Remove the extended Airflow observation gate

> One scheduled authoritative run replaces the 24-hour observation gate before shadow cleanup.

## Status

`Accepted`

## Context

The writer cutover passed its manual authoritative run. Airflow now owns the
hourly schedule, and the legacy writer configuration is absent.

The learning rollout does not need a 24-hour delay before shadow cleanup. The
complete evidence path remains necessary for one scheduled run.

## Decision

Anton will not require Airflow metadata backup or restore during this learning
deployment. Total Airflow metadata loss remains an accepted risk.

Anton will not keep a legacy writer fallback. The legacy writer must stop
before Airflow receives authoritative write access.

One manual authoritative Workflow Run must pass Spark and read-only Trino
validation before writer cutover. Flux must then remove the legacy writer
configuration before the Airflow schedule starts.

Anton will verify one scheduled authoritative Workflow Run before shadow
control-plane removal. The run must pass Spark, Iceberg, Trino, Loki, History
Server, Lease, and resource checks.

An unexplained failure or conflicting Lease holder will block cleanup. Shadow
data deletion remains a separate storage authority boundary.

Later failures must be repaired on the Airflow and Spark Operator path. Git
changes, Flux actions, workload removal, and storage deletion remain separate
authority boundaries.

## Alternatives considered

- **Keep the 24-hour gate** — rejected because it adds delay without a current learning requirement.
- **Remove scheduled verification** — rejected because schedule ownership still needs one end-to-end proof.

## Consequences

### Accepted costs

- Airflow metadata loss can remove all Workflow Run and task state.
- Legacy writer recovery is unavailable after its Git configuration is removed.
- Extended recurrence evidence is not required before shadow cleanup.
- Later failures are repaired on the Airflow and Spark Operator path.
- The September learning review still evaluates reliability and maintenance cost.

## Follow-ups

- [x] Update Plan 0023, the specification, Ticket 11, and operator guidance.
- [x] Retain one complete scheduled verification record.
- [ ] Remove the shadow control plane without deleting shadow data.
