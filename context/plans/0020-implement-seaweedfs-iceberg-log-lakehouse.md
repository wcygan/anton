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

- [x] SeaweedFS exposes a working Iceberg REST endpoint through a declarative Kubernetes Service, and both Spark and Trino can reach it.
- [x] Flux reconciles the lakehouse buckets, credentials, Spark workload, and Trino catalog without manual UI configuration or hand-created runtime state.
- [x] The deterministic fixture produces both Iceberg tables, and a Trino aggregate returns the expected results from the same tables Spark wrote.
- [x] Re-running the same input is idempotent or explicitly deduplicated, while new input creates a new Iceberg snapshot. Two live Spark runs kept both row counts at five; because normalized uses `MERGE` and hourly uses a bounded delete/insert workaround, successful reruns add snapshots even when the final row set is unchanged.
- [x] The demo has a documented validation and cleanup path, with evidence captured before the 2026-08-20 review.

## Tasks

### Phase 0: Verify the catalog path

- [x] Inspect the pinned SeaweedFS image and operator schema for the built-in Iceberg REST port and required arguments. The live image is `chrislusf/seaweedfs:4.40`, the operator chart is `0.1.36` / image `1.0.33`, the CRD exposes `spec.s3.extraArgs`, and `weed s3 -h` exposes `-port.iceberg` on 8181.
- [x] Choose the smallest declarative overlay: `spec.s3.extraArgs: [-port.iceberg=8181]` plus the internal `seaweedfs-iceberg` ClusterIP Service selecting the operator-managed S3 pods. The generated S3 Service remains unchanged on 8333.
- [x] Confirm current SeaweedFS S3 health, available capacity, and cluster resource headroom before adding workloads. Read-only inspection found Seaweed Ready (3/3 masters, 3/3 volumes, 2/2 filers, 2/2 S3), S3 health 200, 11 free volume slots, roughly 288 GiB free across the three PVCs, and 10–11% CPU / 12–15% memory node usage.

### Phase 1: Add lakehouse storage and credentials

- [x] Define dedicated raw and warehouse buckets through the SeaweedFS bucket API/CRD without reusing Harbor's bucket. The live provisioner created ordinary `iceberg-raw` and S3 Table bucket `iceberg-warehouse`.
- [x] Define least-privilege S3 identities or ESO-backed credentials for the demo workloads. The `seaweedfs-iceberg` item is synced by ESO, and the raw identity passed the live S3 write/read/delete smoke test.
- [x] Add the catalog endpoint Service and a read/write smoke-test Job. The live `seaweedfs-iceberg` Service is on port 8181, and the storage smoke Job completed successfully.

### Phase 2: Build the Spark fixture pipeline

- [x] Create pinned Harbor images containing Spark, PySpark, Iceberg, and S3-compatible filesystem dependencies. Spark is published at digest `sha256:e10e24346948f95e2d9033687b2556ea094c32a087e093c0868fab77be7ceeca`; the corrected linux/amd64 Trino 480 image is published at digest `sha256:d39798d37aea49aac9ccaaca9ac703ad067376f1b9932b8884b0706377f47228`.
- [x] Add deterministic JSONL fixture data and the Spark transformation code. The live Spark driver produced five normalized rows and five hourly rows on two identical runs; the hourly table uses the documented delete/insert workaround for the Spark 3.5.3/Iceberg 1.5.2 transformed-partition MERGE planner failure.
- [x] Add a native Kubernetes Spark Job or CronJob that writes `logs.normalized` and `logs.hourly`; two live one-off Jobs completed and their drivers reached `Succeeded`.
- [x] Validate schemas, row counts, partitions, and Iceberg metadata locations. Trino reported the expected columns, `event_date`/`day(hour)` partitions, and locations under `s3://iceberg-warehouse/logs/`.

### Phase 3: Add Trino queries

- [x] Add the official Trino HelmRelease using the repository's Flux app pattern; the live release uses the corrected linux/amd64 Harbor digest.
- [x] Configure a Git-managed Iceberg catalog pointing to SeaweedFS's REST endpoint and S3 warehouse.
- [x] Keep Trino internal-only and inject credentials through ESO/environment references.
- [x] Add a repeatable SQL validation query and compare results with Spark output. The live coordinator returned `normalized_count=5`, `hourly_count=5`, and `hourly_event_count_sum=5`.

### Phase 4: Validate and document

- [x] Run the full fixture flow from raw input through Trino.
- [x] Re-run identical input and verify the duplicate/snapshot contract.
- [x] Capture Flux, Spark, SeaweedFS, and Trino evidence in the implementation notes.
- [x] Document operator-only cleanup, resource bounds, and known failure modes.

### Phase 5: Optional Loki source

- [ ] Add a bounded Loki snapshot CronJob only after the fixture acceptance criteria pass.
- [ ] Write Loki snapshots to the raw bucket and reuse the existing Spark and Trino interfaces.
- [ ] Validate one real log window and keep Loki ingestion internal.

## Log

- 2026-08-06: Opened from ADR 0031 to turn the accepted demo architecture into a phased implementation and validation record.
- 2026-08-06: Phase 0 passed read-only. Added the Seaweed `-port.iceberg=8181` argument and internal catalog Service. Authored dedicated bucket/identity manifests, a native Spark fixture lane, and an internal Trino REST-catalog HelmRelease. Live reconciliation, Harbor image push/digest replacement, and 1Password item creation remain operator-only prerequisites.
- 2026-08-06: Added the bounded Phase 1 S3 smoke Job and Flux ordering edges. It uses the scoped raw identity, verifies write/read/delete against `iceberg-raw`, and passed server-side dry-run; live credentials and reconciliation remain pending.
- 2026-08-06: Disposable SeaweedFS 4.40 integration passed twice with five persisted rows in both Iceberg tables. The REST metrics reporter emitted non-fatal `Path not found` warnings because the built-in catalog does not expose the optional metrics route; table writes and reads completed successfully. Anton runtime acceptance remains blocked on operator-only 1Password credentials, Harbor digests, and approved Flux reconciliation.
- 2026-08-06: Disposable Trino 480, configured with the same Seaweed REST catalog, `fs.native-s3.enabled=true`, and warehouse, read Spark's tables and returned `normalized_count=5`, `hourly_count=5`, and `hourly_event_count_sum=5`. A startup check confirmed Trino 480 rejects the newer `fs.s3.enabled` key as unused. This is offline cross-engine evidence only; no Anton Trino workload has been reconciled.
- 2026-08-06: Added the shared SOPS component to the demo parent Kustomization so child Flux Kustomizations receive `cluster-secrets` for postBuild substitution, and pinned the Spark base image by digest. The demo parent now renders its namespace, encrypted substitution Secret, Spark Kustomization, and Trino Kustomization together.
- 2026-08-06: Read-only live recheck found the cluster still on the previously applied `main` revision: `iceberg-demo` is absent, `seaweedfs-s3` still runs without `-port.iceberg`, and the live `seaweedfs-s3-config` Secret contains only the pre-existing admin/Harbor fields. The Harbor endpoint was unreachable from this checkout, so no image digest could be discovered. No live mutation was attempted.
- 2026-08-06: Operator created the required `seaweedfs-iceberg` item; ESO synced the scoped fields. A temporary Kubernetes port-forward allowed Harbor publication. The live storage rollout required one S3 Deployment restart to load the new identities; bucket provisioning and the raw S3 smoke Job then passed. The first Trino Harbor image was arm64 and failed with `exec format error`; a corrected linux/amd64 build is being published at digest `sha256:d39798d37aea49aac9ccaaca9ac703ad067376f1b9932b8884b0706377f47228`.
- 2026-08-06: Live acceptance passed. Flux reconciled storage, Spark, and Trino; the table-bucket provisioner and scoped raw S3 smoke Job completed; Spark drivers succeeded twice with `expected normalized rows=5 actual=5` and `expected hourly rows=5 actual=5`; and Trino returned `5 / 5 / 5` for the aggregate, the expected five hourly rows, and locations `s3://iceberg-warehouse/logs/normalized` and `s3://iceberg-warehouse/logs/hourly`. The warehouse identity requires the bucket-scoped `s3tables:*:iceberg-warehouse` action, and the generated Seaweed S3 Deployment must be restarted after Secret changes because the operator does not roll it automatically.

## References

- Related ADR: `context/adrs/0031-adopt-seaweedfs-iceberg-log-demo.md`
- SeaweedFS source of truth: `kubernetes/apps/storage/seaweedfs-config/app/seaweed.yaml`
- SeaweedFS operator HelmRelease: `kubernetes/apps/storage/seaweedfs/app/helmrelease.yaml`
- SeaweedFS storage contracts: `kubernetes/apps/storage/AGENTS.md`
- Harbor image registry contract: `kubernetes/apps/registries/AGENTS.md`
- Trino official Kubernetes deployment: <https://trino.io/docs/current/installation/kubernetes.html>
- Iceberg REST catalog specification: <https://iceberg.apache.org/rest-catalog-spec/>
- Cluster validation: `flux get ks -A`, `flux get hr -A`, `kubectl get pods -A`
