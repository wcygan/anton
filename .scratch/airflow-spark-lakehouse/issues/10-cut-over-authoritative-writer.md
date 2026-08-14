# 10 — Cut over authoritative writer ownership

**What to build:** Transfer authoritative Iceberg writer ownership from the legacy CronJob to Airflow with one controlled manual Workflow Run and no overlap.

**Blocked by:** 08 — Add the Loki-source workflow.

**Status:** ready-for-agent

- [ ] Airflow scheduling is paused before writer ownership changes.
- [ ] The legacy writer is suspended through Git and approved Flux reconciliation.
- [ ] No legacy submission, Job, driver, or executor remains active before transfer.
- [ ] Authoritative table snapshots, locations, schemas, counts, and Trino results are recorded before transfer.
- [ ] Airflow receives authoritative target configuration only after the legacy writer stops.
- [ ] One manual authoritative Workflow Run acquires the authoritative Lease.
- [ ] The manual run completes Spark writing and read-only Trino validation.
- [ ] The legacy writer configuration is removed through a separate reviewed Git change.
- [ ] Approved Flux reconciliation removes every legacy writer workload.
- [ ] Obsolete legacy workload resources are removed without deleting authoritative Iceberg data.
- [ ] The Airflow schedule is enabled only after legacy removal passes verification.
- [ ] At no point are two authoritative writers active.
- [ ] The exact Git revision, Flux revision, resource identities, and table evidence are retained.

## Comments
