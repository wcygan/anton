# 08 — Add the Loki-source workflow

**What to build:** Add bounded Loki ingestion as an Airflow-owned Workflow Run that reuses the proven Spark, Iceberg, Trino, retry, and observability contracts.

**Blocked by:** 07 — Pass the five-run shadow gate.

**Status:** ready-for-human

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

- Implemented the bounded Loki extractor, deterministic raw snapshot writer, and shadow-only `LokiSourceSparkOperator`.
- Added the manual `airflow_loki_source` DAG with a five-minute window and a 1000-entry completeness fence.
- Added bucket-scoped ESO credentials in `airflow` and `lakehouse`; Spark uses bucket-specific S3A credentials for raw input and event logs.
- Reused the fail-closed prior-output validator for same-window retries; raw JSONL retains Loki stream labels for correlation evidence.
- The Airflow image test stage passed 26 tests, and `mise exec -- task contracts:validate` passed 207 repository tests.
- The local Spark runtime image build passed its runtime contract; no image was published or pinned in Git.
- Live acceptance remains pending: publish the rebuilt Airflow and Spark images, update their immutable digests, pass Ticket 07, reconcile Flux, and retain one approved source run with Trino evidence.
