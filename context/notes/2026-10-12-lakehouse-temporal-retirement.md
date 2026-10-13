# Lakehouse and Temporal retirement — 2026-10-12

Decision: [ADR 0040](../adrs/0040-retire-lakehouse-and-temporal.md).

## Authority and outcome

The operator explicitly authorized GitOps removal and permanent data deletion, while preserving Longhorn, SeaweedFS, Harbor, Prometheus, Goldilocks, Headlamp, and Hubble. Work used the repository kubeconfig and verified Tailscale operator context. No secret values were retrieved or printed.

Completed at approximately 20:49 America/Chicago (2026-10-13 01:49 UTC).

- `642fc66c4fe62098baf790c133e0d166195b81bf` removed Airflow, lakehouse workloads, Trino, Temporal, and dedicated bucket provisioning/resources.
- `baf587775af3d9a85627001f698ed8aa369c5380` removed Spark Operator after all SparkApplication and SparkCluster resources were absent.
- Both revisions were pushed to `main`; Flux source and `cluster-apps` reconciliation applied them.
- All five retired namespaces, their pods, PVCs/PVs, and associated Longhorn volumes are absent.
- Spark CRDs, cluster RBAC, and webhooks are absent.
- No temporary Jobs, debug pods, or port-forwards were created.

## Deletion sequence and exceptions

Flux pruned the app Kustomizations and HelmReleases. Namespace manifests carried `kustomize.toolkit.fluxcd.io/prune: disabled`, so the operator-authorized namespace deletions were performed explicitly by exact name: `airflow`, `iceberg-demo`, `temporal`, `lakehouse`, then `spark-system` after operator uninstall.

The Spark operator stayed running until the 1,487 retained SparkApplication objects were finalized. Both Spark CRDs were deleted only after their cluster-wide instance lists were empty and the operator was uninstalled.

Airflow's database pod and `temporal-postgres-3` had 1,800-second shutdown grace periods. After their controllers and clients were removed, exact-name pod deletion shortened grace to 30 seconds. No finalizers were stripped. Namespace retirement-revision annotations prompted normal finalization after the old grace estimate was obsolete.

The detached `temporal-postgres-2` and `temporal-postgres-2-wal` PVCs were explicitly deleted by exact name. All nine dedicated volumes are confirmed absent:

- `airflow/airflow-postgres-1`
- `temporal/temporal-postgres-{1,2,3,4}`
- `temporal/temporal-postgres-{1,2,3,4}-wal`

The removed volumes provisioned 110 GiB logical capacity and had approximately 18.26 GiB of replicated Longhorn actual-size footprint before deletion. These are pre-deletion accounting figures, not an isolated before/after physical-disk measurement.

After writers stopped and the applied bucket CronJob declared only `harbor loki` with empty table/prefix lists, the four exact buckets were removed through SeaweedFS 4.40's `weed shell` `s3.bucket.delete -name <bucket>` on `storage/seaweedfs-master-0`:

- `iceberg-raw`
- `iceberg-shadow`
- `iceberg-warehouse`
- `spark-events`

The command removes the dedicated bucket collection and filer directory. Bucket listings were checked after each deletion. Final `s3.bucket.list` contains only `harbor` and `loki`; `s3tables.bucket -list -account admin` reports no table buckets; `/buckets/.objects` has no entries. Removed bucket collection size totaled approximately 0.38 GiB before deletion. This does not promise immediate Longhorn block reclamation.

## Preserved platform

SeaweedFS runtime specification, S3 identities/credentials, PVCs, and Harbor were unchanged. Only lakehouse bucket declarations, lifecycle resource, smoke Job, and dedicated Iceberg Service were removed from shared storage configuration. The existing Iceberg listener remains part of the unchanged SeaweedFS runtime, with no table buckets or dedicated Kubernetes Service.

Source images, historical skills, and retained development evidence remain in Git; they do not run in the cluster. Airflow and Trino task groups are no longer advertised. Dedicated deployment validators were removed; shared storage and provisioning checks remain enforced. Existing metrics/log history ages out through normal shared-service retention.

## Verification

- `mise exec -- task contracts:validate`: PASS, 348 tests, including platform-only provisioning without table buckets.
- `mise exec -- bun run --cwd docs build`: PASS.
- `git diff --check`: PASS.
- Flux: 53 Kustomizations and 27 HelmReleases, all Ready.
- No resources belonging to the five retired namespaces in namespace, pod, PVC, PV, or Longhorn Volume inventories.
- No Spark/Temporal/Airflow/lakehouse/Trino cluster RBAC, webhook, or CRD remnants by name.
- Shared running pods remained ready with unchanged UIDs: storage 44, registries 15, observability 23, kube-system 32.
- Harbor `/api/v2.0/health`: all seven components healthy.
- Loki `/ready`: ready.
- Prometheus `/-/ready`: ready.
- Harbor bucket chunk count and logical bytes unchanged across deletion; Loki continued normal writes.

## Recovery boundary

No backup was created because permanent data deletion was explicitly requested. Git can restore workload definitions, but it cannot restore the deleted database or bucket contents. No shared retention, snapshot cleanup, image garbage collection, or external 1Password-item deletion was performed.
