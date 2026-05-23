---
name: longhorn-restore-flows
description: Restoring Longhorn volumes from backup or snapshot.
---

# Restore flows

Canonical: https://longhorn.io/docs/1.11.1/snapshots-and-backups/backup-and-restore/restore-a-backup/

## Restore-as-new-PVC (preferred)

The Kubernetes-idiomatic path: create a new PVC with a CSI `VolumeSnapshot` `dataSource`. Requires the Longhorn `VolumeSnapshotClass` to exist.

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: restored
  namespace: <ns>
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 20Gi
  dataSource:
    apiGroup: snapshot.storage.k8s.io
    kind: VolumeSnapshot
    name: <snapshot-name>
```

For restoring a **backup** (off-cluster blob) rather than a snapshot, use a `VolumeSnapshot` referencing a `VolumeSnapshotContent` with `source.snapshotHandle` set to the backup URL (`bs://<backup-target>/...`). Details in the canonical docs.

## Restore-in-place (advanced)

Detach the workload, use Longhorn's UI or a `BackupVolume`-restore flow to overwrite the existing volume's replicas. Riskier — prefer restore-as-new-PVC then swap the workload to the restored PVC, verify, then delete the old one.

## DR volume

A DR volume replicates a backup target incrementally and can be activated ("promoted") on failover — used for cross-cluster DR, not anton's current shape.

## Safety habit

Before any restore, take a snapshot of the current (possibly broken) volume first. You can always delete the snapshot afterward; you cannot un-restore over good data.
