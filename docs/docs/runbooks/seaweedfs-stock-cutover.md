---
title: SeaweedFS and Loki stock-software cutover
---

This is the prepared procedure for Plan 0028. It retains shared SeaweedFS S3 for
apps, Harbor and Loki. Production execution needs approval of the exact recovery
point, resources and outage window. No command on this page has been run against
production as part of preparing it.

## Selected approach

Use two image changes, with verification between them: SeaweedFS 4.48 first,
then Loki 3.7.8. Preserve all existing PVCs, native serving copies, S3 endpoints,
buckets and credentials. Keep Loki WAL and flush-on-shutdown enabled. Keep the
existing readiness checks. Defer orphan cleanup, capacity changes, controller
migration and custom-build deletion until the rollback observation period ends.

Use the previously exercised controller-freeze procedure for serial replacement.
The installed CRD accepts `statefulSetUpdateStrategy`, but operator 1.0.39 hardcodes
rolling updates in its master, volume and filer renderers. Do not use that CR field
as a hold. Temporarily suspend the operator's Flux/Helm owners, scale the operator
to zero, set Kubernetes StatefulSets to `OnDelete`, and set their templates to the
same image recorded in the Seaweed CR. Keep S3 at zero until checks pass. Restore
the captured strategies and controller ownership after all templates match source.
These are approved, temporary maintenance exceptions with a recorded cleanup;
no runtime source patch or operator migration is required.

The draft patches are retained locally in
`.private/plan0028-remaining-gates-20261020/`: `seaweedfs-cutover.patch`,
`seaweedfs-steady.patch`, and `loki-stock.patch`. Each applies independently to
`886fbd6a30efff5a8ac75befb25d1e40c8fef45b`; the steady patch is the desired final
state against that baseline, not a patch to apply after the cutover patch.
`decision.patch` also prepares the agreed ADR 0043 supersession; refresh its ADR
number before publication. Rebase all drafts onto the execution revision and rerun validation. They have
not been applied to the repository's deployment files or published.

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
on the strength of Ready snapshots alone. Refresh the recovery point for a later
cutover and account explicitly for writes since the tested checkpoint.

That window's six exports passed every captured file hash and archive integrity
check, and the full isolated Harbor application restore passed against stock
SeaweedFS 4.48, including old-image blob digests and a new robot push/pull.
Production recovery and temporary-resource cleanup completed at minute 53.42.
Three catalogue manifests checked during the lab are missing in current production
too; no pre-window artifact baseline dates their loss. Record whether they need
rebuilding or may remain known gaps before approving cutover. The successful
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
approval for its exact capture/export/clone resources first. If rehearsal ends
before the cutover window, refresh a consistent checkpoint at cutover and record
all writes since the tested recovery point. Do not silently assign an RPO to those
writes. Routine recurring backup cadence belongs with Plan 0008; it is not
implemented by a one-time export.

## SeaweedFS image cutover

Start a new approved window only after the recovery-point gate passes.

1. Fence writers and background jobs as above; retain the backup and rollback
   images. Flush/stop Loki and drain Harbor. Keep source/Helm owners frozen only
   while temporary client replica changes need protection.
2. Suspend Kustomization `storage/seaweedfs` and HelmRelease
   `storage/seaweedfs-operator`; scale Deployment `storage/seaweedfs-operator` to
   zero and verify its Pods are gone. Recheck all captured object UIDs. Patch only
   `storage/seaweedfs-master`, `-volume` and `-filer` StatefulSet strategies to
   `OnDelete`, removing `rollingUpdate`. Keep S3 at zero. Verify no Pod UID changed
   before updating images. The exact merge/UID-guarded template patches are in
   `maintenance-holds-and-templates.json` in the private packet.
3. Apply the reviewed Git change setting `spec.s3.replicas: 0`, the stock image,
   and removal of `leveldb2.sync=true`. Keep `[leveldb2]`, its directory and PVCs.
   Keep the durability CronJob suspended during transition; its draft switches its
   weed init image to stock. Let only `storage/seaweedfs-config` reconcile this
   source while the operator remains stopped. Then update the three held
   StatefulSet main-container image fields to that exact desired digest using the
   captured UID/name preconditions; preserve sidecars and every other template
   field. Set the stopped S3 Deployment's image to the same digest. Confirm source
   and templates agree and no Pod replaced itself. Do not resume the operator yet.
4. Replace one volume Pod at a time: `storage/seaweedfs-volume-0`, then `-1`, then
   `-2`. Use a UID/resource-version-preconditioned eviction via the Eviction API
   so PDBs remain effective. Approval includes the exact captured Pod identities.
   After each, require its new UID, stock digest, readiness and writable native
   copy inventory; preserve every existing FID and copy.
5. Replace `storage/seaweedfs-filer-0`, then `-1`, one at a time, verifying its
   original PVC, mounted path, healthy peer state and stock digest.
6. Identify the current Raft leader through the read-only cluster status. Replace
   the two follower Pods in `storage/seaweedfs-master-0..2` first and the leader
   last. Verify quorum after each. Never assume an ordinal is the leader.
7. Restore the captured StatefulSet strategies. Apply the reviewed steady-state
   source with two S3 replicas and the approved stock policy-job image. Restore
   the operator Deployment, HelmRelease and Kustomization ownership; let it
   reconcile all templates/configuration to this source. Observe any additional
   replacement before admitting writers, and stop if the template differs from
   the reviewed state. Fresh S3 Pods discard old address caches. Verify both
   gateways and exact historical object hashes, signed Range GET, app scoped/
   presigned operations, and historical Harbor digests.
8. Restore clients and original ownership one at a time. Verify Harbor health and
   scratch push/pull, Loki stored-chunk queries, queue recovery, Flux revisions,
   applied generations/images, Longhorn health and absence of temporary resources.
   Retain the checkpoint and both image directions through the observation period.

Wait at most three minutes per replacement before stopping new work; the global
window deadline takes precedence. A blocked PDB, forced exit, missing historical
object, degraded replica, unexpected allocation or failed ordinary read/write
check stops progress. The known isolated crash-fault results alone are not rollback
triggers under the revised contract.

## Loki image cutover

Use its own approved window after the S3 checks pass. Keep the chart version,
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
Git image/configuration change and replace affected Pods through the same owner
and serial procedure. Preserve current data volumes and all post-cutover writes.
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
of operation. Remove obsolete build pipelines and migration helpers only after
rollback retention ends. Preserve fault findings as historical risk evidence.
