---
name: longhorn-backup-dr
description: Configure Longhorn backup target (S3 or NFS), author RecurringJobs for snapshot/backup/filesystem-trim, and restore a volume from a backup. Use when wiring up backups for the first time, editing recurring schedules, or performing a DR restore. Not for PVC create (longhorn-volume-ops) or disk work (longhorn-node-ops).
---

# longhorn-backup-dr

Backup and disaster-recovery operations for Longhorn on anton.

## Status

External backup targets remain unset. Cluster data and recovery verification must stay inside Anton; do not stream backups, database dumps, S3 payloads or volume archives to the operator computer or an external destination.

`storage/cluster-recovery` owns monthly in-cluster CSI checkpoints and sampled restore verification for the current SeaweedFS and Loki PVCs. Read [the storage guide](../../../docs/docs/guides/storage.md#recurring-in-cluster-recovery-checkpoints) and its source under `kubernetes/apps/storage/longhorn-maintenance/app/` before operating it. Inspect the journal's verified report and exact UID registry, not snapshot readiness alone. Its Delete-policy class is separate from the existing Retain-policy forensic class and manual maintenance snapshots; never adopt or prune those historical objects.

These are same-cluster, per-volume crash-consistent checkpoints. They do not protect against cluster loss or prove coordinated Harbor database/S3 recovery, complete S3 integrity, or Loki WAL replay. A new external backup target requires a separate operator decision; the recipes below describe mechanisms, not authorization. Validate them against the deployed Longhorn version before use.

## Platform notes

Nothing Talos-specific for backup target wiring itself; see [`longhorn-node-ops/references/talos.md`](../longhorn-node-ops/references/talos.md) for the platform-level gotchas that already apply.

## Recipes

### Set backup target (S3)

S3 requires a Kubernetes Secret with `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and optional `AWS_ENDPOINTS` (for non-AWS S3). Prefer an ExternalSecret sourced from the 1Password `anton` vault — see `add-flux-app` for the template.

Configure the target via HelmRelease values:

```yaml
defaultSettings:
  backupTarget: s3://<bucket>@<region>/
  backupTargetCredentialSecret: longhorn-backup-credentials
```

### Author a RecurringJob

```yaml
apiVersion: longhorn.io/v1beta2
kind: RecurringJob
metadata:
  name: daily-backup
  namespace: storage
spec:
  cron: "0 3 * * *"
  task: backup            # snapshot | backup | filesystem-trim
  groups: [default]
  retain: 7
  concurrency: 2
```

Volumes with the label `recurringjob.longhorn.io/default: enabled` are picked up automatically. Prefer the `default` group so new PVCs opt in via label rather than per-volume job references.

### Restore-as-new-PVC

Use a CSI `VolumeSnapshot` as `dataSource` — the Kubernetes-idiomatic path. See [restore-flows](references/restore-flows.md) for the exact shape and when to reach for Longhorn's own restore CRs.

### DR volume

Continuously-syncing cross-cluster replication. Not an anton requirement today.

## References

- [Backup target config](references/backup-target.md) — S3/NFS target shapes, credentials, anton guidance
- [Recurring jobs](references/recurring-jobs.md) — task types, groups, retention, scheduling suggestions
- [Restore flows](references/restore-flows.md) — CSI snapshot restore vs Longhorn restore vs DR volume
- [Backup discipline](references/best-practices-backup-discipline.md) — snapshots ≠ backups, test restores, RPO tiering
