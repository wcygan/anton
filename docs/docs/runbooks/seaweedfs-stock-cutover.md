---
title: SeaweedFS and Loki stock-software cutover
---

Plan 0028 deployed stock SeaweedFS 4.48 and Loki 3.7.8 on 2026-10-20
(local date), retaining shared S3 for apps, Harbor and Loki. Custom runtime
patches/builders are retired. See the [execution evidence](https://github.com/wcygan/anton/blob/main/context/notes/2026-10-20-plan0028-stock-cutover.md).
This records the one-time image transition and rollback; use
[the node-maintenance runbook](seaweedfs-node-maintenance.md) for ordinary node
work. Any later execution needs its own exact targets, recovery point and window.

## Selected approach

Use two image changes, with verification between them: SeaweedFS 4.48 first,
then Loki 3.7.8. Preserve all existing PVCs, native serving copies, S3 endpoints,
buckets and credentials. Keep Loki WAL and flush-on-shutdown enabled. Keep the
existing readiness checks. Defer orphan cleanup, capacity changes, controller
migration until after the image transition. Retire custom build sources only
after live stock verification; retain exact rollback OCI archives through the
observation period, so rollback never depends on rebuilding a fork.

The live CRD requires at least one S3 replica. **Do not set CR S3 replicas to
zero:** the first approved attempt was rejected at admission before image changes.
A renderer test alone is insufficient. Require API-server dry runs of final CR,
filer ConfigMap and backend templates, and account for the admission webhook
being hosted by the operator that maintenance stops.

The corrected procedure temporarily holds the operator and scales its S3
Deployment to zero directly. Keep the CR at valid desired replicas two. Use the
existing Kubernetes StatefulSet RollingUpdate strategy for backend image changes;
restore operator ownership only after backend and data checks pass. Different
roles may roll concurrently while writers and S3 are stopped. This requires
approval for the additional operator-owner and temporary template/config targets;
see the [execution boundary](https://github.com/wcygan/anton/blob/main/context/notes/2026-10-20-plan0028-cutover-attempt.md).

The exact operator 1.0.39 builders were checked against the admitted CR: stock
changes only the main-container image in the three StatefulSets, preserving PVCs,
probes and replica counts; the S3 Deployment honors replicas zero internally.
The CRD rejects zero, so the live rollout used the direct Deployment fence below.
All eight backend replacements subsequently passed production checks. Sources:
[master renderer](https://github.com/seaweedfs/seaweedfs-operator/blob/1.0.39/internal/controller/controller_master_statefulset.go),
[filer renderer](https://github.com/seaweedfs/seaweedfs-operator/blob/1.0.39/internal/controller/controller_filer_statefulset.go),
[S3 renderer](https://github.com/seaweedfs/seaweedfs-operator/blob/1.0.39/internal/controller/controller_s3.go).
The earlier private OnDelete strategy patches are historical drafts and must not
be used with this procedure. Only the named main-image/config template changes
in the corrected boundary are permitted. The committed steady-state files are
`kubernetes/apps/storage/seaweedfs-config/app/seaweed.yaml`, its
`durability-cronjob.yaml`, and `kubernetes/apps/observability/loki/app/helmrelease.yaml`.
ADR 0044 records the accepted downtime and upload-recovery contract.

| Runtime | Stock target | Rollback image retained |
| --- | --- | --- |
| SeaweedFS | `docker.io/chrislusf/seaweedfs:4.48@sha256:aba492e2a4e4c90bff795745e8e660affa1f09e7650f5981bd7bccd1a06cd931` | `192.168.1.106/library/seaweedfs-durable:4.48-durable1-growth1-sync1@sha256:63da1c585c2c1beae7b4ab223a7558b1b97e5f44a45755e578079a86a8d42420` |
| Loki | `docker.io/grafana/loki:3.7.8@sha256:1107dd5274e0ada47e42472b7a7e71f3b2a2fe878878108f3e2f9e51528f0193` | `192.168.1.106/library/loki-wal:3.7.8-anton.wal.1@sha256:c8aebc49d956fe2457c10d5acdce3810ea87cbeea3e9fd8d58cb0fd7d6c53347` |

Cache both directions outside Harbor before stopping Harbor. The retained local
SeaweedFS rollback archive has a verified digest and can supply the same bytes;
verify availability on each execution node through an approved pre-pull. A
laptop Docker cache alone does not prove Kubernetes can start an image.

## Preconditions and decision record

1. Verify the Kubernetes context is `tailscale-operator.<tailnet-name>.ts.net`.
   Recheck current namespace, UIDs, PVC-to-PV mapping, images, revisions and operator
   ownership. Stop if another storage operation owns the targets.
2. Require healthy Longhorn volumes and replicas, ready Raft quorum, writable
   SeaweedFS copies, physical disk headroom and logical volume slots. Check the
   full current corpus; do not assume the dated 32-volume/64-copy count is current.
3. Record every active S3 writer, including private apps, Harbor jobs/retention/GC,
   Loki compaction and bucket/policy CronJobs. Capture original replicas and each
   object's `spec.suspend` presence/value so cleanup restores the same ownership.
4. Agree a window before execution. Proposed reservation: 60 minutes, stop new
   cutover steps at minute 40 and reserve 20 minutes for recovery. This is an
   approval proposal, not a measured downtime guarantee. If only a shorter window
   is acceptable, complete backup/export/restore rehearsal first and measure the
   actual remaining restart time. Do not claim the local emulation time is the RTO.
5. Apply the selected upload default: assume files can be unique; require an
   independent encrypted backup and tested restore before relying on the cluster
   as the only copy. Target daily backups with the newest usable point at most
   24 hours old, accepting possible loss since that point. Until coverage is
   running and monitored, require another independent copy or gate unique uploads.
   Measure restore time before promising an RTO. Log-loss tolerance does not
   override this upload policy; document any app-specific exception explicitly.
6. Publish only reviewed source changes, run `mise exec -- task contracts:validate`,
   render the actual chart/operator configuration, and verify both image sources.
   Do not combine this with unrelated changes on the current working branch.

## Recovery point: capture before image changes

The 2026-10-20 backup-only window (evidence in
`context/notes/2026-10-20-plan0028-backup-window.md`) captured a coordinated
Harbor database/S3 recovery point; consult its final verification status before
relying on it. Harbor CNPG still has no configured
recurring backup or plugin, and Longhorn's backup target is empty. Do not proceed
on the strength of Ready snapshots alone. At execution, verify the tested independent recovery point is no more than
24 hours old and every active app permits that loss window. Account explicitly
for writes since that checkpoint. Capture a new coordinated point first if it
is older or an app requires a fresher point; do not silently broaden its RPO.

That window's six exports passed every captured file hash and archive integrity
check, and the full isolated Harbor application restore passed against stock
SeaweedFS 4.48, including old-image blob digests and a new robot push/pull.
Production recovery and temporary-resource cleanup completed at minute 53.42.
Three catalogue manifests checked during the lab are missing in current production
too; no pre-window artifact baseline dates their loss. Record whether they need
rebuilding as a separate Harbor data repair. The stock image change leaves those
entries untouched; compare currently readable artifacts before and after it. The successful
known-image restore does not recover already-missing content. Daily backup and
freshness monitoring remain unimplemented.

Use the existing encrypted export path as the interim method; do not introduce a
new backup controller for this cutover. The independent destination is an
operator-controlled machine outside the cluster, with age encryption and a tested
private key. Do not store the only backup in the SeaweedFS instance being changed.

After approval of the named maintenance actions:

1. Freeze source automation for clients while making temporary replica changes.
   Targets are Kustomizations `registries/harbor` and `observability/loki`, and
   HelmReleases `registries/harbor` and `observability/loki`. Pause the bucket and
   durability CronJobs in `storage`; stop any running instance and any Harbor GC
   or retention job through its supported cancellation path before backup.
   Suspend `storage/seaweedfs-config` while its CronJobs/CR are temporarily changed;
   parent/source automation must not silently undo the freeze. Record all fields.
2. Block app writes. Stop Harbor nginx, jobservice, core and registry after current
   work drains; the current replicas are 2, 1, 2 and 2 respectively. Keep the CNPG
   cluster and its primary running. Do not delete the database or cache volumes.
3. Flush Loki through its existing API proxy; require no new flush failures,
   queue zero and a known record read from stored chunks. Stop `observability/loki`
   cleanly, preserving its 20Gi PVC. Collectors retry within their bounded queues;
   an extended outage can exhaust those queues and lose logs.
4. For the backup only, freeze the SeaweedFS operator owner (Kustomization
   `storage/seaweedfs`, HelmRelease `storage/seaweedfs-operator`, then operator
   Deployment replicas zero). Stop S3, then each filer, then each volume server
   serially. Require clean exits; do not force-delete, delete PVCs, or stop all
   components in parallel. Keep masters and their identity state preserved.
   Stop here on an unclean exit and investigate before calling the capture clean.
   Establish the Pod watch before scaling: use `resourceVersion=0`, require its
   initial ADDED event to match the captured UID, and retain the final DELETED
   event with the main container's terminated exit code. A stale last-change
   resource version can expire from the watch cache before the stop.
5. Capture the five data/metadata PVCs and Loki's PVC, plus the master state,
   image identities, bucket policy and storage manifests. The five SeaweedFS PVCs
   are `mount0-seaweedfs-volume-0..2` and
   `seaweedfs-filer-seaweedfs-filer-0..1`. Generate exact, new snapshot/clone/reader
   names, UIDs, namespace and cleanup manifests for approval; never reuse an old
   snapshot name. The existing snapshot export helpers are precedent, not scripts
   to rerun unchanged with their historical resource names.
6. Discover `registries/harbor-postgres.status.currentPrimary` immediately before
   exporting the `registry` database with PostgreSQL 17 `pg_dump --format=custom`.
   Stream the dump directly into age encryption with pipeline failure checking;
   never send SQL, password hashes or a Secret payload to chat or terminal output.
   Capture the required roles/grants and a recoverable credential/configuration
   path as part of the same approved backup scope. The CNPG app credential is
   generated in `harbor-postgres-app`; a dump alone does not recreate it.
7. Export the stopped-state snapshots and master metadata as encrypted archives;
   retain full-file hashes and identities. Start original volumes, filers and S3,
   restore clients and all captured owners after checks, and export from clones
   while the patched service runs if that shortens the outage. Temporary clone
   readers must mount clones, never the live data PVCs. The private capture packet
   names six snapshots `p28-preflight-20261020-v0..2`, `-f0..1` and `-loki`,
   their `-clone` PVCs and `-reader` Jobs, and one `p28-preflight-isolate` policy
   in each involved namespace. Treat the combined bundle as an inventory only.
   Use the split snapshot/isolation manifests and process one clone/reader at a
   time: 508Gi nominal PVC capacity would otherwise be cloned concurrently.
   Refresh source UIDs, free capacity and unused target names before approval.
   Run the Loki clone reader as UID/GID 10001, matching the writer, with all
   capabilities dropped and the mount read-only; preserve source permissions.
8. Restore into isolated storage with no route to production or published ports.
   Use recovered Harbor credentials only inside that sealed lab, retain private
   logs and never print credentials. Give the restored S3 gateway lab-only keys. Restore
   the database and S3 state from the same write fence. Verify projects, robot/user
   access, known manifest/blob digests and a new scratch push/pull through a real
   Harbor core/registry; verify S3 app objects and Loki cold queries/retention.
   Record elapsed recovery time, coverage and cleanup. Stop if this fails.

The backup/restore authorization is separate from the stock deployment. Obtain
approval for its exact capture/export/clone resources first. Use the tested recovery point only within its agreed freshness and per-app
loss contract; record its timestamp and all later writes as potentially absent
from disaster recovery. A binary rollback preserves current PVCs and does not
restore that older checkpoint. Plan 0008 tracks recurring Harbor DB backups; independent S3/filer/master coverage
for unique uploads is an additional open protection gate. A one-time export does
not implement either cadence.

## SeaweedFS image cutover

Use an approved 60-minute reservation. Stop new image steps at minute 40 and
reserve 20 minutes for recovery. The original operator-running procedure is
withdrawn because API admission rejects CR S3 replicas zero.

1. Verify context, UIDs, original field presence, PVC identities, recovery-point
   freshness, Raft quorum, Longhorn health and the complete native corpus. Require
   no competing storage operation or active Harbor GC/retention work. Verify all
   four exact images execute on all three storage nodes before an outage.
2. Hold Harbor/Loki Kustomizations and HelmReleases, `storage/seaweedfs-config`,
   both storage CronJobs, and the operator owners `storage/seaweedfs`
   Kustomization / `storage/seaweedfs-operator` HelmRelease. Journal each field.
   Include the two operator webhook configurations in the approval packet: their
   fail-closed endpoints disappear while the operator is stopped.
3. Stop Harbor nginx, jobservice, core, registry. The stock Harbor registry image
   exits 2 on normal SIGTERM, as reproduced locally; record this separately from
   the zero-exit requirement for SeaweedFS/Loki. Flush Loki, require queue zero and
   stored-chunk reads, then stop Loki cleanly. Preserve CNPG, cache and all PVCs.
4. Stop `storage/seaweedfs-operator` Deployment (one to zero), wait for its Pod to
   terminate, then scale the operator-owned `storage/seaweedfs-s3` Deployment to
   zero. Require both gateway Pod watches to record zero-exit deletion. Keep the
   Seaweed CR at its valid desired two replicas.
5. With separate approval, add a temporary `matchConditions` entry to the sole
   webhook in `seaweedfs-operator-mutating-webhook-configuration` and
   `seaweedfs-operator-validating-webhook-configuration`:
   `request.namespace != 'storage' || request.name != 'seaweedfs'`.
   This skips only this CR while leaving CRD validation and other objects'
   admission unchanged. Retain the original webhook lists and guard UID/version.
   Publish the reviewed runtime revision and verify its Flux source artifact.
   Guard-patch the Seaweed CR to final stock image/config/disabled Iceberg listener.
   Set `storage/seaweedfs-filer` ConfigMap `data.filer.toml` to the same committed
   config. Change only the main-container image in `seaweedfs-master`,
   `seaweedfs-volume` and `seaweedfs-filer` StatefulSets. Keep RollingUpdate and all
   claims. No OnDelete strategy or routine Pod deletion is needed.
6. Require all eight backend Pods at the exact stock digest/current revisions,
   recorded clean old-Pod exits, healthy quorum, original PVC identities and the
   complete writable native corpus before restoring S3. Stop on any mismatch.
7. Restore the operator's original replica against the already matching stock
   CR/backends. Once its endpoint is ready, remove both temporary webhook
   conditions and verify the full lists equal their originals. Restore the
   operator HelmRelease/Kustomization suspend fields. Reconcile `seaweedfs`
   before `seaweedfs-config`: the latter requires the operator owner's current
   source revision and the CR's current observed generation. Verify both stock
   S3 gateways, native-tool init image, source/rendered template equality,
   authenticated seeded reads/ranges, native policies and historical bytes.
   Explicitly restore both CronJobs' original suspend fields; an omitted source
   field does not necessarily undo an imperative suspension.
8. Restore Harbor replicas/owners and verify health/login, historical manifest and
   blobs, and one newly created scratch robot push/pull; remove only those new
   objects. Complete Loki's separately verified stock/new-WAL phase within budget.
   Remove the UID-recorded cache DaemonSet/policy and verify all original ownership.

On failure, keep writers/S3 fenced and restore the original CR, filer ConfigMap
and three main images using the same StatefulSet rollout. Restore operator,
gateways, clients and source ownership after recovery checks. Remove any
temporary admission exceptions once the operator endpoint is back, and verify
the original webhook lists. A blocked Pod needing
an eviction requires a fresh exact-target recovery decision. No PVC, snapshot,
bucket, artifact or WAL deletion is authorized by an image cutover.

## Loki image cutover

Use a separate verified phase after the S3 checks pass. It can share the approved
60-minute reservation only while the global budget permits; otherwise use its own
approved window. Keep the chart version,
storage schema, S3 bucket, replica count and PVC unchanged.

1. Fence ingestion long enough to flush every in-memory chunk, require flush queue
   zero, and verify stored-chunk readback. Stop the patched process cleanly.
2. Preserve `/var/loki/wal-anton-20261019-a` and the complete original PVC/checkpoint.
   Do not ask stock Loki to replay the patched counter history.
3. Reconcile the stock image pin and `ingester.wal.dir: /var/loki/wal-stock-0028`.
   Keep `enabled: true` and `flush_on_shutdown: true`. Verify the actual rendered
   configuration before resuming the HelmRelease.
4. Require old stored records, fresh ingestion/query and clean restart readback;
   then resume collectors/clients and observe queues. Record any gaps honestly.
   Retention is unchanged: 24h default, 336h warning, 720h error/fatal.

## Rollback and data recovery

**Image rollback is the first response.** Keep writers fenced, revert the selected
Git image/configuration change and let the same operator/controller roll back its workloads. Preserve current data volumes and all post-cutover writes.
Never restore an older backup merely because an image fails readiness.

For Loki rollback, flush and cleanly stop stock first. Start the patched image with
another fresh WAL directory (for example `/var/loki/wal-rollback-0028`) after all
acknowledged data that can be flushed is in S3. Preserve both old WAL directories;
replaying the pre-cutover patched WAL can duplicate or resurrect old state. If a
clean flush fails, preserve the current PVC and WAL and stop for offline recovery.
Do not delete a WAL to make readiness green.

**Backup restore is a separate, destructive recovery decision.** It requires a
fresh approval naming exact replacement PVCs/DB target and the accepted loss of
writes since that checkpoint. Restore Harbor DB and S3 coherently; do not restore
one side alone or overwrite the live PVCs automatically. Use new storage, verify
service readback, then switch owners/endpoints deliberately. If new writes exist,
retain their state and reconcile them before returning to an older checkpoint.

Before closing, verify the final Git/Flux/applied identities, all original replica
and suspension fields, no temporary probes/readers/networks, and seven normal days
of operation. Remove obsolete build pipelines and migration helpers after live stock verification;
retain exact rollback binaries through observation. Preserve fault findings as historical risk evidence.
