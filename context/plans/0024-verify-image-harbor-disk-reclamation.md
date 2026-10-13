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
- [ ] Harbor's complete GC policy matches Git; authenticated inspection is GET-only.
- [ ] October 18 scheduled real GC and preceding retention succeed; retained
  active manifests and blobs remain readable.
- [ ] One healthy Harbor-only compaction/trim pilot demonstrates physical
  reclamation before weekly automation is published through GitOps.
- [ ] Tests and cluster health pass; weekly read-only review understands aging
  windows, disabled backups, and each storage layer's measurement semantics.

## Tasks

- [x] Implement and collect the private node image baseline.
- [ ] Deploy full GC-policy reconciliation and GET-only inspection; verify live.
- [x] Prepare and test gated compaction and unpublished automation templates.
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
and a five-minute deadline. Run only one target first. The script requires
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

## References

- [Storage reclamation baseline](../notes/2026-10-12-storage-reclamation.md)
- [Intentional backup disablement](../notes/2026-10-13-disable-longhorn-backups.md)
- Kubernetes image GC: https://kubernetes.io/docs/concepts/architecture/garbage-collection/
- Harbor GC: https://goharbor.io/docs/main/administration/garbage-collection/
- SeaweedFS 4.40 scoped shell command: https://github.com/seaweedfs/seaweedfs/blob/4.40/weed/shell/command_volume_vacuum.go
