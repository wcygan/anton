# 10 — Observe and retire the legacy deployment

**What to build:** Prove stable authoritative scheduling, then remove the legacy lakehouse deployment while retaining the shadow environment for rollback evidence.

**Blocked by:** 09 — Cut over authoritative writer ownership.

**Status:** ready-for-agent

- [ ] Airflow completes 24 consecutive authoritative scheduled Workflow Runs across at least 24 hours.
- [ ] Every run passes Spark, Iceberg, Trino, Runtime Logs, and Application History checks.
- [ ] Any unexplained failure resets the observation window.
- [ ] The authoritative Lease never has concurrent holders or an unverified takeover.
- [ ] Resource use remains within the accepted learning ceilings, with peak use recorded.
- [ ] The legacy CronJob is removed only after the observation window passes.
- [ ] Remaining legacy namespace resources are removed through a separate reviewed Git change.
- [ ] The shadow environment remains available for seven additional days.
- [ ] Shadow data is not deleted without separate storage approval.
- [ ] Rollback instructions remain valid until the shadow retention period ends.
- [ ] Plan evidence records the final legacy removal and authoritative steady state.

## Comments
