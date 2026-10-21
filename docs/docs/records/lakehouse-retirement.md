---
title: Lakehouse and workflow experiments
record_type: retirement
date: 2026-10-12
---

# Lakehouse and workflow experiments

## Outcome

In October 2026, Airflow, Spark, Trino, Flight Recorder, and Temporal were removed, along with their dedicated data. Shared storage, the registry, metrics, and Kubernetes logging stayed in place. [ADR 0040](../decisions/0040-retire-lakehouse-and-temporal.md) records the decision; ADRs 0031 through 0039 trace how the experiment grew.

## What we learned

- A learning workload needs a review date and an exit path. Keeping a stack with no active users adds maintenance and alert noise.
- Stop writers before deleting data.
- Keep an operator installed until the resources it manages finish finalizing.

## Limits

Git can restore the definitions but not the deleted data. The old lakehouse instructions describe a retired experiment and do not authorize recreating it.
