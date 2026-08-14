# Cutover and Cleanup

Use this reference for Tickets 10 and 11. Treat every writer change as a
separate repository, Flux, and live-operation authority boundary.

## Cutover preconditions

- The accepted five-run shadow gate passes.
- Failure, retry, cancellation, Lease, and recovery tests pass.
- Airflow scheduling is paused.
- The legacy writer change is ready in Git.
- No legacy Job, driver, executor, or submission pod remains active.
- Authoritative schemas, counts, locations, and snapshots are retained.

## Single-writer transfer

1. Pause Airflow scheduling through its authoritative owner.
2. Suspend the legacy writer through Git.
3. Obtain approval for Flux reconciliation.
4. Prove that all legacy writer work stopped.
5. Record authoritative table state.
6. Change Airflow to the authoritative target through Git.
7. Run one approved manual authoritative Workflow Run.
8. Require read-only Trino validation.
9. Remove the legacy writer configuration through Git.
10. Obtain approval for Flux reconciliation.
11. Verify that Flux removed all legacy writer workloads.
12. Enable scheduling only after legacy removal passes.

At no point can both writers hold authoritative write access.

## Observation gate

Observe 24 consecutive scheduled runs across at least 24 hours. Every run must
pass Spark, Iceberg, Trino, Loki, and History Server checks.

Reset the observation window after an unexplained failure. Record peak resource
use before changing a request, limit, or replica count.

## Cleanup boundaries

- Remove the shadow control plane after the observation gate passes.
- Preserve retained acceptance evidence through the learning review.
- Keep authoritative Iceberg data during platform removal.
- Require separate storage approval before bucket deletion.
- Verify `deletecollection` access before Spark resource cleanup.
- Remove temporary port-forwards and diagnostic resources after each operation.
- Review the learning platform by 2026-09-10.

Permanent retention requires a new concrete-need intake decision. Additional
learning permits one explicit time-box extension.

## Completion evidence

Retain Git and Flux revisions, writer identities, Lease state, manual and
scheduled run identities, Trino results, legacy removal, and cleanup status.
