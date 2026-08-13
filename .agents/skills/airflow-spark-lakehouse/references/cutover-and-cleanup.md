# Cutover and Cleanup

Use this reference for Tickets 09 through 11. Treat every writer change as a
separate repository, Flux, and live-operation authority boundary.

## Cutover preconditions

- The accepted five-run shadow gate passes.
- Failure, retry, cancellation, Lease, and recovery tests pass.
- Airflow scheduling is paused.
- The legacy writer change is ready in Git.
- No legacy Job, driver, executor, or submission pod remains active.
- Authoritative schemas, counts, locations, and snapshots are retained.
- The rollback change and verification commands are ready.

## Single-writer transfer

1. Pause Airflow scheduling through its authoritative owner.
2. Suspend the legacy writer through Git.
3. Obtain approval for Flux reconciliation.
4. Prove that all legacy writer work stopped.
5. Record authoritative table state.
6. Change Airflow to the authoritative target through Git.
7. Run one approved manual authoritative Workflow Run.
8. Require read-only Trino validation.
9. Enable scheduling only after manual validation passes.

At no point can both writers hold authoritative write access.

## Observation gate

Observe 24 consecutive scheduled runs across at least 24 hours. Every run must
pass Spark, Iceberg, Trino, Loki, and History Server checks.

Reset the observation window after an unexplained failure. Record peak resource
use before changing a request, limit, or replica count.

Remove the legacy writer only after the observation gate passes.

## Rollback

1. Pause Airflow.
2. Verify that its authoritative Spark work stopped.
3. Restore the legacy writer through Git.
4. Obtain approval for Flux reconciliation.
5. Verify that the legacy writer is the sole writer.
6. Resume its schedule only after read-only Trino validation.

The control-plane rollback target is 30 minutes. Backup recovery and data
deletion remain outside that target.

## Cleanup boundaries

- Keep the shadow environment for seven days after legacy removal.
- Preserve retained acceptance evidence through the learning review.
- Keep authoritative Iceberg data during rollback or platform removal.
- Require separate storage approval before bucket deletion.
- Verify `deletecollection` access before Spark resource cleanup.
- Remove temporary port-forwards and diagnostic resources after each operation.
- Review the learning platform by 2026-09-10.

Permanent retention requires a new concrete-need intake decision. Additional
learning permits one explicit time-box extension.

## Completion evidence

Retain Git and Flux revisions, writer identities, Lease state, manual and
scheduled run identities, Trino results, rollback readiness, and cleanup status.
