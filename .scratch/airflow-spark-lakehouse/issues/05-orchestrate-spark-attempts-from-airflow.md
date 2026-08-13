# 05 — Orchestrate Spark Attempts from Airflow

**What to build:** Let one Airflow Workflow Run create, observe, recover, retry, and cancel uniquely identified Spark Attempts without direct `spark-submit` orchestration.

**Blocked by:** 02 — Run the shadow fixture through SparkApplication; 04 — Run the Airflow Kubernetes foundation.

**Status:** resolved

- [x] A typed deferrable Airflow adapter creates and watches Apache `SparkApplication` resources.
- [x] The adapter uses generic Kubernetes custom-resource facilities and not legacy Spark integrations.
- [x] A Spark Attempt name contains bounded DAG and task prefixes, a stable identity hash, and the Airflow try number.
- [x] The identity hash uses DAG, run, task, and map identities with NUL separators.
- [x] The same Airflow try maps to the same custom resource, while a new try maps to a new custom resource.
- [x] Full Airflow identities appear in annotations and bounded identities appear in labels.
- [x] Driver and executor pod templates receive the same correlation identity.
- [x] A target-specific Kubernetes Lease permits one active writer.
- [x] The deferred trigger renews the Lease and records the exact Spark Attempt as holder.
- [x] Lease takeover requires expiry and proof that the prior Spark application is inactive.
- [x] Active attempts reattach, succeeded attempts advance, failed attempts report diagnostics, and ambiguous attempts fail closed.
- [x] `stateTransitionHistory` defines outcome; `ResourceReleased` alone does not.
- [x] Cancellation collects bounded diagnostics, deletes the exact custom resource, verifies stop, and then releases the Lease.
- [x] Airflow receives only custom-resource, Lease, pod-read, pod-log, and event-read permissions in the workload namespace.
- [x] The DAG defines `23 * * * *` UTC, disables catchup, and permits one active Workflow Run.
- [x] The adapter contract covers identity, state, Lease, retry, recovery, and cancellation behavior.

## Comments

- 2026-08-13: The focused Airflow image test passed all 21 adapter and recovery tests.
- The tests cover identity, correlation, watches, Lease safety, retry, recovery, cancellation, and schedule bounds.
- Flux applied revision `67f7be0f` to the ready Airflow and lakehouse resources.
- Scheduled run `scheduled__2026-08-13T16:23:00+00:00` created one shadow Spark Attempt.
- The attempt reached `Succeeded` before `ResourceReleased` and retained full Airflow identity.
- Airflow task receipts recorded submission, Lease renewal, state changes, terminal state, and task completion.
- The read-only evidence is in `evidence/ticket06-readonly-audit-20260813/ledger.json`.
