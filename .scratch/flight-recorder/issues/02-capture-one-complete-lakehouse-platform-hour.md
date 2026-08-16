# 02 — Capture one complete lakehouse platform hour

**What to build:** Capture one closed hour of lakehouse platform logs and process its complete manifest through one manual Spark Attempt.

**Blocked by:** 01 — Prove one manual Flight Recorder slice.

**Status:** resolved

- [x] The Workflow Run selects the previous closed UTC hour from an explicit source-window end.
- [x] The hour contains twelve five-minute chunks for workflow, Spark Operator, Trino, and SeaweedFS queries.
- [x] Each component query has an independent entry, response-size, and timeout fence.
- [x] All 48 source queries must succeed before the complete source manifest is published.
- [x] A missing, failed, or oversized query rejects the complete hour and prevents a Spark Attempt.
- [x] A rejected hour remains visible through Airflow evidence and never becomes a partial Iceberg result.
- [x] One Spark Attempt reads only the completed source manifest.
- [x] Source, accepted, rejected, deduplicated, and written counts reconcile for every component.
- [x] Manual exact-hour replay remains available while Loki retains the source records.
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
- 2026-08-16: The 17:00–18:00 UTC hour reached the 5,000-entry Trino fence at chunk 11 after 35 successful queries.
- 2026-08-16: Rejection evidence proved no complete manifest, Spark Application, active Lease, or partial Iceberg result.
- 2026-08-16: All 35 retained child manifests and raw objects passed exact size, checksum, count, and identity validation.
- 2026-08-16: The R-15 idempotent validation remained incomplete because the strict initial validator requires the original writer receipt identity.
- 2026-08-16: R-16 selected the unwritten 15:00–16:00 UTC hour after Trino receipt and entry-fence preflight passed.
- 2026-08-16: The initial manifest retained 6,282 events, 321 rejections, four components, 48 chunks, and checksum `218348be3774e26978fece48513433fe1d7a771a8de5306a6e8e14bd38924095`.
- 2026-08-16: Every component reconciled source, accepted, rejected, deduplicated, and written counts.
- 2026-08-16: Initial and replay Spark Attempts reached `RunningHealthy`, `Succeeded`, then `ResourceReleased`.
- 2026-08-16: Strict initial and replay evidence passed with exact Airflow and Spark image identities.
- 2026-08-16: Replay changed no event, receipt, component-count, hourly-row, Flight Recorder snapshot, or `logs` snapshot state.
