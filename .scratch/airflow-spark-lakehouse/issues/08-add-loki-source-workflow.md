# 08 — Add the Loki-source workflow

**What to build:** Add bounded Loki ingestion as an Airflow-owned Workflow Run that reuses the proven Spark, Iceberg, Trino, retry, and observability contracts.

**Blocked by:** 07 — Pass the five-run shadow gate.

**Status:** resolved

- [x] The Workflow Run captures one bounded Loki source window with explicit time limits.
- [x] Source extraction cannot issue unbounded Loki queries or write authoritative Iceberg data during shadow validation.
- [x] The extracted input reaches the established Spark normalization and hourly table interfaces.
- [x] Spark remains the only Iceberg writer, and Trino remains read-only.
- [x] Reprocessing the same source window follows the accepted idempotency contract.
- [x] Correlation identity connects the Airflow task, Spark Attempt, Runtime Logs, and Application History.
- [x] Trino validates schema, counts, partitions, snapshots, locations, and time travel for the resulting shadow data.
- [x] Failure, retry, and cancellation preserve the same Lease and fail-closed behavior as the fixture workflow.
- [x] One approved end-to-end source run retains bounded input details and complete validation evidence.

## Comments

- Implemented the bounded Loki extractor, deterministic raw snapshot writer, and shadow-only `LokiSourceSparkOperator`.
- Added the manual `airflow_loki_source` DAG with a five-minute window and a 1000-entry completeness fence.
- Added bucket-scoped ESO credentials in `airflow` and `lakehouse`; Spark uses bucket-specific S3A credentials for raw input and event logs.
- Reused the fail-closed prior-output validator for same-window retries; raw JSONL retains Loki stream labels for correlation evidence.
- The Airflow image test stage passed 26 tests, and `mise exec -- task contracts:validate` passed 207 repository tests.
- Published `airflow-runtime:3.2.2-ticket08.1` at digest `sha256:033982a99d850a01f35c7dc98638db9aa4769eb7e228e182b103b89a42b7e80d` and `spark-runtime:4.1.3-ticket08.1` at digest `sha256:77a9e545a49b5eb6ea23fe8e92d78f1ef751ea5aae5a209afd02e0caa46beaf3`.
- Pinned both published digests in Git and removed the Spark image's recursive ownership layer so source rebuilds do not transfer duplicate runtime data.
- Ticket 07 passed with the accepted post-rotation five-run ledger.
- The approved run captured 298 Loki entries in a five-minute window and wrote only shadow tables.
- Trino observed 303 normalized rows, four hourly rows, and an hourly event sum of 298.
- The exact-window retry reused the source object checksum and retained the normalized count of 303.
- Complete retained evidence is in `evidence/loki-source-20260813/`.
