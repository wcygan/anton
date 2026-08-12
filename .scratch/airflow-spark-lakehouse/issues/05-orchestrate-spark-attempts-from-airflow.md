# 05 — Orchestrate Spark Attempts from Airflow

**What to build:** Let one Airflow Workflow Run create, observe, recover, retry, and cancel uniquely identified Spark Attempts without direct `spark-submit` orchestration.

**Blocked by:** 02 — Run the shadow fixture through SparkApplication; 04 — Run the Airflow Kubernetes foundation.

**Status:** ready-for-agent

- [ ] A typed deferrable Airflow adapter creates and watches Apache `SparkApplication` resources.
- [ ] The adapter uses generic Kubernetes custom-resource facilities and not legacy Spark integrations.
- [ ] A Spark Attempt name contains bounded DAG and task prefixes, a stable identity hash, and the Airflow try number.
- [ ] The identity hash uses DAG, run, task, and map identities with NUL separators.
- [ ] The same Airflow try maps to the same custom resource, while a new try maps to a new custom resource.
- [ ] Full Airflow identities appear in annotations and bounded identities appear in labels.
- [ ] Driver and executor pod templates receive the same correlation identity.
- [ ] A target-specific Kubernetes Lease permits one active writer.
- [ ] The deferred trigger renews the Lease and records the exact Spark Attempt as holder.
- [ ] Lease takeover requires expiry and proof that the prior Spark application is inactive.
- [ ] Active attempts reattach, succeeded attempts advance, failed attempts report diagnostics, and ambiguous attempts fail closed.
- [ ] `stateTransitionHistory` defines outcome; `ResourceReleased` alone does not.
- [ ] Cancellation collects bounded diagnostics, deletes the exact custom resource, verifies stop, and then releases the Lease.
- [ ] Airflow receives only custom-resource, Lease, pod-read, pod-log, and event-read permissions in the workload namespace.
- [ ] The DAG defines `23 * * * *` UTC, disables catchup, and permits one active Workflow Run.
- [ ] The adapter contract covers identity, state, Lease, retry, recovery, and cancellation behavior.

## Comments
