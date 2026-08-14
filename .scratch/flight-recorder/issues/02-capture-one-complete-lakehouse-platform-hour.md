# 02 — Capture one complete lakehouse platform hour

**What to build:** Capture one closed hour of lakehouse platform logs and process its complete manifest through one manual Spark Attempt.

**Blocked by:** 01 — Prove one manual Flight Recorder slice.

**Status:** ready-for-agent

- [ ] The Workflow Run selects the previous closed UTC hour from an explicit source-window end.
- [ ] The hour contains twelve five-minute chunks for workflow, Spark Operator, Trino, and SeaweedFS queries.
- [ ] Each component query has an independent entry, response-size, and timeout fence.
- [ ] All 48 source queries must succeed before the complete source manifest is published.
- [ ] A missing, failed, or oversized query rejects the complete hour and prevents a Spark Attempt.
- [ ] A rejected hour remains visible through Airflow evidence and never becomes a partial Iceberg result.
- [ ] One Spark Attempt reads only the completed source manifest.
- [ ] Source, accepted, rejected, deduplicated, and written counts reconcile for every component.
- [ ] Manual exact-hour replay remains available while Loki retains the source records.
- [ ] Focused tests and repository contracts pass.
