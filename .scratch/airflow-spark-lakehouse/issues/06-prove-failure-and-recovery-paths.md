# 06 — Prove failure and recovery paths

**What to build:** Prove that one Workflow Run remains diagnosable and safe across normal completion, fast container exit, pre-commit failure, retry, cancellation, and control-plane recovery.

**Blocked by:** 03 — Preserve Spark logs and Application History; 05 — Orchestrate Spark Attempts from Airflow.

**Status:** resolved

- [x] A normal success run completes through Trino validation.
- [x] A deliberately short-lived executor leaves complete Runtime Logs in Loki.
- [x] A failure before Iceberg commit retains driver and executor diagnostics.
- [x] Airflow task logs record submission, identity, state changes, terminal state, and bounded failure diagnostics.
- [x] Loki contains unique Airflow, driver, and executor markers after all containers exit.
- [x] History Server shows valid event history without relying on standard-output markers.
- [x] Scheduler restart reattaches to the same Spark Attempt.
- [x] Triggerer restart resumes observation and Lease renewal.
- [x] Duplicate delivery does not create a second attempt for the same Airflow try.
- [x] A bounded retry validates prior output before creating a new Spark Attempt.
- [x] Cancellation prevents further Spark work and releases ownership only after stop.
- [x] Expired Lease handling refuses takeover while the prior application remains active.
- [x] Every controlled test retains identities, resource states, logs, and validation output.

## Comments

- 2026-08-12: Added bounded Spark Attempt receipts.
- Receipts record identity, submission, state changes, terminal state, Lease renewal, retry decisions, cancellation, and failure diagnostics.
- Added local adapter tests for success, failures, recovery, duplicate delivery, retry, cancellation, and expired Lease takeover.
- Prior-output reuse requires an independent `anton.io/prior-output-valid=true` marker.
- Local tests do not replace live Trino, Loki, History Server, or retention evidence.
- 2026-08-13: The read-only audit accepted normal success, short-life logs, and History Server evidence.
- The accepted Ticket 07 ledger supplies Trino and normal success evidence.
- A current 14.833-second application retained 736 driver and 399 executor Loki samples after exit.
- History Server retained the completed application and its 3.413-second executor.
- The 04:23 UTC failure did not prove Ticket 06 failure handling.
- That run had no executor evidence and recorded empty Airflow failure diagnostics.
- At the read-only audit, restart, duplicate, retry, cancellation, Lease, failure, and retention tests remained open.
- The partial ledger is `evidence/ticket06-readonly-audit-20260813/ledger.json`.
- 2026-08-13: Approved shadow-only recovery tests resolved the remaining acceptance checks.
- Scheduler replacement preserved one Spark Attempt and completed the Workflow Run.
- Triggerer replacement renewed a held Lease after startup, then completed the same Spark Attempt.
- Duplicate delivery emitted `reattach` and created no second custom resource.
- Retry validation rejected prior-output reuse and created try number two.
- Cancellation stopped the exact resource before Lease release.
- Expired Lease takeover was refused while the prior resource remained active.
- The accepted pre-commit failure retained one failed driver and one completed executor.
- Airflow retained two diagnostic records and a 4000-character bounded task diagnostic.
- Loki retained 65 Airflow, 66 driver, and 56 executor samples after exit.
- The shadow snapshot stayed `6584017577001615138` across the accepted failure.
- Ticket 03 supplies the accepted 24-hour and bounded-cleanup retention tests.
- The complete live ledger is `evidence/ticket06-live-20260813/ledger.json`.
