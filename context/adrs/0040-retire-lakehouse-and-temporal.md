---
status: Accepted
date: 2026-10-12
deciders: ['@wcygan']
affects: compute
intent: concrete-need
supersedes: [0039]
superseded-by: null
retrospective: false
---

# 0040 — Retire the lakehouse and Temporal

> Remove unused learning workloads and their data while preserving the shared platform.

## Status

`Accepted`

## Context

The operator no longer uses the Airflow/Spark lakehouse or Temporal and explicitly authorized GitOps removal and permanent deletion of their data on 2026-10-12. This supersedes ADR 0039's open-ended lakehouse retention decision.

The audit found hourly failing Spark work, an unavailable History Server, and no visible user workflows or schedules in Temporal. The combined baseline consumes about 0.55 CPU cores and 4.6 GiB memory.

## Decision

Remove Airflow and its CNPG database, Spark applications/operator/history server, Flight Recorder, Trino, and Temporal with all its CNPG volumes, including detached volumes. Delete only the dedicated SeaweedFS buckets `iceberg-raw`, `iceberg-warehouse`, `iceberg-shadow`, and `spark-events` after writers stop and provisioning intent is removed.

Keep Longhorn, SeaweedFS, Harbor, Prometheus, Loki, shared database operators, Goldilocks, Headlamp, and Hubble. Preserve shared S3 credentials and SeaweedFS runtime configuration to avoid disturbing Harbor or Loki. Historical application code, skills, and evidence remain reference material, not deployed services. Remove the retired command groups from the default Task surface.

## Alternatives considered

- **Keep running** — rejected because the learning value no longer offsets maintenance.
- **Suspend and retain data** — rejected; the operator explicitly requested data deletion.
- **Remove shared storage or registry services** — rejected because active platform consumers still require them.

## Consequences

### Accepted costs

- Data deletion is permanent. Reverting Git restores definitions, not deleted data.
- Keep the Spark operator until its namespace-scoped resources have finished deletion.
- Re-adoption requires a new decision and a fresh deployment; old runbooks do not authorize recreation.

## Follow-ups

- Record the deployed revisions, absence checks, bucket inventory, and shared-platform health in the retirement execution note.
