# Velero Operations Guide

## Daily Operations Checklist

### Morning Health Check (5 minutes)

```bash
# 1. Check backup completion from overnight
kubectl get backup.velero.io -n storage | grep $(date +%Y-%m-%d)

# 2. Verify backup storage location is available
kubectl get backupstoragelocation -n storage

# 3. Check for any failed backups
kubectl get backup.velero.io -n storage | grep -E "Failed|PartiallyFailed"

# 4. Review Velero pod health
kubectl get pods -n storage -l app.kubernetes.io/name=velero
```

### Weekly Tasks

1. **Review Backup Storage Usage**
   ```bash
   # Check S3 bucket size
   kubectl exec -n storage deployment/rook-ceph-tools -- \
     s3cmd du s3://velero/ --no-ssl --host=rook-ceph-rgw-storage.storage:80
   ```

2. **Verify Weekly Backup**
   ```bash
   # Check Sunday's weekly backup
   kubectl get backup.velero.io -n storage | grep weekly
   ```

3. **Run Integration Test**
   ```bash
   deno task test:velero --skip-restore
   ```

### Monthly Tasks

1. **Perform Restore Test**
   ```bash
   # Create test namespace
   kubectl create namespace restore-test
   
   # Create test resources
   kubectl apply -n restore-test -f - <<EOF
   apiVersion: v1
   kind: ConfigMap
   metadata:
     name: test-data
   data:
     date: "$(date)"
     test: "monthly-restore-test"
   EOF
   
   # Create backup
   cat <<EOF | kubectl apply -f -
   apiVersion: velero.io/v1
   kind: Backup
   metadata:
     name: restore-test-$(date +%Y%m)
     namespace: storage
   spec:
     includedNamespaces:
       - restore-test
     ttl: 24h0m0s
   EOF
   
   # Wait for completion
   sleep 30
   
   # Delete namespace
   kubectl delete namespace restore-test
   
   # Restore
   cat <<EOF | kubectl apply -f -
   apiVersion: velero.io/v1
   kind: Restore
   metadata:
     name: restore-test-$(date +%Y%m)
     namespace: storage
   spec:
     backupName: restore-test-$(date +%Y%m)
   EOF
   
   # Verify
   kubectl get configmap -n restore-test test-data
   
   # Cleanup
   kubectl delete namespace restore-test
   ```

2. **Review Metrics and Trends**
   - Check Grafana dashboards for backup success rates
   - Review storage growth trends
   - Analyze backup duration patterns

## Common Operational Scenarios

### Scenario 1: Urgent Backup Before Maintenance

```bash
# Create immediate backup with short retention
cat <<EOF | kubectl apply -f -
apiVersion: velero.io/v1
kind: Backup
metadata:
  name: pre-maintenance-$(date +%Y%m%d-%H%M%S)
  namespace: storage
spec:
  includeClusterResources: true
  ttl: 168h0m0s  # 7 days
  storageLocation: default
EOF

# Monitor progress
kubectl describe backup.velero.io pre-maintenance-* -n storage
```

### Scenario 2: Namespace Migration

```bash
# Backup source namespace
cat <<EOF | kubectl apply -f -
apiVersion: velero.io/v1
kind: Backup
metadata:
  name: migrate-${SOURCE_NS}
  namespace: storage
spec:
  includedNamespaces:
    - ${SOURCE_NS}
  ttl: 24h0m0s
EOF

# Wait for completion
kubectl wait --for=jsonpath='{.status.phase}'=Completed \
  backup.velero.io/migrate-${SOURCE_NS} -n storage --timeout=300s

# Restore to new namespace
cat <<EOF | kubectl apply -f -
apiVersion: velero.io/v1
kind: Restore
metadata:
  name: migrate-${SOURCE_NS}-to-${DEST_NS}
  namespace: storage
spec:
  backupName: migrate-${SOURCE_NS}
  namespaceMappings:
    ${SOURCE_NS}: ${DEST_NS}
EOF
```

### Scenario 3: Disaster Recovery Drill

```bash
# 1. Document current state
kubectl get namespaces | grep -v kube- | grep -v velero > /tmp/namespaces-before.txt
kubectl get pv > /tmp/pv-before.txt

# 2. Simulate disaster (in test environment only!)
# kubectl delete namespace <test-namespace>

# 3. List available backups
kubectl get backup.velero.io -n storage

# 4. Perform restore
cat <<EOF | kubectl apply -f -
apiVersion: velero.io/v1
kind: Restore
metadata:
  name: dr-drill-$(date +%Y%m%d)
  namespace: storage
spec:
  backupName: <most-recent-backup>
  includedNamespaces:
    - <test-namespace>
EOF

# 5. Verify restoration
kubectl get all -n <test-namespace>
```

## Troubleshooting Guide

### Issue: Backup Stuck in "InProgress"

1. **Check Velero logs**:
   ```bash
   kubectl logs -n storage deployment/velero --tail=100
   ```

2. **Look for node agent issues**:
   ```bash
   kubectl get pods -n storage -l name=node-agent -o wide
   kubectl logs -n storage -l name=node-agent --tail=50
   ```

3. **Force retry**:
   ```bash
   # Delete stuck backup
   kubectl delete backup.velero.io <backup-name> -n storage
   
   # Recreate
   kubectl apply -f <backup-spec>
   ```

### Issue: Restore Missing Resources

1. **Check backup contents**:
   ```bash
   # Download backup tarball
   kubectl exec -n storage deployment/rook-ceph-tools -- \
     s3cmd get s3://velero/backups/<backup-name>/velero-backup.json - \
     --no-ssl --host=rook-ceph-rgw-storage.storage:80 | jq '.items[].kind' | sort | uniq -c
   ```

2. **Verify included resources**:
   ```bash
   kubectl describe backup.velero.io <backup-name> -n storage | grep -A20 "Spec:"
   ```

### Issue: S3 Connection Errors

1. **Test S3 connectivity**:
   ```bash
   # From Velero pod
   kubectl exec -n storage deployment/velero -- \
     aws s3 ls s3://velero/ \
     --endpoint-url http://rook-ceph-rgw-storage.storage:80
   ```

2. **Verify credentials**:
   ```bash
   kubectl get secret velero-credentials -n storage -o yaml
   ```

3. **Check Ceph RGW status**:
   ```bash
   kubectl get pods -n storage -l app=rook-ceph-rgw
   kubectl logs -n storage -l app=rook-ceph-rgw --tail=50
   ```

## Performance Tuning

### Optimize Backup Performance

1. **Increase parallelism**:
   ```yaml
   # Edit HelmRelease
   kubectl edit helmrelease velero -n storage
   
   # Add under spec.values.configuration:
   defaultParallelism: 4
   ```

2. **Adjust resource limits**:
   ```yaml
   resources:
     requests:
       cpu: 500m
       memory: 512Mi
     limits:
       cpu: 2000m
       memory: 2Gi
   ```

### Optimize Restore Performance

1. **Use resource filtering**:
   ```bash
   # Restore only essential resources first
   cat <<EOF | kubectl apply -f -
   apiVersion: velero.io/v1
   kind: Restore
   metadata:
     name: fast-restore
     namespace: storage
   spec:
     backupName: <backup-name>
     includeClusterResources: false
     excludedResources:
       - events
       - events.events.k8s.io
       - pods
       - replicasets.apps
   EOF
   ```

## Monitoring and Alerting

### Key Metrics to Monitor

1. **Backup Success Rate**:
   ```promql
   rate(velero_backup_success_total[24h]) / rate(velero_backup_total[24h])
   ```

2. **Backup Duration**:
   ```promql
   velero_backup_duration_seconds{schedule="daily-backup"}
   ```

3. **Storage Usage Growth**:
   ```promql
   rate(velero_backup_items_total[7d])
   ```

### Recommended Alerts

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: velero-alerts
  namespace: monitoring
spec:
  groups:
  - name: velero
    rules:
    - alert: VeleroBackupFailed
      expr: increase(velero_backup_failure_total[1h]) > 0
      for: 10m
      annotations:
        summary: "Velero backup failed"
        
    - alert: VeleroBackupMissing
      expr: time() - velero_backup_last_successful_timestamp > 86400
      for: 1h
      annotations:
        summary: "No successful backup in 24 hours"
        
    - alert: VeleroStorageLocationUnavailable
      expr: velero_backup_storage_location_available == 0
      for: 15m
      annotations:
        summary: "Backup storage location unavailable"
```

## Integration Test Usage

### Running Tests

```bash
# Quick health check
deno task test:velero --skip-restore

# Full backup/restore test
deno task test:velero:full --verbose

# Generate JSON report for automation
./scripts/test-velero-backup.ts --json > /tmp/velero-test-$(date +%Y%m%d).json

# Manual verification mode
./scripts/test-velero-backup.ts --manual
```

### Interpreting Test Results

- **Exit Code 0**: All systems healthy
- **Exit Code 1**: Warnings present (e.g., no recent backups)
- **Exit Code 2**: Critical issues (e.g., Velero not running)

## Best Practices

1. **Label Critical Resources**:
   ```bash
   kubectl label namespace production backup=critical
   kubectl label pvc important-data backup=critical
   ```

2. **Use Backup Hooks** for databases:
   ```yaml
   spec:
     hooks:
       resources:
       - name: database-backup
         includedNamespaces:
         - database
         labelSelector:
           matchLabels:
             app: postgresql
         pre:
         - exec:
             container: postgres
             command: ["/bin/bash", "-c", "pg_dump -U postgres mydb > /backup/dump.sql"]
   ```

3. **Document Restore Procedures** for each application
4. **Practice Restores** quarterly
5. **Monitor S3 Bucket Growth** and adjust retention as needed

## Quick Reference Commands

```bash
# List backups by date
kubectl get backup.velero.io -n storage --sort-by=.metadata.creationTimestamp

# Get backup summary
kubectl get backup.velero.io -n storage -o custom-columns=NAME:.metadata.name,STATUS:.status.phase,CREATED:.metadata.creationTimestamp,EXPIRES:.status.expiration

# Delete old backups
kubectl delete backup.velero.io -n storage -l velero.io/schedule-name=daily-backup --field-selector metadata.creationTimestamp<2024-01-01

# Check node agent logs on specific node
kubectl logs -n storage $(kubectl get pods -n storage -l name=node-agent -o name | grep k8s-1)

# Force backup deletion from S3
kubectl exec -n storage deployment/rook-ceph-tools -- \
  s3cmd rm -r s3://velero/backups/<backup-name>/ \
  --no-ssl --host=rook-ceph-rgw-storage.storage:80
```