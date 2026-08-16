---
name: airflow-spark-lakehouse
description: >-
  Operate Anton's Airflow-owned Spark lakehouse workflow. Use for Workflow Run
  or Spark Attempt diagnosis, Flight Recorder runs, exact-window retries,
  shadow-gate evidence, writer cutover, retention, or cleanup.
---

# Airflow Spark Lakehouse

Goal: Operate one Airflow-owned lakehouse workflow without losing identity,
evidence, or single-writer safety.

Success means:

- One Workflow Run and Spark Attempt are traced by exact identity.
- Retry, Lease, Trino, Loki, and History Server evidence agrees.
- Any writer transfer preserves one authoritative writer.

Stop when: the selected workflow reaches its evidence gate, or another
authority boundary requires operator approval.

## Authority

- ADR 0036 owns the Airflow and Apache Spark Operator decision.
- Plan 0023 owns the mutable rollout and removal sequence.
- `.scratch/airflow-spark-lakehouse/spec.md` owns implementation acceptance.
- `images/airflow-runtime/src/anton_airflow/` owns workflow behavior.
- `scripts/lib/airflow_shadow_gate.py` owns retained gate validation.
- `scripts/lib/flight_recorder_evidence.py` owns live Flight Recorder evidence policy.
- `scripts/airflow-lakehouse.py` owns the evidence command boundary.

Use `seaweedfs-iceberg-data-access` for table-level Spark and Trino work.
Use `seaweedfs-iceberg-lakehouse` for storage, catalog, and Harbor work.
Use `query-kubernetes-logs` for detailed Loki queries.

## Read the matching branch

- Read [workflow-state-and-retry.md](references/workflow-state-and-retry.md)
  for identity, watch, Lease, retry, cancellation, or source-window work.
- Read [shadow-gate-evidence.md](references/shadow-gate-evidence.md) for
  evidence collection, validation, candidate changes, or gate failures.
- Read [flight-recorder-acceptance.md](references/flight-recorder-acceptance.md)
  for a manual Flight Recorder run, replay, or acceptance check.
- Read [live-recovery-scenarios.md](references/live-recovery-scenarios.md) for
  scheduler, triggerer, retry, cancellation, Lease, or pre-commit tests.
- Read [cutover-and-cleanup.md](references/cutover-and-cleanup.md) for writer
  transfer, observation, legacy removal, or experiment cleanup.

## Safety boundaries

- Start with read-only repository and cluster checks.
- Treat `exec`, port-forward, Workflow Run creation, and reconcile as live mutations.
- Obtain explicit approval before each live mutation.
- Keep credential values out of commands, output, evidence, and files.
- Keep repository edits, credential work, Flux actions, and data deletion separate.
- Record the exact target, namespace, revision, time window, and cleanup owner.
- Fail closed when application state, Lease ownership, or commit state is ambiguous.

## Read-only pulse

```sh
mise exec -- kubectl config current-context
mise exec -- flux get ks -A | rg 'airflow|spark-operator|spark-history|trino'
mise exec -- flux get hr -A | rg 'airflow|spark-operator|trino'
mise exec -- kubectl -n airflow get pods
mise exec -- kubectl -n lakehouse get sparkapplications,pods,leases
```

Expected state depends on the active rollout phase. Compare it with Plan 0023
and the current ticket before interpreting a missing resource.

Use the exact-attempt collector for retained and live evidence:

```sh
mise exec -- task airflow:attempt-evidence \
  RUN_ID=<exact-run-id> TARGET=authoritative
```

## Diagnose one workflow

1. Record the DAG ID, run ID, task ID, map index, and try number.
2. Record the target, source window, candidate revision, and image digests.
3. Resolve the exact Spark Attempt and writer Lease.
4. Trace Airflow, SparkApplication, driver, executor, Trino, Loki, and history evidence.
5. Stop at the earliest failing layer.
6. Select the matching reference before proposing a retry or mutation.

Use generation, identity, revision, and verified dependencies to connect events.
Timestamp proximity alone does not prove causality.

## Repository validation

```sh
mise exec -- python3 -m unittest scripts.tests.test_airflow_shadow_gate
mise exec -- python3 -m unittest scripts.tests.test_airflow_lakehouse_operations
mise exec -- task airflow:shadow-gate \
  LEDGER=.scratch/airflow-spark-lakehouse/evidence/shadow-gate-20260813-rotated/ledger.json
mise exec -- task contracts:validate
```

Repository checks do not authorize a Workflow Run, reconcile, credential change,
writer cutover, or data deletion.

## Report format

```text
Status: passed | failed | blocked
Workflow Run: <DAG, run, task, try, target>
Spark Attempt: <name, state, Lease holder>
Evidence: <Trino, Loki, History Server, candidate, credential epoch>
Cause: <earliest supported failing layer>
Changes: <repository paths only>
Approval needed: <exact live or external action, if any>
Residual risk: <unverified recurrence or retention window>
```
