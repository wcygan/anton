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
edition: condensed-public
slug: /decisions/0037-remove-extended-airflow-observation-gate
---

# 0037 — Remove the extended Airflow observation gate

> Drop the 24-hour observation wait, but still require one fully verified scheduled run before shadow cleanup.

_Public edition condensed on 2026-10-21; original decision date and meaning retained._

## Context

The manual authoritative run had passed, Airflow owned the schedule, and the legacy writer configuration was gone. The rollout still needed proof from one complete scheduled run. Waiting a further 24 hours before shadow cleanup added delay without serving any learning goal.

## Decision

Keep accepting complete Airflow metadata loss, and keep no legacy writer fallback.

- **Before cutover:** one manual authoritative Workflow Run must pass Spark and read-only Trino validation, and Flux must remove the legacy writer before the Airflow schedule starts.
- **Before removing the shadow control plane:** verify one scheduled authoritative run across Spark, Iceberg, Trino, Loki, the History Server, Leases, and resource checks.

An unexplained failure or conflicting Lease ownership blocks cleanup. Deleting shadow data remains a separate storage decision.

## Alternatives considered

- **Keep the 24-hour observation gate:** delay with no learning value.
- **Drop scheduled verification entirely:** schedule ownership still needs end-to-end evidence.

## Consequences

Metadata loss and the loss of the legacy recovery path remain accepted costs. Only the extended observation period is removed; a full scheduled verification is still required. The decision stays subject to the September learning review, and later ADRs revisit the platform's duration and retirement.
