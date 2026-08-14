# 11 — Observe the authoritative workflow and clean the shadow path

**What to build:** Prove stable authoritative scheduling, then remove the shadow control plane while preserving required evidence and data.

**Blocked by:** 10 — Cut over authoritative writer ownership.

**Status:** needs-triage

- [ ] Airflow completes 24 consecutive authoritative scheduled Workflow Runs across at least 24 hours.
- [ ] Every run passes Spark, Iceberg, Trino, Runtime Logs, and Application History checks.
- [ ] Any unexplained failure resets the observation window.
- [ ] The authoritative Lease never has concurrent holders or an unverified takeover.
- [ ] Resource use remains within the accepted learning ceilings, with peak use recorded.
- [ ] The shadow control-plane configuration is removed through a reviewed Git change.
- [ ] Shadow workloads are absent after approved Flux reconciliation.
- [ ] Shadow data is not deleted without separate storage approval.
- [ ] Plan evidence records the authoritative steady state and shadow cleanup.

## Comments
