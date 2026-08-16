# 02 — Capture one complete lakehouse platform hour

**What to build:** Capture one closed hour of lakehouse platform logs and process its complete manifest through one manual Spark Attempt.

**Blocked by:** 01 — Prove one manual Flight Recorder slice.

**Status:** agent-active

- [ ] The Workflow Run selects the previous closed UTC hour from an explicit source-window end.
- [ ] The hour contains twelve five-minute chunks for workflow, Spark Operator, Trino, and SeaweedFS queries.
- [ ] Each component query has an independent entry, response-size, and timeout fence.
- [ ] All 48 source queries must succeed before the complete source manifest is published.
- [ ] A missing, failed, or oversized query rejects the complete hour and prevents a Spark Attempt.
- [ ] A rejected hour remains visible through Airflow evidence and never becomes a partial Iceberg result.
- [ ] One Spark Attempt reads only the completed source manifest.
- [ ] Source, accepted, rejected, deduplicated, and written counts reconcile for every component.
- [ ] Manual exact-hour replay remains available while Loki retains the source records.
- [x] Focused tests and repository contracts pass.

## Comments

- 2026-08-15: Local implementation captures four components across 12 chunks and publishes the complete manifest last.
- 2026-08-15: Spark validates all 48 retained child sources before table creation or writes.
- 2026-08-15: Component receipts reconcile source, accepted, rejected, deduplicated, and written counts.
- 2026-08-15: Focused suites passed 81 tests. Repository contracts passed 276 tests.
- 2026-08-15: Rejection evidence bypasses the Ticket 02 schema and proves no Spark resource or active Lease.
- 2026-08-15: Complete-hour source data has a 32 MiB aggregate limit and ambiguity-safe immutable publication.
- 2026-08-15: Image publication, Flux rollout, one manual hour, and exact replay remain approval-gated.
- 2026-08-16: Image publication and Flux rollout reached manual attempts. No complete-hour acceptance or exact replay passed.
- 2026-08-16: The first rejection result was complete. A later result became incomplete after task-pod retention removed strict identity evidence.
- 2026-08-16: A later attempt exposed an Airflow image that embedded the prior Spark digest. Acceptance stopped before an accepted Spark write.
- 2026-08-16: The retained `logs` namespace snapshots were identical before and after the failed digest attempt.
- 2026-08-16: Rebuild Airflow after the final Spark pin. Verify the embedded and live digests before the next manual hour.
