---
status: In-progress
opened: 2026-08-06
closed: null
affects: demos
intent: learning
related-adrs: [0031]
review-by: 2026-08-20
---

# 0020 — Implement SeaweedFS Iceberg log lakehouse demo

> Build and validate a GitOps-managed Spark, Iceberg, SeaweedFS, and Trino log-processing demo before the learning review date.

## Goal

Anton can process a deterministic JSONL log fixture into `logs.normalized` and `logs.hourly` Iceberg tables stored in SeaweedFS, with SeaweedFS's built-in Iceberg REST catalog serving Spark and Trino. All durable configuration is managed from Git with Flux and ESO; no Polaris, separate metastore, streaming broker, or manual UI setup is required. If the fixture path is successful, a Loki snapshot source can be added without changing the table or query contracts. If the learning goal is not met by 2026-08-20, remove the demo using its cleanup procedure and close the plan as abandoned.

## Acceptance criteria

- [ ] SeaweedFS exposes a working Iceberg REST endpoint through a declarative Kubernetes Service, and both Spark and Trino can reach it.
- [ ] Flux reconciles the lakehouse buckets, credentials, Spark workload, and Trino catalog without manual UI configuration or hand-created runtime state.
- [ ] The deterministic fixture produces both Iceberg tables, and a Trino aggregate returns the expected results from the same tables Spark wrote.
- [ ] Re-running the same input is idempotent or explicitly deduplicated, while new input creates a new Iceberg snapshot.
- [ ] The demo has a documented validation and cleanup path, with evidence captured before the 2026-08-20 review.

## Tasks

### Phase 0: Verify the catalog path

- [ ] Inspect the pinned SeaweedFS image and operator schema for the built-in Iceberg REST port and required arguments.
- [ ] Choose the smallest declarative overlay: operator arguments plus an internal Service, or a documented fallback if the operator cannot expose the endpoint cleanly.
- [ ] Confirm current SeaweedFS S3 health, available capacity, and cluster resource headroom before adding workloads.

### Phase 1: Add lakehouse storage and credentials

- [ ] Define dedicated raw and warehouse buckets through the SeaweedFS bucket API/CRD without reusing Harbor's bucket.
- [ ] Define least-privilege S3 identities or ESO-backed credentials for the demo workloads.
- [ ] Add the catalog endpoint Service and a read/write smoke-test Job.

### Phase 2: Build the Spark fixture pipeline

- [ ] Create a pinned Harbor image containing Spark, PySpark, Iceberg, and S3-compatible filesystem dependencies.
- [ ] Add deterministic JSONL fixture data and the Spark transformation code.
- [ ] Add a native Kubernetes Spark Job or CronJob that writes `logs.normalized` and `logs.hourly`.
- [ ] Validate schemas, row counts, partitions, and Iceberg metadata locations.

### Phase 3: Add Trino queries

- [ ] Add the official Trino HelmRelease using the repository's Flux app pattern.
- [ ] Configure a Git-managed Iceberg catalog pointing to SeaweedFS's REST endpoint and S3 warehouse.
- [ ] Keep Trino internal-only and inject credentials through ESO/environment references.
- [ ] Add a repeatable SQL validation query and compare results with Spark output.

### Phase 4: Validate and document

- [ ] Run the full fixture flow from raw input through Trino.
- [ ] Re-run identical input and verify the duplicate/snapshot contract.
- [ ] Capture Flux, Spark, SeaweedFS, and Trino evidence in the implementation notes.
- [ ] Document operator-only cleanup, resource bounds, and known failure modes.

### Phase 5: Optional Loki source

- [ ] Add a bounded Loki snapshot CronJob only after the fixture acceptance criteria pass.
- [ ] Write Loki snapshots to the raw bucket and reuse the existing Spark and Trino interfaces.
- [ ] Validate one real log window and keep Loki ingestion internal.

## Log

- 2026-08-06: Opened from ADR 0031 to turn the accepted demo architecture into a phased implementation and validation record.

## References

- Related ADR: `context/adrs/0031-adopt-seaweedfs-iceberg-log-demo.md`
- SeaweedFS source of truth: `kubernetes/apps/storage/seaweedfs-config/app/seaweed.yaml`
- SeaweedFS operator HelmRelease: `kubernetes/apps/storage/seaweedfs/app/helmrelease.yaml`
- SeaweedFS storage contracts: `kubernetes/apps/storage/AGENTS.md`
- Harbor image registry contract: `kubernetes/apps/registries/AGENTS.md`
- Trino official Kubernetes deployment: <https://trino.io/docs/current/installation/kubernetes.html>
- Iceberg REST catalog specification: <https://iceberg.apache.org/rest-catalog-spec/>
- Cluster validation: `flux get ks -A`, `flux get hr -A`, `kubectl get pods -A`
