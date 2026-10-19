---
status: Done
opened: 2026-10-19
closed: 2026-10-19
affects: observability
intent: concrete-need
related-adrs: ['0005', '0032', '0042']
review-by: null
---

# 0026 — Investigate Loki WAL replay safely

> Preserve a point-in-time Loki volume and diagnose replay on isolated copies before selecting a production repair.

## Goal

Determine the exact returned error behind Loki 3.7.8's generic WAL segment
recovery warning, classify its data impact and select a verified repair while
preserving the production volume and its evidence. This document prepares the
operation; snapshot creation, cloning, diagnostic workloads and any restart need
separate operator authorization. The collector shutdown alert rollout does not
execute this plan.

## Acceptance criteria

- [x] A retained, identified snapshot of the correct Loki volume and a hash-verified evidence copy survive normal WAL checkpoint cleanup.
- [x] Offline replay reports the actual error and affected references/counts without connecting to production or changing baseline evidence.
- [x] Source-to-Loki comparisons distinguish observed loss from unavailable historical records.
- [x] A proposed repair passes an isolated replay/restart regression and has an exact rollback before production approval.

## Tasks

### Recorded preflight and scope

- [x] Confirm `observability/storage-loki-0` is Bound to `pvc-359371d0-80ba-4208-a125-c17127538585`: 20Gi, Longhorn volume of the same name, attached/healthy with two replicas on 2026-10-19.
- [x] Confirm the snapshot CRDs exist and no `VolumeSnapshotClass` is currently configured.
- [x] Preserve the 2026-10-19 investigation: 8,790/8,790 retained workload records matched Loki in 18:40–18:57 UTC, plus 3,600/3,600 numbered drill records. The 30-record collector shutdown report was reproduced as durable replay, not demonstrated loss.
- [x] Record the diagnostic limit: the old replay segments have already rotated away. A new snapshot preserves current/future evidence; it cannot recreate the original failure state.
- [x] Immediately before the authorized operation, verify the expected Tailscale operator Kubernetes context without publishing its literal tailnet name; recheck PVC UID, PV CSI driver/handle, mounted pod/node, image digest, Longhorn engine version, replica health, free disk capacity, CSI/snapshot-controller readiness and current alerts. Stop on any identity change, rebuilding replica, degraded volume or insufficient clone capacity. Reserve capacity for a 20Gi clone with two replicas (up to 40Gi of replicated data across eligible storage nodes), snapshot growth, working-copy space and existing safety headroom.

### Approval unit A: retained point-in-time snapshot

- [x] Obtain approval for only the named class/snapshot and transient snapshot I/O. Add the class through `storage/longhorn-config` with the appropriate snapshot-controller dependency and normal Flux validation; create the named forensic snapshot only after that revision is Ready. Confirm the installed Longhorn version's CSI `type: snap` support.

Prepared shapes (documentation only; these are not wired into Flux):

```yaml
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshotClass
metadata:
  name: longhorn-wal-forensics
driver: driver.longhorn.io
deletionPolicy: Retain
parameters:
  type: snap
```

Use the following names once, after refreshing the target identity; choose a new
suffix for another capture rather than replacing an existing snapshot:

```yaml
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: loki-wal-forensics-20261019-a
  namespace: observability
spec:
  volumeSnapshotClassName: longhorn-wal-forensics
  source:
    persistentVolumeClaimName: storage-loki-0
```

- [x] Take the initial snapshot while Loki is running, preserving the current crash-recovery state. Do not flush, stop Loki, edit WAL files or change checkpoints first. This is a crash-consistent capture, not an application-consistent backup. Record the snapshot/controller times and any brief I/O impact.
- [x] Wait at most five minutes for `readyToUse=true`; record snapshot UID, bound `VolumeSnapshotContent`, CSI driver, source volume handle, backend snapshot handle, restore size and retention policy. Stop further actions if readiness times out or production storage/latency/canary health worsens. Preserve a failed capture for inspection; do not retry by deleting it blindly.
- [x] Verify production Loki, collector queues, canaries, Longhorn and SeaweedFS remain healthy. Retained snapshots share the cluster's failure domain and are not independent backups.

### Approval unit B: clone, preserve and replay offline

- [x] Obtain separate approval to create only `observability/loki-wal-replay-20261019-a` from the snapshot. Never change the production StatefulSet, PV claimRef, reclaim policy, original PVC or production mount.

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: loki-wal-replay-20261019-a
  namespace: observability
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: longhorn
  resources:
    requests:
      storage: 20Gi
  dataSource:
    apiGroup: snapshot.storage.k8s.io
    kind: VolumeSnapshot
    name: loki-wal-forensics-20261019-a
```

- [x] Wait at most five minutes for a separate Bound clone. Verify its CSI handle differs from the source and it references the intended snapshot. Stop if the original volume changes or clone identity/readiness is ambiguous.
- [x] Before creating reader Job `loki-wal-reader-20261019-a`, install and verify NetworkPolicy `loki-wal-isolate-20261019-a` denying all ingress/egress for its unique diagnostic label. Review the complete pinned Job/NetworkPolicy manifests as part of approval unit B; use `backoffLimit: 0` and a 600-second deadline. Use no Loki/collector production selector labels, no host networking, no service-account token, no production Secrets and no public Service. Pin diagnostic images and apply resource/time limits. Mount only the clone, read-only; no pod may mount the original PVC for this operation.
- [x] Produce a sorted file manifest and SHA-256 hashes for completed checkpoints, all WAL segments and relevant local index metadata. Preserve the complete snapshot even if only WAL files are exported. Treat raw logs/WAL as sensitive: controlled local storage, encrypted export, no bodies or credentials in shared evidence. Verify archive hashes before relying on an external copy.
- [x] Build/download dependencies for an exact-version test harness before attaching evidence. Add a test in Loki's `pkg/ingester` package that calls real checkpoint/WAL recovery and prints the returned error, error type, file/offset or stream reference when available, plus counts/hashes rather than log bodies or full labels. Increasing production log verbosity alone cannot expose the error omitted by this version's recovery log call.
- [x] Run the harness in a local container with `--network none`, no kubeconfig/Talos config, no S3/SeaweedFS credentials and no production endpoint configuration. Use the retained archive as a read-only baseline and a separate disposable working copy; Loki startup/recovery may write or remove files. Disable module downloads for the replay (`GOPROXY=off`, `GOSUMDB=off`, local toolchain). Put any writable filesystem object-store fixture only on the working copy. Do not start an application server or production storage client.
- [x] Stop after ten minutes or on any attempted external connection. Keep the first actual error and distinguish reader/CRC/decode failures from missing references or stream reconstruction failures. Normal duplicate replay counts are not lost-record counts, and the open duplicate-counter bug does not itself explain the generic error.
- [x] Compare baseline hashes after replay and require zero baseline changes. Repeat on a fresh working copy to establish reproducibility. Use stable canary/source IDs for loss checks; if the original error does not reproduce, record that limitation and arrange a fresh pre-restart capture only with explicit approval.

### Approval unit C: repair, rollback and cleanup

- [x] Select the smallest repair from the reproduced error. Keep WAL enabled and `flush_on_shutdown: true`; do not truncate/delete the WAL or run filesystem repair as a diagnostic step. Require evidence of a constrained corruption and preserved originals before proposing any destructive repair. Test a candidate version/fix offline before production rollout; upstream PR 25162 is currently open/unmerged and is a separate replay-loss risk.
- [x] Present exact files/commands, expected transition, timeout and rollback for any production change. The original volume remains authoritative; there is no restore-in-place or diagnostic-clone cutover in this plan. A diagnostic failure is handled by stopping the diagnostic workload, not by changing production data.
- [x] After evidence is retained and the operator approves cleanup, remove only Job `loki-wal-reader-20261019-a`, NetworkPolicy `loki-wal-isolate-20261019-a` and clone PVC `loki-wal-replay-20261019-a`; keep the retained snapshot/content and encrypted evidence through review. Obtain a separate exact-target decision for final snapshot/backend-artifact deletion. `Retain` can leave backend artifacts intentionally; inventory them rather than using wildcard cleanup.
- [x] Close this plan with the supported cause, proven data impact, actual repair validation and residual uncertainty. Keep the existing WAL recovery alert truthful; never restart merely to clear its lifetime counter.

## Log

- 2026-10-19: Prepared at the operator's request after one generic segment-recovery error during an overlapping restart. The process recovered its checkpoint, kernel checks found no storage-error signatures, and the durable collector replayed shutdown-interrupted requests. No snapshot, clone, replay workload or Loki restart was performed for this plan.

- 2026-10-19: Executed authorized capture and isolated replay; reproduced missing references, verified all captured records in Loki and a candidate checkpoint fix. Production repair remains a review/approval handoff; the diagnostic clone is retained pending storage-deletion approval.

- 2026-10-19: Done after the approved pinned-image rollout, clean old-process exit, 1,800/1,800 timestamp/body comparisons through stored chunks and a completed production checkpoint; original WAL, snapshots and encrypted evidence retained.

## 2026-10-19 snapshot and offline replay result

The operator authorized the snapshot/clone/offline investigation, preserving the
original volume and requiring a recommendation before production repair.

- Git `777caa4d` adds `longhorn-wal-forensics` through `storage/longhorn-config`,
  with its snapshot-controller dependency. Contract validation passed; Flux
  reported that revision Ready before capture. Longhorn is 1.12.1. Source PVC,
  pod UID and image digest matched the recorded identities; the original remains
  attached/healthy with two replicas. Eligible disks had over 900 GiB available
  each, exceeding the clone's two-replica reservation plus safety headroom.
- Snapshot `observability/loki-wal-forensics-20261019-a` became ready at
  **19:41:52 UTC**, UID `d1531ea6-7036-4736-aa7e-9f7e9897adb3`.
  Content `snapcontent-d1531ea6-7036-4736-aa7e-9f7e9897adb3` retains backend
  `snap://pvc-359371d0-80ba-4208-a125-c17127538585/snapshot-d1531ea6-7036-4736-aa7e-9f7e9897adb3`.
  Restore size is 20Gi and deletion policy is Retain. No flush, restart or
  modification of production WAL preceded capture.
- The distinct clone is `observability/loki-wal-replay-20261019-a`, CSI handle
  `pvc-3d4e071c-0234-4a05-8fab-a0d377c8b16b`. Its denied-network, tokenless,
  pinned Python reader mounted only the clone read-only. Recreating the diagnostic
  Job as UID 10001 resolved a file-permission error; normal CSI detach/attach
  completed without intervention. Reader Job and NetworkPolicy are now removed.
  Storage deletion policy blocked removal of the clone PVC pending explicit
  approval; it remains detached. Original production resources were unchanged.
- All 22 exported files (11,645,144 bytes) were SHA256 verified after decryption.
  The 2,262,056-byte age-encrypted archive SHA256 is
  `1ebaa33ad920d66d95fb4b8c28c2364243b641900f9f53a1fd59e8a4227722c6`.
  Keep its private key and controlled local baseline alongside private evidence;
  neither raw evidence nor key is committed. The retained complete snapshot
  remains the authoritative capture and is not an off-cluster backup.
- Upstream commit `09e6ce2ff1bdc19763a10265b870c86f51c98655` (v3.7.8)
  matches production's revision and image
  `grafana/loki@sha256:1107dd5274e0ada47e42472b7a7e71f3b2a2fe878878108f3e2f9e51528f0193`.
  Real checkpoint/WAL recovery ran twice on fresh working copies with network
  disabled, no credentials/endpoints and an unchanged hash-verified baseline.
  The actual returned error was
  `stream (16667595852335071993) not set during WAL replay for user (fake)`
  (`*errors.errorString`). Checkpoint, segment and independent scan readers
  reported no errors. Two missing references affected 45 entries initially;
  record locations and hashes are retained privately.
- **Data impact:** all 30,117 checkpoint entries and 6,579 segment entries matched
  Loki by nanosecond timestamp/body SHA256: 34,698 unique pairs, zero missing.
  This includes all 45 missing-reference entries (5 Grafana and 40 SeaweedFS
  operator records). Narrow queries for those streams downloaded stored chunks,
  with zero matching in-memory chunks. Offline recovery counted 34,285 recovered
  entries and 2,366 duplicate skips; these counters are not loss counts.
  The original 18:54 startup segments had rotated away: this capture reproduces
  the error class and demonstrates present evidence coverage, but cannot prove
  that the historical generic message had the identical reference/cause.

### Supported cause and verified candidate

Checkpoint iteration holds stream pointers while checkpoint work is amortized.
`streamIterator.Next` explicitly skips a stream if its chunks have become empty
after a successful flush. Entries in the next WAL segment can still use that
stream's earlier reference. If its series declaration was in an older truncated
segment, replay has entries but no recovered reference until a later declaration.
This explains the reproduced semantic error without byte corruption; the affected
records' successful stored-chunk reads support the already-flushed path.

The candidate in `scripts/fixtures/loki-wal/retain-flushed-stream-reference.patch`
retains stream metadata even when its chunks were flushed during checkpointing.
The synthetic regression fails on 3.7.8 with an unset-user/reference recovery
error and passes with that change. It checks that the already-stored entry is
skipped by the existing counter, a newer unflushed entry is recovered, and an
unrelated unknown reference still fails. Fourteen surrounding checkpoint,
encoding, recovery and ingester-WAL tests pass in an offline container.

This is a candidate for review, not a deployed image or a repair to an
already-incomplete checkpoint. Its test models the flush/checkpoint boundary;
full concurrency/load validation and the separate counter-reset issue remain
release gates. Keep WAL and flush-on-shutdown enabled. Do not suppress unknown
reference errors, truncate WAL, run fsck, replace the original PVC, or restore
this diagnostic clone into production.

### Production handoff and rollback

Recommend no immediate production data repair: captured records are available.
Prepare a reviewed upstream release or pinned patched Loki image that retains
flushed-stream references and includes the returned recovery error in logging.
Before proposing rollout, run this fixture plus an end-to-end filesystem-backed
restart drill with numbered logs, forced checkpoint/flush overlap, a second
restart after a completed new checkpoint, and a true missing-reference negative
control. PR 25162's separate counter-reset risk must be assessed independently;
this candidate does not fix it.

Once an exact tested image digest exists, present the HelmRelease image change
and obtain production rollout authorization. Take another retained snapshot,
record canary IDs and all original identities, and let Flux replace only Loki.
Stop after five minutes if readiness fails, any numbered entry ages toward its
five-minute delivery budget, or storage/queue errors appear. Revert the exact
image/config commit and reconcile `observability/loki` to roll back; retain the
original PVC and all snapshots. A first boot may still report the existing
incomplete checkpoint: the prevention patch cannot invent missing historical
metadata. Do not use another restart just to clear the latched alert.

At this snapshot-investigation checkpoint, remaining work was candidate review
and clone cleanup. See the subsequent review/build execution below. Keep the snapshot/content and
private encrypted evidence until that review is complete.

Final verification at 19:51 UTC: all seven production Loki/collector/canary pods
are Ready with zero new restarts; original Loki UID is unchanged, all three
canary pending ages and collector queues are zero, original Longhorn volume is
healthy, and SeaweedFS reports zero read-only volumes. Firing alerts are only
the historical latched `LokiWALRecoveryFailure`, the known fan alert and Watchdog.
The class patch passed 449 repository tests; the candidate passed 14 offline
upstream tests. No new storage or log-delivery alert appeared.

Private evidence: `.private/loki-wal-replay/` contains snapshot/clone/controller
identities, the encrypted archive and manifest, repeated replay results, bounded
Loki comparisons, before/after regression logs and final health checks. The
rerunnable public harness is `scripts/replay-loki-wal.py` with its fixture README.

Principles applied: **Fix Root Causes** selected the returned missing-reference
error instead of a corruption repair; **Build the Lever** produced the offline
replay runner and fixtures; **Prove It Works** required baseline hashes, two
replays, exact record comparisons and failing-before/passing-after regression.

- 2026-10-19: Operator authorized candidate review/build/restart tests and clone deletion. Review rejected the checkpoint-only image after 128/256 control records were lost; combined checkpoint/counter image passed 640/640 records through six restarts, 1,118/1,118 collector replay records and a real missing-reference error control. Clone deleted; retained snapshot/evidence and original production resources preserved.

## Subsequent review and pinned image, 2026-10-19

The operator authorized review, a pinned image build, checkpoint/flush overlap
and repeated-restart loss checks, plus deletion of the detached clone. This does
not authorize production rollout or publication to a registry.

**Review supersedes the checkpoint-only recommendation above.** Independent
review found that serializing an empty stream with its old `EntryCt` interacts
with same-label stream recreation. The old counter can discard newly
acknowledged entries whose counters restarted from zero. The checkpoint-only
image lost **128/256 numbered logs** in the actual amd64 overlap/crash negative
control. The strengthened Go regression also failed on the missing recreated
entry. That candidate is rejected.

The reviewed combined patch is `scripts/fixtures/loki-wal/checkpoint-and-counter.patch`:
reference retention, a bounded per-tenant removed-stream counter floor adapted
from upstream PR 25162 commit `9cf0657212438f968facc96a34202f992b23ac49`, preservation
of persisted counter gaps during replay, and actual returned recovery errors in
startup logs. The upstream proposal remains unmerged at review time. Independent
review found no further code blocker. The test now covers an iterator holding
an old stream before flush/removal, two entries after recreation, a write after
restart, and another removal/recreation followed by replay. These changes prevent
new failures; they cannot heal references or counters already missing/reused in
historical WAL.

The local linux/amd64 OCI candidate is version `3.7.8-anton.wal.1`:

- Manifest: `sha256:c8aebc49d956fe2457c10d5acdce3810ea87cbeea3e9fd8d58cb0fd7d6c53347`.
- Loaded image config: `sha256:e08b7f504501aada07bd6d4b79c4468f6480393740c483d1c3785cafaf1f2370`.
- Binary SHA256: `a1e3d8e7213a775016b48852d4d659c94e6e81665bcd8671f624fff16cbc5f39`.
- Patch SHA256: `92e9f628ece3a02306579ebd0e8b3b22b54d4b384bfbd5c3daa7057b520f99f4`.
- Source: v3.7.8 revision `09e6ce2ff1bdc19763a10265b870c86f51c98655`.
- Pinned Go 1.26.6 toolchain and original pinned amd64 Loki runtime base;
  generated binary version output verifies revision, patch hash, Go version and platform.
- Local archive: `.private/loki-wal-replay/image/candidate/loki-wal-candidate.oci.tar`;
  provenance: sibling `image.json`. It is not pushed or production-deployed.

`scripts/build-loki-wal-image.py` verifies the entire tracked source diff, builds
without network access, and exports OCI plus a loaded image. Exported config
and loaded config digests must match. Temporary packaging builder is removed.
The daemon's default driver could not export OCI; the reproducible command uses
a temporary docker-container builder instead.

Actual-image verification with `scripts/verify-loki-checkpoint-restarts.py` ran
on the amd64 artifact under local emulation. Two overlap cycles exercised six
restarts (SIGKILL, graceful restart, then another completed checkpoint/SIGKILL
per cycle). **640/640 acknowledged numbered logs** remained queryable with no
extra or duplicate results. Runtime overlap required checkpoint start/end and
all old chunks removed before completion. The Go fixture establishes the precise
iterator-capture ordering; the runtime integration alone does not. All recoveries
reported checkpoint/segment `errors=false`. Focused upstream checkpoint,
recovery, recreation and WAL tests passed with `-race` on native arm64 Go 1.26.6.

The existing collector durability fixture now accepts an immutable `--loki-image`.
With this candidate, an HTTP503 backend outage, two collector SIGKILLs, a graceful
collector restart and a Loki restart recovered **1,118/1,118** records. Shutdown
messages reported 588 items dropped, but all numbered records replayed from the
durable queue. This remains the verified shutdown interruption behavior, not an
observed loss count.

The synthetic missing-reference image control also passed: the real runtime
reported failure counter one and logged `stream (999) not set during WAL replay
for user (fake)`, while 64 newly acknowledged logs remained queryable. Required
WAL metrics and checkpoint/segment startup evidence were asserted; missing
metrics cannot silently skip recovery coverage. The error vector is normally
absent until a failure, so clean recovery is also required explicitly in logs.

Final artifact verification checked all 21 OCI blobs. Archive SHA256 is
`e608c9aea839d8b3c18a14dcef23176accd5909297de5651aacafa84a38b0764`.
Contract validation passed 449 tests. All test containers, internal networks and
the temporary packaging builder were removed. Final read-only cluster evidence
shows original Loki pod UID unchanged, all seven Loki/collector/canary pods Ready,
18/18 Longhorn volumes healthy, no SeaweedFS read-only volumes, no new storage or
log-delivery alert, and the existing historical WAL counter still latched.

Cleanup: approved PVC `observability/loki-wal-replay-20261019-a`, its PV and
Longhorn volume `pvc-3d4e071c-0234-4a05-8fab-a0d377c8b16b` are absent. The original
Loki volume and pod were preserved. Snapshot/content and encrypted original
archive remain retained. No production configuration or image was changed.

Production handoff still needs a separately authorized registry publication and
rollout. Before upgrading, retain a fresh snapshot and drain/verify old accepted
records in object storage, because old aliased counters are not repaired by this
patch. **A plain image revert is not a verified downgrade:** older replay code
does not preserve the newer counter gaps. Rehearse the exact flush/checkpoint and
downgrade procedure before approving rollback, or select a forward fix. Do not
truncate/delete the original WAL, restore the diagnostic clone in place, or
restart production simply to clear the historical alert counter.

Principles: **Fix Root Causes** rejected the narrower patch after exposing its
counter interaction; **Test Behavior, Not Implementation** required exact
numbered log contents across crashes and stream recreation; **Prove It Works**
required the actual pinned amd64 image, failing control, race tests and retained
OCI provenance.

## Downgrade rehearsal and rollout authorization, 2026-10-19

The operator authorized downgrade rehearsal, committing/pushing the fix,
publishing the pinned image to Harbor, fresh snapshot capture and safe Flux
rollout with delivery/storage/alert verification. The original volume and WAL
remain preserved.

The downgrade rehearsal passed **448/448** numbered records: three candidate
restarts, a drained switch to the exact upstream amd64 3.7.8 image, a crash after
64 new writes, and a graceful restart after another 64 writes. The old process
uses `/data/wal-downgrade` on the same filesystem fixture. All original WAL file
hashes remain unchanged. Before cutover, 320/320 records were served from stored
chunks with no matching memory chunks, and the candidate exited cleanly.

The safe rollback is therefore **drain, clean shutdown, old image with a new WAL
directory**. It is not a plain image revert against newer counter history. In
production, preserve `/var/loki/wal` and each later WAL directory, use a new
explicit WAL directory for each image-compatibility cutover, and retain snapshots.
Do not switch WAL directories after a forced/unclean shutdown without recovering
and verifying the unflushed records first. Check numbered logs and stored-chunk
coverage, require clean shutdown and no S3/flush failures, then verify new writes
through another restart in the rehearsal. No WAL truncation/deletion is involved.

Harbor publication uses `192.168.1.106/library/loki-wal` and must preserve the
verified OCI manifest digest. The registry guide requires a scoped robot token;
1Password CLI metadata access timed out and available cached credentials were
admin accounts. An authentication-path question is pending with the operator;
publication and production rollout must wait for that answer. Repository
validation and the commit can proceed independently.

## Publication checkpoint, 2026-10-19 20:52 UTC

The fix and reproducible rehearsal tooling are committed and pushed as
`58533d7c09cff80622dfa8f1b4f2f80834824d02`; the privacy workflow passed.
The prepared deployment values pass all 449 contract tests and render the exact
candidate OCI digest. They remain uncommitted pending verified publication and
the drain/clean-shutdown gate. A rendered maintenance post-renderer scales only
the Loki StatefulSet to zero while retaining its PVC; the chart's replica helper
otherwise forces at least one replica, so setting replicas to zero alone is
insufficient. This maintenance change has not been applied.

Fresh pre-upgrade snapshot `observability/loki-wal-preupgrade-20261019-a`
was created at 20:45:53 UTC, is ready, and retains the original 20 GiB volume.
Snapshot UID is `2bed0ae8-39d0-4154-80b9-21b59757ee6a`, content is
`snapcontent-2bed0ae8-39d0-4154-80b9-21b59757ee6a`, and the backend handle is
`snap://pvc-359371d0-80ba-4208-a125-c17127538585/snapshot-2bed0ae8-39d0-4154-80b9-21b59757ee6a`.
Original Loki pod UID, image, PVC and WAL remain unchanged. At 20:49 UTC,
18/18 Longhorn volumes were healthy, SeaweedFS had no read-only volumes,
collectors/canaries were ready, and no additional storage or log-delivery
failure was firing. The historical WAL recovery alert remains active.

The operator selected the path of finding an existing scoped Harbor robot in
1Password and unlocked the app. CLI session setup still failed after the authorization prompts were
accepted; an operator-side `op whoami` check is pending. Do not substitute cached
admin credentials or create another robot without authorization.

The installed Crane 0.21.5 also rejected Harbor's same-host private-IP token
realm. An isolated client was built from upstream's merged same-host fix,
commit `bf87c3bfe4cc3218ac0baa364545d72729d2906d`, without replacing the installed
binary. It successfully reached Harbor and confirmed the target repository/tag
is absent. The OCI layout was extracted after verifying the archive checksum;
its manifest digest remains unchanged. Publication has not occurred.

Private evidence is under `.private/loki-wal-replay/rollout/`, including the
fresh snapshot identities, contract output, OCI layout and downgrade results.
The original snapshot and encrypted archive remain retained. Resume with scoped
robot authentication, exact-digest publication and anonymous-pull verification,
then the approved drain, clean stop and fresh WAL epoch cutover. Never switch
WAL directories after an unclean stop without recovering unflushed records.

## Harbor publication and S3 cache gate, 2026-10-19

1Password CLI access recovered after the operator signed in. Matching Harbor
items in anton and Personal contained admin credentials; no matching scoped
robot credential was found. The operator explicitly approved a one-day robot
scoped to library pull/push, token storage in anton, and revocation/credential
cleanup after the publication attempt.

Temporary robot 53 (`robot$library+loki-wal-publish-20261019-a`) was created,
its permissions read back, and its token stored in the temporary 1Password item.
The exact OCI layout push then encountered repeated Harbor HTTP500 responses:
`s3aws: unexpected EOF`. The attempt was stopped, robot 53 revoked, its temporary
credential item deleted, and the isolated client auth directory removed.
Publication has not succeeded; production Loki remains unchanged.

Both SeaweedFS S3 gateways logged read timeouts to `10.42.2.214:8444` for volumes
22 and 23, while master lookups returned `10.42.2.162:8444`, the current healthy
seaweedfs-volume-1 address. This matches the documented stale volume-address
cache failure. Longhorn health and read-only volume gauges do not prove this S3
read path is healthy. Current S3 Deployment has two ready replicas. Airflow,
lakehouse and spark-system namespaces, writer pods and writer leases are absent;
the SparkApplication CRD is also absent, so do not apply the historical writer
workflow as though it were still deployed.

The operator has been asked to approve a rolling restart of only
`storage/deployment/seaweedfs-s3`, temporary S3 write/read/delete verification,
and publication retry. That storage mutation has not been performed. Retain the
fresh Loki snapshot and original WAL; do not start Loki maintenance until S3
health and exact-digest image publication/pull are verified. Private evidence:
`.private/loki-wal-replay/rollout/s3-cache-failure.json` and `publication.json`.

A separate preflight alert affects a private workload: one of two desired
replicas is ready. The deployment reports Kyverno rejecting replacement creation
because its image-verification auth field cannot be decoded as base64. It is
outside this Loki rollout and was not changed.

## Verified production cutover, 2026-10-19

The approved S3 gateway rolling restart restored the blocked Harbor read path.
Both replacement gateways became Ready and stopped logging reads to the removed
volume-pod address. The scoped Harbor-bucket smoke Job wrote/read exactly
638,976 bytes (SHA256 `94f43e498bdccf42fabcaab4880053e6b00486d70ff3f3354f7649a981fce05a`),
deleted its unique temporary object, and verified HEAD returned 404 afterward.
The source of the historical stale-address failure remains a separate SeaweedFS
limitation; a gateway restart clears this occurrence but does not prevent future
cache stalls after another volume address change.

The candidate was published to `192.168.1.106/library/loki-wal:3.7.8-anton.wal.1`.
Authenticated and anonymous reads verified manifest digest
`sha256:c8aebc49d956fe2457c10d5acdce3810ea87cbeea3e9fd8d58cb0fd7d6c53347`
and linux/amd64. Temporary robots 53 and 54 were revoked; server request logs
confirm HTTP 200 for both exact deletions. Their temporary 1Password items were
deleted and isolated authentication directories removed. No admin credential
was used for an image push.

A second fresh pre-upgrade snapshot, `observability/loki-wal-preupgrade-20261019-b`,
UID `afdcc383-b4de-4d6c-aa38-b39193936b0d`, is Ready and Retain. It was taken
before the Loki drain after the publication delay. The earlier pre-upgrade and
forensic snapshots remain Ready. The encrypted forensic archive hash is
unchanged, and its key remains retained with mode 0600.

The final source sequence is:

- `58533d7c`: checkpoint/counter fix, fixtures and reproducible build/restart tools.
- `87d031b8`: temporary Helm post-renderer scales only Loki to zero, preserving PVC.
- `241a1cdd`: restore one replica with the immutable Harbor digest, explicit
  `/var/loki/wal-anton-20261019-a`, WAL enabled, shutdown flushing and 120-second
  termination grace. The temporary post-renderer is removed.

Before maintenance, 85/85 frozen numbered records were queried from stored
chunks with zero matching memory chunks. `/ingester/shutdown?flush=true&terminate=false`
returned HTTP 204 at 21:26:33 UTC. The original Loki container then exited 0 at
21:27:02 UTC; no forced termination or WAL truncation was used. Helm release v16,
generation 11, became Ready at 21:28:40 UTC. The replacement pod's imageID and
build-info version `3.7.8-anton.wal.1`, revision `09e6ce2f-92e9f628ece3`, Go 1.26.6
and amd64 match the tested artifact. Both containers have zero restarts.
The original PVC UID and Longhorn handle are unchanged. Talos read-only listings
on the replacement node verify both the original `wal` directory and the new
WAL directory remain present.

The production collector-to-Loki ledger verified **1,800/1,800** source-emitted
numbered records across the planned backend outage, with no missing, unexpected
or duplicate query results. After the new instance flushed, all 1,800 were read
from four stored chunks with zero matching memory chunks. All three production
canaries caught up. Collectors retained their original pod UIDs and zero restarts;
each logged 18 retryable exports during downtime and none logged dropped-data or
checkpoint/storage failure messages. This is bounded evidence for the numbered
fixture and canaries, not a proof about every arbitrary historical log.

The first scheduled production checkpoint started at 21:32:56 UTC and completed
its atomic rename at 21:37:26 UTC, taking 4m30.031781376s with the checkpoint
creation-failure counter at zero. A fresh query after completion again matched
all 1,800 exact source timestamp/body-hash pairs, served from four stored chunks
with no matching memory chunks. This observes one normal checkpoint cycle; the
crash/recreation/downgrade cases remain the isolated actual-image rehearsals.

Final acceptance at 21:37:38 UTC found all seven Loki/collector/canary pods Ready
with zero restarts, 18/18 Longhorn volumes healthy, zero SeaweedFS read-only
volumes, maximum oldest unconfirmed canary age 4.1 seconds, and maximum collector
queue 6,008 bytes out of 64 MiB per collector. Prometheus and Alertmanager had no
active storage or log-loss alert; the original WAL recovery alert resolved.
Only the known physical-fan alert and Watchdog remained active in Alertmanager.
All 16 relevant Prometheus rules were healthy. No new storage or delivery alert
fired in the observed rollout window. Initial singleton memberlist/query errors
during cold start resolved before readiness, with no later Loki runtime errors
in the verification window.

The final source passed all 449 contract tests and the GitHub public-privacy
workflow. An incident-note privacy failure was corrected by the concurrent
redaction commit `f06e8855`; the newer main commits were integrated before the
rollout. The current public source passes the privacy gate. The earlier Git
history retains the corrected private identifiers; no credentials were present.

Temporary S3 and ledger Jobs and their owned Pods are confirmed absent. Their
synthetic source/query evidence, startup/clean-stop evidence, OCI provenance,
S3 cache comparison and cleanup receipts remain under ignored
`.private/loki-wal-replay/rollout/`. No temporary listener or test alert was
created. The snapshot backend artifacts and original evidence remain retained.

Rollback remains the rehearsed drain, complete flush and clean shutdown, then
the exact upstream image with another fresh WAL directory on the same PVC.
Do not perform a plain image revert against the new counter history, switch WAL
directories after an unclean stop without recovery, or delete old WAL directories.
The custom patch remains a maintained pinned image until an upstream release
containing the reviewed fixes is separately qualified.

Principles: **Fix Root Causes** addressed the checkpoint and replay-counter
interaction rather than suppressing its warning; **Test Behavior, Not
Implementation** required exact numbered contents across crashes, downgrade and
production cutover; **Build the Lever** retained reproducible build and restart
harnesses; **Prove It Works** gated cutover on the actual image digest, durable
stored-chunk queries, clean exit, applied generations and live alert health.

## References

- Related ADRs: 0005, 0032, 0042.
- Investigation evidence: ignored `.private/wal-shutdown-investigation/report.json`; bounded comparison and HTTP503 replay scripts retained alongside it. Do not commit raw logs or WAL.
- Flux owners: `observability/loki`, `storage/longhorn`, `storage/longhorn-config`, `kube-system/snapshot-controller-app` and snapshot CRDs.
- [Longhorn CSI snapshots](https://longhorn.io/docs/1.12.1/snapshots-and-backups/csi-snapshot-support/csi-volume-snapshot-associated-with-longhorn-snapshot/).
- [Loki 3.7.8 recovery logging](https://github.com/grafana/loki/blob/v3.7.8/pkg/ingester/ingester.go#L599), [replay implementation](https://github.com/grafana/loki/blob/v3.7.8/pkg/ingester/recovery.go#L191).
- [Separate upstream replay-counter issue](https://github.com/grafana/loki/issues/25118), [proposed fix](https://github.com/grafana/loki/pull/25162).
