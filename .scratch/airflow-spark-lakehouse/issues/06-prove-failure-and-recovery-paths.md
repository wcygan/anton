# 06 — Prove failure and recovery paths

**What to build:** Prove that one Workflow Run remains diagnosable and safe across normal completion, fast container exit, pre-commit failure, retry, cancellation, and control-plane recovery.

**Blocked by:** 03 — Preserve Spark logs and Application History; 05 — Orchestrate Spark Attempts from Airflow.

**Status:** ready-for-agent

- [ ] A normal success run completes through Trino validation.
- [ ] A deliberately short-lived executor leaves complete Runtime Logs in Loki.
- [ ] A failure before Iceberg commit retains driver and executor diagnostics.
- [ ] Airflow task logs record submission, identity, state changes, terminal state, and bounded failure diagnostics.
- [ ] Loki contains unique Airflow, driver, and executor markers after all containers exit.
- [ ] History Server shows valid event history without relying on standard-output markers.
- [ ] Scheduler restart reattaches to the same Spark Attempt.
- [ ] Triggerer restart resumes observation and Lease renewal.
- [ ] Duplicate delivery does not create a second attempt for the same Airflow try.
- [ ] A bounded retry validates prior output before creating a new Spark Attempt.
- [ ] Cancellation prevents further Spark work and releases ownership only after stop.
- [ ] Expired Lease handling refuses takeover while the prior application remains active.
- [ ] Every controlled test retains identities, resource states, logs, and validation output.

## Comments

- 2026-08-12: Added bounded Spark Attempt receipts.
- Receipts record identity, submission, state changes, terminal state, Lease renewal, retry decisions, cancellation, and failure diagnostics.
- Added local adapter tests for success, failures, recovery, duplicate delivery, retry, cancellation, and expired Lease takeover.
- Prior-output reuse requires an independent `anton.io/prior-output-valid=true` marker.
- Local tests do not replace live Trino, Loki, History Server, or retention evidence.
