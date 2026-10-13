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

- [ ] Implement and collect the private node image baseline.
- [ ] Deploy full GC-policy reconciliation and GET-only inspection; verify live.
- [ ] Prepare and test gated compaction and unpublished automation templates.
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

## Log

- 2026-10-13: User approved implementation. Sunday GC and Tuesday image-aging
  checks are future gates; maintenance automation must not be enabled early.

## References

- [Storage reclamation baseline](../notes/2026-10-12-storage-reclamation.md)
- [Intentional backup disablement](../notes/2026-10-13-disable-longhorn-backups.md)
- Kubernetes image GC: https://kubernetes.io/docs/concepts/architecture/garbage-collection/
- Harbor GC: https://goharbor.io/docs/main/administration/garbage-collection/
- SeaweedFS 4.40 scoped shell command: https://github.com/seaweedfs/seaweedfs/blob/4.40/weed/shell/command_volume_vacuum.go
