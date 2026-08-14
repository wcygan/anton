# 11 — Observe the authoritative workflow and clean the shadow path

**What to build:** Verify authoritative scheduling, then remove the shadow control plane while preserving required evidence and data.

**Blocked by:** 10 — Cut over authoritative writer ownership.

**Status:** resolved

- [x] Airflow completes one authoritative scheduled Workflow Run.
- [x] The run passes Spark, Iceberg, Trino, Runtime Logs, and Application History checks.
- [x] Any unexplained failure blocks cleanup until its cause is known.
- [x] The authoritative Lease never has concurrent holders or an unverified takeover.
- [x] The verification run stays within the accepted learning ceilings, with peak use recorded.
- [x] The shadow control-plane configuration is removed through a reviewed Git change.
- [x] Shadow workloads are absent after approved Flux reconciliation.
- [x] Shadow data is not deleted without separate storage approval.
- [x] Plan evidence records the authoritative steady state and shadow cleanup.

## Comments

- Scheduled run `scheduled__2026-08-14T13:23:00+00:00` completed successfully in 61 seconds.
- Spark Attempt `lh-airflow-run-auth-a2e1e078723c-a1` passed with no conflicting Lease holder.
- Trino returned counts `5 / 5 / 5`. Schema, partitions, locations, and new snapshots matched the contract.
- Loki retained 736 samples with no error samples. History Server retained one completed application.
- Peak recorded memory was 278357606 bytes against a 1073741824-byte ceiling.
- Evidence is in `evidence/ticket11-scheduled-20260814/ledger.json`.
- Flux applied revision `a90d8dec` and removed all shadow control-plane resources.
- Airflow now uses image digest `sha256:afdbc98fa46cc28e403980bc3b13b364b2aaf2f67e5f8d1a4074d90f618eb919`.
- The stale shadow DAG metadata record was removed after its image file disappeared.
- No shadow storage data was deleted. Trino still returns `5 / 5 / 5`.
