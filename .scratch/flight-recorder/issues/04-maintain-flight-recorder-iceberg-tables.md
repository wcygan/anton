# 04 — Maintain Flight Recorder Iceberg tables

**What to build:** Run one manual maintenance Workflow Run that removes expired Flight Recorder data without changing retained rows or unrelated tables.

**Blocked by:** 01 — Prove one manual Flight Recorder slice.

**Status:** ready-for-agent

- [ ] The maintenance Spark Attempt uses the authoritative writer Lease.
- [ ] Complete event partitions older than seven days are removed from the current table state.
- [ ] Complete summary and run-receipt partitions older than fourteen days are removed.
- [ ] Current rows and the accepted query windows remain unchanged after maintenance.
- [ ] Snapshot expiration runs after row validation and keeps at least 24 hours and two snapshots.
- [ ] Branches and tags are inspected before snapshot expiration.
- [ ] The run records table bytes, snapshot identifiers, deleted partitions, and its completion time.
- [ ] Ingestion can detect a maintenance success record older than 48 hours and stop safely.
- [ ] Read-only Trino checks confirm the maintained schemas, counts, partitions, and snapshots.
- [ ] Automatic data-file compaction remains disabled until measurements show a need.
- [ ] Focused tests and repository contracts pass.
