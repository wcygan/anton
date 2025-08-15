# Backup & Disaster Recovery Golden Rules

## The Golden Rule

**A backup doesn't exist until you've successfully restored from it.** Untested backups are just wasted storage. Test restore procedures regularly.

## Critical Rules

### 1. Never Trust a Single Backup Location

**WRONG:**
```yaml
# Single backup destination
backup:
  destination: s3://backups/cluster
```

**RIGHT:**
```yaml
# Multiple backup destinations
volsync:
  restic:
    repository: backup-s3     # Primary: S3
    copyMethod: Direct
  
  # Secondary backup job
  rclone:
    destination: backup-nfs   # Secondary: NFS
    copyMethod: Snapshot
```

**Why:** Single location = single point of failure. Ransomware can encrypt backups too.

### 2. Always Version Infrastructure Alongside Data

**WRONG:**
```bash
# Backing up only PVCs
velero backup create daily-backup \
  --include-resources=pvc
```

**RIGHT:**
```bash
# Full application backup
velero backup create daily-backup \
  --include-resources=pvc,pv,deployment,service,configmap,secret \
  --include-namespaces=app-namespace \
  --snapshot-volumes=true
```

**Why:** Data without its application configuration is useless.

### 3. Never Perform Restore Without Isolation

**WRONG:**
```bash
# Restoring directly to production
velero restore create --from-backup prod-backup
```

**RIGHT:**
```bash
# Restore to isolated namespace first
velero restore create test-restore \
  --from-backup prod-backup \
  --namespace-mappings "production:restore-test"

# Verify restore worked
kubectl -n restore-test get all

# Then migrate if successful
```

**Why:** Failed restores can corrupt existing data.

### 4. Always Test Restore Time Requirements

**WRONG:**
```yaml
# Setting RPO/RTO without testing
backup:
  schedule: "0 2 * * *"  # Daily at 2am
  # Assuming 1-hour restore time
```

**RIGHT:**
```bash
# Measure actual restore time
time velero restore create test-restore \
  --from-backup prod-backup

# Document in runbook
echo "Restore time: 3.5 hours" >> disaster-recovery-runbook.md

# Adjust backup frequency if needed
```

**Why:** Real restore times are always longer than expected.

### 5. Never Ignore Backup Failures

**WRONG:**
```yaml
# No alerting on backup failures
backup:
  schedule: "0 2 * * *"
  # No failure notifications
```

**RIGHT:**
```yaml
# Alert on backup failures
- alert: BackupFailed
  expr: |
    volsync_replication_last_sync_duration_seconds{result="Failed"} > 0
    OR
    time() - volsync_replication_last_sync_time > 86400
  for: 5m
  annotations:
    summary: "Backup failed for {{ $labels.name }}"
```

**Why:** Silent backup failures mean no protection when you need it.

## Backup Strategy Patterns

### 3-2-1 Rule Implementation

```yaml
# 3 copies of data
# 2 different storage types  
# 1 offsite location

# Copy 1: Live data (Ceph)
storageClassName: ceph-block

# Copy 2: Local NFS backup
volsync-nfs:
  schedule: "0 */6 * * *"  # Every 6 hours
  destination: nfs-backup

# Copy 3: Offsite S3
volsync-s3:
  schedule: "0 2 * * *"    # Daily
  destination: s3-backup
```

### Application-Specific Backup Requirements

**Databases**
```yaml
# Pre-backup hooks for consistency
preBackupHook:
  exec:
    command:
      - /bin/bash
      - -c
      - pg_dump -U postgres mydb > /backup/dump.sql
```

**Stateful Applications**
```yaml
# Quiesce before snapshot
preBackupHook:
  exec:
    command:
      - /app/bin/maintenance-mode
      - enable
```

## Disaster Recovery Procedures

### Full Cluster Recovery

```bash
# 1. Bootstrap new cluster
talosctl apply-config --nodes $NODES --file controlplane.yaml

# 2. Install Flux
flux install --export | kubectl apply -f -

# 3. Restore secrets first
kubectl create secret generic sops-age \
  --from-file=age.key=/backup/age.key \
  -n flux-system

# 4. Restore Git repository
flux create source git flux-system \
  --url=https://github.com/org/fleet \
  --branch=main

# 5. Let Flux restore applications
flux reconcile kustomization flux-system --with-source

# 6. Restore data
velero restore create cluster-restore \
  --from-backup latest-backup
```

### Single Application Recovery

```bash
# 1. Scale down application
kubectl scale deployment app -n production --replicas=0

# 2. Restore PVC
velero restore create app-restore \
  --from-backup daily-backup \
  --include-resources=pvc \
  --selector="app=myapp"

# 3. Verify data
kubectl run -it verify --image=busybox \
  --mount type=pvc,name=app-data,mountPath=/data

# 4. Scale up application
kubectl scale deployment app -n production --replicas=3
```

## Testing Requirements

### Monthly Restore Tests

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: restore-test
spec:
  schedule: "0 3 1 * *"  # First of month
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: test-restore
            image: velero/velero
            command:
            - /bin/bash
            - -c
            - |
              # Create test restore
              velero restore create monthly-test \
                --from-backup latest \
                --namespace-mappings "prod:test"
              
              # Wait for completion
              sleep 300
              
              # Verify restore
              kubectl -n test get all
```

## Backup Monitoring

### Key Metrics to Track

```yaml
# Prometheus rules
- record: backup_size_gb
  expr: volsync_volume_capacity_bytes / 1024 / 1024 / 1024

- record: backup_duration_hours  
  expr: volsync_replication_last_sync_duration_seconds / 3600

- alert: BackupTooSlow
  expr: backup_duration_hours > 4
  for: 5m
```

### Backup Dashboard Essentials

- Last successful backup time per application
- Backup size trends
- Restore test results
- RPO/RTO compliance
- Storage usage by backup destination

## Pre-Operation Checklist

- [ ] Recent backup verified (< 24 hours old)
- [ ] Backup destination accessible
- [ ] Restore procedure documented
- [ ] Restore test performed this month
- [ ] Team notified of maintenance window
- [ ] Rollback plan prepared
- [ ] Monitoring alerts acknowledged

## Incidents

### 2024-08-15: Corrupted Backup Chain
- **What happened:** S3 bucket lifecycle deleted old backups
- **Impact:** Could only restore last 7 days, lost historical data
- **Root cause:** Restic incremental backups need full chain
- **Lesson:** Understand backup tool requirements

### 2024-10-22: Restore Failure During Outage
- **What happened:** Primary storage failed, restore took 8 hours
- **Impact:** Extended outage beyond SLA
- **Root cause:** Never tested full restore time
- **Lesson:** Test and document actual restore times