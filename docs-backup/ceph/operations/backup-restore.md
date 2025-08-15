# Ceph Backup and Restore Procedures

## Overview
This document outlines backup and restore procedures for workloads using Ceph storage, leveraging Volsync for automated backups.

## Backup Architecture

- **Tool**: Volsync (rsync-based backup to external storage)
- **Snapshot Provider**: Ceph CSI snapshots
- **Backup Storage**: External NFS or S3 (must be configured)
- **Frequency**: Configurable per workload

## Prerequisites

- [ ] Volsync is deployed and healthy
- [ ] External backup storage is configured
- [ ] CSI snapshot support is verified

```bash
# Verify Volsync
kubectl -n storage get pods | grep volsync

# Verify snapshot support
kubectl get volumesnapshotclass
```

## Creating Backups

### 1. Manual Backup (One-Time)

For immediate backup of a PVC:

```bash
# Create a VolumeSnapshot
cat <<EOF | kubectl apply -f -
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: manual-backup-$(date +%Y%m%d-%H%M%S)
  namespace: <namespace>
spec:
  volumeSnapshotClassName: csi-cephfsplugin-snapclass
  source:
    persistentVolumeClaimName: <pvc-name>
EOF
```

### 2. Automated Backup with Volsync

Create a ReplicationSource for automated backups:

```yaml
apiVersion: volsync.backube/v1alpha1
kind: ReplicationSource
metadata:
  name: <app>-backup
  namespace: <namespace>
spec:
  sourcePVC: <pvc-name>
  trigger:
    schedule: "0 2 * * *"  # Daily at 2 AM
  restic:
    pruneIntervalDays: 7
    retain:
      daily: 7
      weekly: 4
      monthly: 3
    repository: <app>-backup-secret
    cacheCapacity: 1Gi
    cacheStorageClassName: ceph-block
    storageClassName: ceph-block
    volumeSnapshotClassName: csi-cephfsplugin-snapclass
```

### 3. Configure Backup Repository

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: <app>-backup-secret
  namespace: <namespace>
type: Opaque
stringData:
  RESTIC_REPOSITORY: "s3:https://s3.example.com/backup-bucket/<namespace>/<app>"
  RESTIC_PASSWORD: "your-secure-password"
  AWS_ACCESS_KEY_ID: "your-access-key"
  AWS_SECRET_ACCESS_KEY: "your-secret-key"
```

## Restore Procedures

### 1. Restore from Snapshot

To restore from a Ceph snapshot:

```bash
# List available snapshots
kubectl get volumesnapshot -n <namespace>

# Create PVC from snapshot
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: <pvc-name>-restored
  namespace: <namespace>
spec:
  storageClassName: ceph-block
  dataSource:
    name: <snapshot-name>
    kind: VolumeSnapshot
    apiGroup: snapshot.storage.k8s.io
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: <original-size>
EOF
```

### 2. Restore from Volsync Backup

```yaml
apiVersion: volsync.backube/v1alpha1
kind: ReplicationDestination
metadata:
  name: <app>-restore
  namespace: <namespace>
spec:
  trigger:
    manual: restore-once
  restic:
    repository: <app>-backup-secret
    destinationPVC: <pvc-name>-restored
    storageClassName: ceph-block
    volumeSnapshotClassName: csi-cephfsplugin-snapclass
    cacheStorageClassName: ceph-block
```

### 3. Application-Specific Restore

After PVC is restored, update the application to use it:

```bash
# Scale down application
kubectl scale deployment <app> -n <namespace> --replicas=0

# Update deployment to use restored PVC
kubectl patch deployment <app> -n <namespace> --type json -p='[
  {"op": "replace", "path": "/spec/template/spec/volumes/0/persistentVolumeClaim/claimName", "value": "<pvc-name>-restored"}
]'

# Scale up application
kubectl scale deployment <app> -n <namespace> --replicas=1
```

## Backup Verification

### Daily Verification Tasks

```bash
# Check ReplicationSource status
kubectl get replicationsource -A

# Verify last backup completion
kubectl describe replicationsource <app>-backup -n <namespace> | grep -A5 "Last Sync"

# Check backup sizes
kubectl get pvc -A | grep cache
```

### Monthly Restore Test

1. Create test namespace:
   ```bash
   kubectl create namespace restore-test
   ```

2. Restore a backup to test namespace
3. Verify data integrity
4. Clean up test namespace

## Disaster Recovery Scenarios

### Scenario 1: Single PVC Corruption

1. Stop affected application
2. Create snapshot of corrupted PVC (for analysis)
3. Delete corrupted PVC
4. Restore from most recent backup
5. Restart application

### Scenario 2: Namespace Deletion

```bash
# Restore all PVCs in namespace
for pvc in $(kubectl get replicationsource -n <namespace> -o name); do
  # Create ReplicationDestination for each
done
```

### Scenario 3: Complete Cluster Loss

1. Rebuild Ceph cluster
2. Restore Volsync deployment
3. Configure backup repository access
4. Restore all workloads from external backups

## Backup Retention Policies

### Default Retention
- Daily: 7 backups
- Weekly: 4 backups  
- Monthly: 3 backups

### Adjusting Retention

Edit ReplicationSource:
```yaml
spec:
  restic:
    retain:
      daily: 14    # Keep 2 weeks
      weekly: 8    # Keep 2 months
      monthly: 12  # Keep 1 year
```

## Monitoring Backups

### Prometheus Alerts

Configure alerts for:
- Backup failure
- Backup age > 25 hours
- Repository storage usage > 80%

### Example Alert
```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: backup-alerts
  namespace: monitoring
spec:
  groups:
  - name: backup.rules
    rules:
    - alert: BackupFailed
      expr: volsync_volume_out_of_sync{} > 0
      for: 1h
      annotations:
        summary: "Backup failed for {{ $labels.obj_name }}"
```

## Best Practices

1. **Test Restores Regularly**: Monthly restore tests to verify backup integrity
2. **Monitor Backup Storage**: Ensure sufficient space for retention policy
3. **Document Critical Data**: Maintain list of critical PVCs requiring backup
4. **Secure Backup Credentials**: Use sealed secrets or external secret operator
5. **Version Application Configs**: Keep application configurations in Git

## Quick Reference

```bash
# List all backups
kubectl get replicationsource -A

# Check backup status
kubectl describe replicationsource <name> -n <namespace>

# Create manual snapshot
kubectl create volumesnapshot <name> --from-pvc=<pvc-name> -n <namespace>

# List snapshots
kubectl get volumesnapshot -n <namespace>

# Restore from snapshot
kubectl apply -f restore-pvc.yaml
```

## Troubleshooting

### Backup Failing

1. Check ReplicationSource events:
   ```bash
   kubectl describe replicationsource <name> -n <namespace>
   ```

2. Check Volsync logs:
   ```bash
   kubectl logs -n storage -l app.kubernetes.io/name=volsync
   ```

3. Verify snapshot class:
   ```bash
   kubectl get volumesnapshotclass
   ```

### Restore Failing

1. Verify backup repository accessible
2. Check credentials in secret
3. Ensure sufficient storage space
4. Review ReplicationDestination events

## External Resources

- Volsync Documentation: https://volsync.readthedocs.io/
- Ceph CSI Snapshots: https://rook.io/docs/rook/latest/Storage-Configuration/Ceph-CSI/ceph-csi-snapshot/