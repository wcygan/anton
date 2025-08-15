# Velero Backup and Restore

## Overview

Velero is an open-source tool that provides backup and restore capabilities for Kubernetes cluster resources and persistent volumes. In this homelab, Velero is configured to use Ceph S3-compatible object storage as the backup destination.

## Architecture

- **Namespace**: `storage`
- **Backup Storage**: Ceph RGW (S3-compatible) at `http://rook-ceph-rgw-storage.storage.svc.cluster.local:80`
- **Backup Bucket**: `velero`
- **Version**: Velero v1.16.0 (Helm chart 9.2.0)

## Components

1. **Velero Server**: Main controller managing backup/restore operations
2. **Node Agents**: DaemonSet pods for file system backups
3. **Backup Schedules**: Automated daily and weekly backups
4. **Storage Location**: S3-compatible backend configuration

## Backup Schedules

### Daily Backup
- **Schedule**: 2:00 AM UTC daily
- **Retention**: 30 days
- **Scope**: All namespaces except system
- **Excludes**: `velero`, `kube-system` namespaces and event resources

### Weekly Backup
- **Schedule**: 3:00 AM UTC on Sundays
- **Retention**: 90 days
- **Scope**: Full cluster including file system backups
- **Excludes**: `velero`, `kube-system` namespaces and event resources

## Manual Backup Procedures

### Create a Namespace Backup

```bash
cat <<EOF | kubectl apply -f -
apiVersion: velero.io/v1
kind: Backup
metadata:
  name: manual-backup-$(date +%Y%m%d-%H%M%S)
  namespace: storage
spec:
  includedNamespaces:
    - default
    - monitoring
  ttl: 24h0m0s
  storageLocation: default
EOF
```

### Create a Full Cluster Backup

```bash
cat <<EOF | kubectl apply -f -
apiVersion: velero.io/v1
kind: Backup
metadata:
  name: cluster-backup-$(date +%Y%m%d-%H%M%S)
  namespace: storage
spec:
  includeClusterResources: true
  storageLocation: default
  ttl: 720h0m0s  # 30 days
EOF
```

### Check Backup Status

```bash
# List all backups
kubectl get backup.velero.io -n storage

# Describe specific backup
kubectl describe backup.velero.io <backup-name> -n storage

# Check logs
kubectl logs -n storage deployment/velero | grep <backup-name>
```

## Restore Procedures

### Restore from Backup

```bash
cat <<EOF | kubectl apply -f -
apiVersion: velero.io/v1
kind: Restore
metadata:
  name: restore-$(date +%Y%m%d-%H%M%S)
  namespace: storage
spec:
  backupName: <backup-name>
  includedNamespaces:  # Optional: limit scope
    - default
EOF
```

### Monitor Restore Progress

```bash
# Check restore status
kubectl get restore.velero.io -n storage

# Describe restore
kubectl describe restore.velero.io <restore-name> -n storage
```

## Testing and Verification

### Run Integration Test

```bash
# Quick test (backup only)
deno task test:velero --skip-restore

# Full test (backup and restore)
deno task test:velero:full

# Manual verification steps
deno task test:velero --manual
```

### Verify Backup Contents

```bash
# List objects in S3 bucket
kubectl exec -n storage deployment/rook-ceph-tools -- \
  s3cmd ls s3://velero/ --no-ssl --host=rook-ceph-rgw-storage.storage:80

# Check backup metadata
kubectl get backup.velero.io <backup-name> -n storage -o yaml
```

## Monitoring

### Prometheus Metrics

Velero exposes metrics on port 8085:
- `velero_backup_total`: Total number of backups
- `velero_backup_success_total`: Successful backups
- `velero_backup_failure_total`: Failed backups
- `velero_restore_total`: Total number of restores

### Check Component Health

```bash
# Velero deployment status
kubectl get deployment velero -n storage

# Node agent status
kubectl get pods -n storage -l name=node-agent

# Backup storage location status
kubectl get backupstoragelocation -n storage
```

## Troubleshooting

### Common Issues

1. **Backup Storage Location Unavailable**
   - Check S3 credentials: `kubectl get secret velero-credentials -n storage`
   - Verify Ceph RGW is accessible
   - Check bucket exists: `kubectl exec -n storage deployment/velero -- ls /var/velero-backups`

2. **Backup Failing**
   - Check Velero logs: `kubectl logs -n storage deployment/velero`
   - Verify namespace exists and has resources
   - Check for resource quota issues

3. **Restore Not Working**
   - Ensure backup completed successfully
   - Check for namespace conflicts
   - Verify storage class exists

### Debug Commands

```bash
# Get detailed Velero logs
kubectl logs -n storage deployment/velero -f

# Check node agent logs
kubectl logs -n storage -l name=node-agent

# Verify S3 connectivity
kubectl exec -n storage deployment/velero -- \
  aws s3 ls s3://velero/ --endpoint-url http://rook-ceph-rgw-storage.storage:80
```

## Best Practices

1. **Test Restores Regularly**: Run monthly restore tests in a test namespace
2. **Monitor Backup Age**: Set alerts for backups older than expected
3. **Document Critical Resources**: Maintain a list of critical namespaces/resources
4. **Secure Credentials**: Use External Secrets Operator for S3 credentials
5. **Plan Capacity**: Monitor S3 bucket growth and plan for retention

## Integration with GitOps

Velero backups complement GitOps by:
- Backing up runtime state not in Git (secrets, PVCs, etc.)
- Providing point-in-time recovery
- Enabling migration between clusters
- Protecting against accidental deletions

## Limitations

- Does not backup etcd directly (cluster state)
- Requires CSI driver support for volume snapshots
- S3 bucket must be accessible from all nodes
- Large file system backups can be slow

## References

- [Velero Documentation](https://velero.io/docs/)
- [Backup Integration Test Script](/scripts/test-velero-backup.ts)
- [Helm Chart Values](/kubernetes/apps/storage/velero/app/helmrelease.yaml)
- [Ceph S3 Configuration](/docs/ceph/operations/backup-restore.md)