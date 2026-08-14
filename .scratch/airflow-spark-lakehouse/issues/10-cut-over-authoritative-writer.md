# 10 — Cut over authoritative writer ownership

**What to build:** Transfer authoritative Iceberg writer ownership from the legacy CronJob to Airflow with one controlled manual Workflow Run and no overlap.

**Blocked by:** 08 — Add the Loki-source workflow.

**Status:** resolved

- [x] Airflow scheduling is paused before writer ownership changes.
- [x] The legacy writer is suspended through Git and approved Flux reconciliation.
- [x] No legacy submission, Job, driver, or executor remains active before transfer.
- [x] Authoritative table snapshots, locations, schemas, counts, and Trino results are recorded before transfer.
- [x] Airflow receives authoritative target configuration only after the legacy writer stops.
- [x] One manual authoritative Workflow Run acquires the authoritative Lease.
- [x] The manual run completes Spark writing and read-only Trino validation.
- [x] The legacy writer configuration is removed through a separate reviewed Git change.
- [x] Approved Flux reconciliation removes every legacy writer workload.
- [x] Obsolete legacy workload resources are removed without deleting authoritative Iceberg data.
- [x] The Airflow schedule is enabled only after legacy removal passes verification.
- [x] At no point are two authoritative writers active.
- [x] The exact Git revision, Flux revision, resource identities, and table evidence are retained.

## Comments

- Commits `a19df868` through `95967bd6` completed the ordered writer cutover.
- Manual run `manual__ticket10_authoritative_20260814T1247Z` completed successfully.
- Spark Attempt `lh-airflow-run-auth-af00693afbad-a1` held the authoritative Lease.
- Trino retained the pre-run and post-run table evidence without a storage deletion.
