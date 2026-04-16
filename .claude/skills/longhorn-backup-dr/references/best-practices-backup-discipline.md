---
name: longhorn-backup-discipline
description: Backup discipline best practices.
---

# Backup discipline

Canonical: https://longhorn.io/docs/1.11.1/best-practices/

## Snapshots are not backups

Snapshots live on the same disks as the volume. A disk failure loses the snapshot with the data. Always pair snapshots with a backup target for durability.

## Test restores

A backup is only as good as its most recent successful restore. Quarterly: pick a non-critical volume, restore-as-new-PVC, verify the data, delete the restored PVC. Untested backups are folklore, not infrastructure.

## Per-workload RPO

Not every PVC needs daily backup. Tier workloads:

- **Critical state** (databases, auth stores) → `backup` daily + `snapshot` every 6h.
- **Application caches** → `snapshot` daily; no backup (rebuildable).
- **Scratch / rebuildable** → no recurring job.

## Watch capacity

Recurring jobs silently consume space. Snapshots are sparse files that diverge from the live volume; older snapshots only reclaim their unique blocks when pruned. Monitor `nodes.longhorn.io[*].status.diskStatus[*].storageAvailable` and tune retention down if headroom drops below ~25%.

## Don't delete the last backup

Keep at least one confirmed-good backup off the cluster at all times, even when setting up a new target. The worst day to discover your backup target was misconfigured is the day you need it.
