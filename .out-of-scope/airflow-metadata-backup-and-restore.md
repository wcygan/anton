# Airflow metadata backup and restore

Anton does not require Airflow metadata backup or restore for the current lakehouse learning deployment.

## Why this is out of scope

Current workflow history and task state have no durable value. Anton accepts complete metadata loss under ADR 0036.

Git, pinned images, DAGs, and external secrets can rebuild the Airflow control plane. They do not restore historical workflow state.

An independent backup target and restore drills add operational work without protecting required data. Authoritative Iceberg data remains outside this decision.

## Prior requests

- Ticket 09 — Prove Airflow metadata backup and restore.
