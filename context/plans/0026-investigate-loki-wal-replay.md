---
status: In-progress
opened: 2026-10-19
closed: null
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
- [ ] Present exact files/commands, expected transition, timeout and rollback for any production change. The original volume remains authoritative; there is no restore-in-place or diagnostic-clone cutover in this plan. A diagnostic failure is handled by stopping the diagnostic workload, not by changing production data.
- [ ] After evidence is retained and the operator approves cleanup, remove only Job `loki-wal-reader-20261019-a`, NetworkPolicy `loki-wal-isolate-20261019-a` and clone PVC `loki-wal-replay-20261019-a`; keep the retained snapshot/content and encrypted evidence through review. Obtain a separate exact-target decision for final snapshot/backend-artifact deletion. `Retain` can leave backend artifacts intentionally; inventory them rather than using wildcard cleanup.
- [ ] Close this plan with the supported cause, proven data impact, actual repair validation and residual uncertainty. Keep the existing WAL recovery alert truthful; never restart merely to clear its lifetime counter.

## Log

- 2026-10-19: Prepared at the operator's request after one generic segment-recovery error during an overlapping restart. The process recovered its checkpoint, kernel checks found no storage-error signatures, and the durable collector replayed shutdown-interrupted requests. No snapshot, clone, replay workload or Loki restart was performed for this plan.

- 2026-10-19: Executed authorized capture and isolated replay; reproduced missing references, verified all captured records in Loki and a candidate checkpoint fix. Production repair remains a review/approval handoff; the diagnostic clone is retained pending storage-deletion approval.

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

Remaining work is production-candidate review/approval and explicit deletion
approval for the detached diagnostic clone. Keep the snapshot/content and
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

## References

- Related ADRs: 0005, 0032, 0042.
- Investigation evidence: ignored `.private/wal-shutdown-investigation/report.json`; bounded comparison and HTTP503 replay scripts retained alongside it. Do not commit raw logs or WAL.
- Flux owners: `observability/loki`, `storage/longhorn`, `storage/longhorn-config`, `kube-system/snapshot-controller-app` and snapshot CRDs.
- [Longhorn CSI snapshots](https://longhorn.io/docs/1.12.1/snapshots-and-backups/csi-snapshot-support/csi-volume-snapshot-associated-with-longhorn-snapshot/).
- [Loki 3.7.8 recovery logging](https://github.com/grafana/loki/blob/v3.7.8/pkg/ingester/ingester.go#L599), [replay implementation](https://github.com/grafana/loki/blob/v3.7.8/pkg/ingester/recovery.go#L191).
- [Separate upstream replay-counter issue](https://github.com/grafana/loki/issues/25118), [proposed fix](https://github.com/grafana/loki/pull/25162).
