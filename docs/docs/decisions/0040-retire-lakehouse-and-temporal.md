---
status: Accepted
date: 2026-10-12
deciders: ['@wcygan']
affects: compute
intent: concrete-need
supersedes: [0039]
superseded-by: null
retrospective: false
edition: condensed-public
slug: /decisions/0040-retire-lakehouse-and-temporal
---

# 0040 — Retire the lakehouse and Temporal

> Remove the lakehouse and Temporal and delete their dedicated data, keeping shared platform services.

_Public edition condensed on 2026-10-21; original decision date and meaning retained._

## Context

The operator no longer used the Airflow and Spark lakehouse or Temporal, and authorized removing them through GitOps and permanently deleting their data. Recent inspection found failing scheduled Spark work, an unavailable History Server, and no visible Temporal workflows or schedules. Together, the unused workloads consumed meaningful CPU and memory.

## Decision

### Remove

- Airflow and its CNPG database
- Spark applications and the Spark Operator
- The History Server, Flight Recorder, and Trino
- Temporal and its CNPG volumes, including detached volumes

Delete only the dedicated lakehouse buckets—raw input, warehouse tables, shadow data, and Spark events—after writers stop and their bucket provisioning intent is removed.

### Keep

Longhorn, SeaweedFS, Harbor, Prometheus, Loki, the database operators, Goldilocks, Headlamp, and Hubble. Keep the shared S3 credentials and SeaweedFS configuration, which active services still use.

Historical code, skills, and evidence remain reference material, not deployed services. Remove retired command groups from the default task list. Re-adoption needs a new decision and deployment; the old runbooks do not authorize it.

## Alternatives considered

- **Keep the workloads:** no longer justified the maintenance.
- **Suspend them:** would keep data the operator asked to delete.
- **Also remove shared storage and registry:** would disrupt active consumers.

## Consequences

Data deletion is permanent; restoring Git definitions cannot bring it back. Retire the Spark Operator only after its namespaced resources finish deleting. Keep an execution record of revisions, absence checks, bucket inventory, and shared-platform health.
