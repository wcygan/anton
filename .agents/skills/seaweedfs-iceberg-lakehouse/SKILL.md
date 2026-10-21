---
name: seaweedfs-iceberg-lakehouse
description: >-
  Operate Anton's shared SeaweedFS S3 for apps, Harbor and Loki: capacity, topology,
  policy, cache recovery and planned maintenance. The skill name is legacy; the
  lakehouse is retired.
---

# Shared SeaweedFS S3

ADR 0040 retired the lakehouse; ADR 0044 selects stock SeaweedFS/Loki and planned
S3 downtime. Keep shared S3 for apps, Harbor and Loki. Plan 0028 tracks rollout
and observation; verify actual image identities instead of assuming the source
has already deployed. Do not require retired Spark, Airflow or Trino workflows
for an S3 storage check.

## Read and route

Read `AGENTS.md`, `kubernetes/apps/storage/AGENTS.md` and
`anton-remote-access` before cluster access. For manifest changes also use
`anton-repo-conventions`. Current procedures are:

- `docs/docs/runbooks/seaweedfs-stock-cutover.md`: one-time image/WAL transition,
  backup contract, writer fence and rollback.
- `docs/docs/runbooks/seaweedfs-node-maintenance.md`: planned node downtime.
- `context/plans/0028-retire-custom-storage-runtime-patches.md`: qualification,
  current recovery evidence, remaining rollout and observation gates.

Keep the repository's exact-target live approval boundary. Source edits do not
authorize suspension, scaling, port-forward, jobs, image rollout or data restore.
Use `mise exec --`; keep credentials and literal tailnet names out of evidence.

## Ownership and invariants

`storage/seaweedfs` owns the operator chart. `storage/seaweedfs-config` owns the
Seaweed CR, persistent filer claims, S3 identities, probes and configuration jobs.
The CR is the operator's source; ordinary image changes use its RollingUpdate
behavior with clients and S3 fenced, not direct StatefulSet strategy overrides.

- Preserve 3 masters, 3 volumes, 2 persistent filers and 2 standalone gateways
  during this transition. Keep native `001` placement and existing Longhorn
  replica settings; no capacity migration is implied.
- Clients use `http://seaweedfs-s3.storage.svc.cluster.local:8333`; off-cluster
  access uses the existing internal gateway. Harbor redirects stay disabled.
- Keep both logical slot headroom and physical free bytes visible. Enumerate the
  current corpus; historical 32-volume/64-copy counts are not a live inventory.
- `buckets-cronjob.yaml` plus `provision-buckets.sh` own bucket/prefix lifecycle.
  `durability-cronjob.yaml` plus `ensure-durability.py` own supported native
  fsync/001 prefix settings. These use upstream commands, not runtime patches.
- Preserve filer LevelDB paths/PVCs and Raft/S3 readiness checks. In-cluster
  snapshots and replicas are not independent backups or an upload-loss bound.
- Logs are best effort. Unique uploads require the independent recovery contract
  and another copy while monitored daily backup coverage remains unimplemented.

## Bounded verification

Check source revision, exact owner/UID, applied generation and runtime image,
then readiness, topology and actual consumer behavior. Inspect scoped logs before
attributing a stale address to storage loss. After a volume-address change,
fresh gateways discard caches; restart them only under an approved writer fence.

Check the bucket provisioner and its owned Jobs before calling policy healthy:

```sh
mise exec -- kubectl -n storage get cronjob seaweedfs-buckets-ensure
mise exec -- kubectl -n storage get jobs -l batch.kubernetes.io/cronjob-name=seaweedfs-buckets-ensure
```

Require authenticated seeded bytes, previously readable Harbor image digests,
new scratch push/pull and Loki stored-chunk/new-ingestion checks as applicable.
Record existing missing artifacts separately; never turn a failed historical pull
into a passing test or delete its catalogue entry to make verification green.
Stop on changed PVC identity, lost quorum, degraded original storage, unclean
exit or missing previously readable data. Follow image rollback first; restoring
older data is a separately approved destructive decision.

For an owned app's image publication, read
[Harbor image handoff](references/harbor-image-handoff.md) only when that separate
workflow is requested. Retired lakehouse instructions and custom runtime sources
remain available in Git at `886fbd6a`; they are not the current operating path.
