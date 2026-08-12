# 08 — Add the Loki-source workflow

**What to build:** Add bounded Loki ingestion as an Airflow-owned Workflow Run that reuses the proven Spark, Iceberg, Trino, retry, and observability contracts.

**Blocked by:** 07 — Pass the five-run shadow gate.

**Status:** ready-for-agent

- [ ] The Workflow Run captures one bounded Loki source window with explicit time limits.
- [ ] Source extraction cannot issue unbounded Loki queries or write authoritative Iceberg data during shadow validation.
- [ ] The extracted input reaches the established Spark normalization and hourly table interfaces.
- [ ] Spark remains the only Iceberg writer, and Trino remains read-only.
- [ ] Reprocessing the same source window follows the accepted idempotency contract.
- [ ] Correlation identity connects the Airflow task, Spark Attempt, Runtime Logs, and Application History.
- [ ] Trino validates schema, counts, partitions, snapshots, locations, and time travel for the resulting shadow data.
- [ ] Failure, retry, and cancellation preserve the same Lease and fail-closed behavior as the fixture workflow.
- [ ] One approved end-to-end source run retains bounded input details and complete validation evidence.

## Comments
