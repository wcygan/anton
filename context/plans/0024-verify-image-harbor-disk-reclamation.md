---
status: In-progress
opened: 2026-10-13
closed: null
affects: storage
intent: concrete-need
related-adrs: [0005, 0006, 0015]
review-by: 2026-10-20
---

# 0024 — Verify node images and Harbor disk reclamation

## Goal

Prove actual physical savings from kubelet image GC and Harbor retention/GC,
SeaweedFS compaction, and Longhorn trim. Preserve active images, volume and
replica specs, resource requests, and service availability. The operator
authorized this plan's staged jobs, inspections, compaction and trim on
October 13. No broad pruning, direct containerd deletion, backups, or new
persistent service is authorized.

## Acceptance criteria

- [ ] A post-aging node inventory separates references, unique digests, CRI
  usage, and filesystem space without asserting candidate bytes are reclaimable.
- [x] Harbor's complete GC policy matches Git; authenticated inspection is GET-only.
- [ ] October 18 scheduled real GC and preceding retention succeed; retained
  active manifests and blobs remain readable.
- [ ] One healthy Harbor-only compaction/trim pilot demonstrates physical
  reclamation before weekly automation is published through GitOps.
- [x] Tests and cluster health pass; weekly read-only review understands aging
  windows, disabled backups, and each storage layer's measurement semantics.

## Tasks

- [x] Implement and collect the private node image baseline.
- [x] Deploy full GC-policy reconciliation and GET-only inspection; verify live.
- [x] Prepare and test gated compaction and unpublished automation templates.
- [x] Migrate both filer indexes to durable metadata PVCs and verify matching exports.
- [x] Repair rollback/untagged/inventory retention gaps and pass guarded live dry runs.
- [ ] Verify October 18 GC; wait one hour after completion, then pilot eligible
  Harbor volumes serially and trim only their affected SeaweedFS PVCs.
- [ ] Publish maintenance/trim automation only after the pilot passes.
- [ ] Compare node images October 20 at 09:00 America/Chicago; if kubelet
  restarted, defer age eligibility to its latest start +168h +30m.

## Execution boundaries and commands

`mise exec -- task storage:image-inventory -- --output
.private/reclamation/node-images-2026-10-13.json` preserves baseline evidence.
For the comparison add `--compare .private/reclamation/node-images-2026-10-13.json`
and use a new output filename. Inventory includes retained ReplicaSets for
rollback protection and every runtime record, including exited containers.

Harbor `MODE=inspect` uses only authenticated GETs with the existing Secret
reference inside the job. Never fetch Secret data into this chat. Use a Job
derived from the retention CronJob for inspection; capture sanitized JSON,
then delete that exact temporary Job. Retention/GC writes remain owned by the
Git-managed reconciler and Harbor scheduler.
Remove the generated CronJob ownerReferences from manual Jobs: its one-success
history policy can otherwise delete completed diagnostic evidence before it is
captured. Keep the explicit TTL and delete each independent Job after capture.
Use `restartPolicy: Never` as well as `backoffLimit: 0`; inheriting OnFailure
can restart and delete a failed diagnostic pod before its error is retained.

`MODE=verify-images` resolves active/desired workload artifacts through Harbor's
API, obtains registry tokens inside the Job, verifies manifest graphs and blob
HEAD requests, and reports counts only. A missing manifest/blob fails the Job;
no registry credentials or tokens leave it.

Compaction requires the current week's scheduled successful real GC, successful
preceding project retention, and at least one hour since GC completion.
Targets must be verified Harbor collection IDs with >=256MiB deleted and >=10%
garbage, writable with another writable Harbor volume, and host filesystem
available space greater than twice volume size. Fail closed on ambiguity.
Use locked SeaweedFS 4.40 `weed shell volume.vacuum` with explicit collection
and volume ID, never the unscoped HTTP vacuum endpoint. Mutate one target,
verify completion/health, then continue. No retry after an uncertain mutation.

Weekly compaction schedule after pilot: Sunday 07:30 UTC (02:30 CDT).
Separate SeaweedFS Longhorn trim: Sunday 08:30 UTC (03:30 CDT), concurrency one,
snapshot removal false. Existing observability trim stays separate.

## Pilot and activation handoff

The ConfigMap already carries `reclamation.sh` and `reclamation-gates.jq`;
the CronJob/identity manifests are under `harbor-config/app/staged/`, and
storage RBAC/trim manifests under `longhorn-maintenance/app/staged/`.
They are intentionally absent from the Kustomize resources lists. Do not
publish them before the acceptance gates above pass.

At the October 18 follow-up, inspect/verify through temporary Jobs, capture
Seaweed volume `/status` and Longhorn disk allocation, and retain those private
reports. If eligible, temporary scoped identity/RBAC may be applied for the
pilot. Derive a Job from the staged CronJob's jobTemplate, use a unique exact
name, `MODE=apply-reclamation`, `VOLUME_ID=<verified candidate ID>`, no retries,
and a fifteen-minute deadline (the expanded readable inventory takes about
two minutes per check under the unchanged 100m CPU limit). Run only one target first. The script requires
the current week's scheduled successful real GC plus preceding retention,
one-hour cooldown, all health/space gates, and checks CompactRevision and size
after mutation. Stop on any uncertain result; do not bypass the gates.

After measured compaction, use the existing supported Longhorn `trimFilesystem`
API for the affected attached volume, keeping snapshot removal false. Record
filesystem free bytes and Longhorn physical allocation before/after, unchanged
volume/replica specs, and retained-image verification. Continue additional
eligible targets serially only while checks pass. A successful command or
nominal deleted-byte counter alone does not prove physical reclamation.

Once the pilot demonstrates savings, publish the prepared manifests by adding
their `./staged/...` paths to their owning Kustomizations. Revalidate the three
SeaweedFS PVC-to-Longhorn IDs first; refresh metadata-only volume labels if IDs
changed. Confirm the namespaces/RBAC and server admission in dry run before
publishing. Let Flux take ownership of pilot RBAC or delete those exact
temporary resources if not activated. Delete every temporary pilot/inspection
Job after evidence capture. Keep successful/failed weekly maintenance logs for
seven days so the Monday read-only review can check the recorded GC ID.

## Scheduled continuation

- `harbor-reclamation-pilot`: one-time heartbeat October 18 at 02:15
  America/Chicago. It must defer if the GC completion cooldown is not satisfied.
- `node-image-aging-verification`: one-time heartbeat October 20 at 09:00
  America/Chicago; reads only, defers eligibility after any kubelet restart.
- Existing `weekly-anton-resource-review` remains Mondays 09:00 and read-only;
  it must not flag the October 19 morning image-aging grace window as a failure.

## Retained-image repair

The new reader exposed existing registry content missing behind intact Harbor
artifact metadata. BusyBox, the NVMe collector and the storage VXLAN helper
returned `MANIFEST_UNKNOWN`; pull authorization succeeded. S3 reads confirmed
the BusyBox repository revision link and manifest blob were absent at the
configured registry path. This is a content inconsistency, not a token or
frontend routing fault. The event that originally removed the content is not
established by the retained evidence; do not attribute it to this cleanup.

The operator separately authorized investigation and repair on October 13.
BusyBox was restored from Docker Hub at exactly its existing manifest digest.
Both custom images were recovered at their existing digests through Spegel's
node cache. Every source manifest and config/layer blob was SHA-256 verified
before registry uploads; restored manifests were read back and digest checked.
The repairs used the supported registry API, added content without deleting
artifacts, preserved existing tags and workload references, and required no
workload restarts. Credentials remained inside short-lived Jobs using the
existing Secret references.

Physical maintenance still requires the scheduled real GC, readable retained
images, cooldown, healthy storage and measured pilot savings. Missing retained
images now fail the compaction script before any storage mutation. Private
sanitized diagnostic/status evidence is in `.private/reclamation/`; temporary
Jobs are deleted after capture. No real GC, compaction, trim, or manual image
deletion ran in this implementation turn.

## Log

- 2026-10-13: User approved implementation. Sunday GC and Tuesday image-aging
  checks are future gates; maintenance automation must not be enabled early.
- 2026-10-13: Baseline: 252.319GiB CRI imageFs, references 1308/1029/1405 and
  unique digests 465/363/504. Conservative unmatched candidates total 2187
  references/766 per-node digests; no physical reclaim estimate is asserted.
- 2026-10-13: Live Harbor inspection found its schedule options in JSON
  `job_parameters`, with false `dry_run` omitted; both formats are covered by
  tests. Both latest retention runs succeeded; only dry-run GC 673 exists.
- 2026-10-13: One-time continuation heartbeats created and weekly read-only
  instructions refreshed. Compaction/trim automation remains unpublished.
- 2026-10-13: Prepared manifest/blob reader, serial fail-closed compaction script,
  scoped staged RBAC and schedules. All 378 contract tests and strict Flux
  ConfigMap substitution passed. The deployed GC options normalize to
  dry_run=false, delete_untagged=false and workers=1 without exposing credentials.
- 2026-10-13: Independent reconciliation Job completed; matching GC schedule was
  not rewritten. Manifest verification failed with the BusyBox inconsistency
  above; the operator subsequently authorized its content repair.

- 2026-10-13: Contract validation passed all 380 tests, including missing manifest/blob failure and prevention of compaction when retained-image verification fails.
- 2026-10-13: Repaired all three retained images at their original digests. Final reader Job completed: 3 artifacts and 8 referenced blobs readable. All nodes/storage/Flux/services and 72/72 scrapes healthy; no new container restarts in the task window. Volume and replica specs unchanged. The historical content-removal event remains unknown.

- 2026-10-13, 23:01 UTC: Read-only continuation checkpoint passed: three nodes,
  all 18 Longhorn volumes, 55 Kustomizations, 27 HelmReleases and 72/72 scrapes
  healthy; Cilium 3/3, operator/CoreDNS 2/2 and persistent filers 2/2 ready.
  Replicas, limits and Longhorn CPU reservations remain unchanged. Daily
  guarded retention is enabled for 01:30 UTC (20:30 CDT on October 13 for its
  next run). Both dated follow-ups and the weekly review are active. QMD's
  stale context index was rebuilt and the current plan is retrievable.
  October 18 real GC/pilot and October 20 post-aging comparison remain pending;
  no cleanup or cluster mutation was performed at this checkpoint.

## Filer durability and retention repair — October 13

The operator authorized a staged filer metadata migration and retention repair,
with physical reclamation held until the new safety checks pass. Both filers
previously kept their LevelDB indexes in container-local `/data/filerldb2`;
neither mounted durable metadata storage. Older private exports already lacked
Harbor image paths despite intact Harbor database records. This strongly
supports lost filer indexes as the cause of the metadata/content mismatch;
it does not identify an exact blob-deletion event or prove that retention
deleted the missing content. PR 469 proposed persistence but was never merged.

Implemented persistence on both existing filers, without a new service or backup
system. Each mounts a retained 4Gi Longhorn claim under `/data`. The operator
1.0.39 replaces the StatefulSet when adding claim templates, so the migration
orphaned existing Pods, recreated the StatefulSet with temporary OnDelete,
seeded each claim from live metadata/changelog, and replaced one filer at a
time. Final replicas remain two and the original RollingUpdate strategy is
restored. Flux and the SeaweedFS operator are resumed. Private export, Pod UID,
and storage specification evidence lives in
`.private/filer-migration-2026-10-13/`.

Loki continued writing throughout migration. Comparisons therefore check
records stable across source exports rather than treating normal churn as loss.
Two recent Loki entries required a targeted replay from the intact peer.
SeaweedFS 4.40's `fs.meta.load` does not wait for its final file goroutine at EOF;
the replay included a trailing directory record to fence completion. Final
exports match all 3,207 records, including 340 Harbor records. The original
16 Longhorn volume specifications and 32 replica specifications are unchanged;
the two new metadata volumes are healthy.

Retention now inventories init containers, runtime digest identities,
scheduled Jobs, scaled-to-zero controllers, retained ReplicaSets and
ControllerRevisions, and Harbor ingress/internal aliases. Two older CS2
rollback manifests were additionally restored at their original digests from
SHA-256-verified Spegel cache bytes through the supported registry API.

The three project retention rules retain latest two pushed tagged artifacts,
protected `in-use-*`/`rollback` tags, and all untagged artifacts. Native retention
scheduling is disabled with `trigger.kind: ""` (omitted in Harbor responses): Harbor 2.15.2 accepts a transition
to `Manual` but rejects later updates with that kind; the empty kind is its
supported unscheduled form. Only the Git-managed 01:30 UTC CronJob may submit
retention after readable inventory and healthy persistent filer checks. It
rechecks inventory before execution, waits for each execution's actual success,
and verifies images afterward. There are no automatic mutation retries.

Real retention publishes proof in `registries/harbor-retention-status`:
schema/state, execution IDs/status, completion time, inventory SHA-256, and
filer PVC UIDs/Longhorn mapping. A dry run cannot publish real success proof.
Physical maintenance additionally requires fresh proof preceding that week's
real scheduled GC, matching current inventory/storage identity, safe retention
policy, healthy targets and the existing cooldown/space/threshold checks.
Temporary validation exposed inventory memory/argument-size failures; the
reader now fetches one workload kind at a time and projects only relevant
fields into bounded ephemeral scratch. Requests, limits and replicas remain
unchanged. The recurring retention Job has a bounded 30-minute deadline to
cover repeated inventories and both project executions; physical maintenance
already has the same bound. All 392 repository contract tests pass, including large inventory,
rollback/alias/runtime ambiguity, filer persistence, failed retention, dry-run
proof exclusion and changed/stale proof rejection.

The October 18 GC/physical pilot and October 20 node-image comparison remain
future acceptance gates. Compaction and SeaweedFS trim automation remain staged
and absent from rendered resources until measured pilot savings. The weekly
review and pilot instructions now require the new persistence/protection proof.

Live safety verification passed for five protected artifacts and 54 referenced
blobs. The guarded dry run completed executions 675 and 676 successfully,
rechecked unchanged inventory, and verified images/filers afterward. Its proof
has `dry_run:true` and is deliberately not published as real retention evidence.
The recurring daily retention and Sunday GC policies are released after these
checks; physical automation remains staged until the October 18 real-GC pilot.
Harbor's normal writes are restored. Temporary migration clients/configuration,
completed diagnostic Jobs and master-local exports are removed after evidence
capture; private operator evidence is retained. Nodes, all 18 Longhorn volumes,
55 Kustomizations, 27 HelmReleases and all 72 scrapes are healthy.

Pinned implementation references:

- [Harbor 2.15.2 unscheduled policy handling](https://github.com/goharbor/harbor/blob/v2.15.2/src/controller/retention/controller.go)
- [SeaweedFS 4.40 metadata loader](https://github.com/seaweedfs/seaweedfs/blob/4.40/weed/shell/command_fs_meta_load.go)

## References

- [Storage reclamation baseline](../notes/2026-10-12-storage-reclamation.md)
- [Intentional backup disablement](../notes/2026-10-13-disable-longhorn-backups.md)
- Kubernetes image GC: https://kubernetes.io/docs/concepts/architecture/garbage-collection/
- Harbor GC: https://goharbor.io/docs/main/administration/garbage-collection/
- SeaweedFS 4.40 scoped shell command: https://github.com/seaweedfs/seaweedfs/blob/4.40/weed/shell/command_volume_vacuum.go
