# Ceph Storage Migration Plan

## Executive Summary

This document outlines the migration plan for transitioning from local-path provisioner to Ceph distributed storage for the Anton Kubernetes cluster. The migration will be executed in phases to minimize downtime and ensure data integrity.

## Current State

### Storage Overview
- **Total Storage Used**: 116Gi across 5 PVCs
- **Storage Provisioner**: local-path (rancher.io/local-path)
- **Target Storage**: Ceph RBD (ceph-block storage class)
- **Migration Tool**: Volsync with CSI snapshots

### Workload Inventory

| Application | PVC Name | Namespace | Size | Type | Priority | Node |
|------------|----------|-----------|------|------|----------|------|
| Airflow Logs | logs-airflow-triggerer-0 | airflow | 100Gi | Logs | Low | k8s-1 |
| Airflow PostgreSQL | data-airflow-postgresql-0 | airflow | 8Gi | Database | High | k8s-3 |
| PostgreSQL Test | test-postgres-cluster-1 | database | 5Gi | Database | Medium | k8s-2 |
| KubeAI Open WebUI | open-webui | kubeai | 2Gi | Application | Medium | k8s-2 |
| DragonflyDB Test | df-test-cache-0 | database | 1Gi | Cache | Low | k8s-3 |

## Migration Strategy

### Phase 1: Test Workloads (Low Risk)
Start with non-critical test workloads to validate the migration process.

**Workloads:**
1. df-test-cache-0 (1Gi) - Test cache instance
2. test-postgres-cluster-1 (5Gi) - Test database

**Benefits:**
- Validate Volsync backup/restore process
- Test Ceph performance with real workloads
- Establish migration procedures

### Phase 2: Application Storage (Medium Risk)
Migrate application storage that can tolerate brief downtime.

**Workloads:**
1. open-webui (2Gi) - KubeAI interface
2. logs-airflow-triggerer-0 (100Gi) - Airflow logs (can be recreated if needed)

**Considerations:**
- Open WebUI downtime affects AI model access
- Airflow logs are non-critical but large

### Phase 3: Production Databases (High Risk)
Migrate critical database workloads with minimal downtime.

**Workloads:**
1. data-airflow-postgresql-0 (8Gi) - Production Airflow metadata

**Requirements:**
- Zero data loss
- Minimal downtime (<5 minutes)
- Immediate rollback capability

## Migration Procedures

### Standard Migration Process

1. **Pre-Migration Backup**
   ```bash
   # Create Volsync ReplicationSource for backup
   kubectl apply -f - <<EOF
   apiVersion: volsync.backube/v1alpha1
   kind: ReplicationSource
   metadata:
     name: backup-<pvc-name>
     namespace: <namespace>
   spec:
     sourcePVC: <pvc-name>
     trigger:
       manual: backup-before-migration
     restic:
       repository: <backup-location>
       copyMethod: Snapshot
       volumeSnapshotClassName: csi-ceph-blockpool
   EOF
   ```

2. **Scale Down Application**
   ```bash
   kubectl scale deployment/statefulset <app-name> -n <namespace> --replicas=0
   ```

3. **Create New PVC on Ceph**
   ```bash
   kubectl apply -f - <<EOF
   apiVersion: v1
   kind: PersistentVolumeClaim
   metadata:
     name: <pvc-name>-ceph
     namespace: <namespace>
   spec:
     accessModes:
       - ReadWriteOnce
     storageClassName: ceph-block
     resources:
       requests:
         storage: <size>
   EOF
   ```

4. **Restore Data to New PVC**
   ```bash
   kubectl apply -f - <<EOF
   apiVersion: volsync.backube/v1alpha1
   kind: ReplicationDestination
   metadata:
     name: restore-<pvc-name>
     namespace: <namespace>
   spec:
     trigger:
       manual: restore-to-ceph
     restic:
       repository: <backup-location>
       destinationPVC: <pvc-name>-ceph
       copyMethod: Direct
   EOF
   ```

5. **Update Application Configuration**
   - Edit deployment/statefulset to use new PVC name
   - Apply changes

6. **Scale Up Application**
   ```bash
   kubectl scale deployment/statefulset <app-name> -n <namespace> --replicas=<original-count>
   ```

7. **Verify Application Health**
   - Check pod status
   - Validate data integrity
   - Monitor application logs

8. **Cleanup Old PVC** (after validation period)
   ```bash
   kubectl delete pvc <old-pvc-name> -n <namespace>
   ```

## Rollback Procedures

### Immediate Rollback (Within Migration Window)

1. **Stop Application**
   ```bash
   kubectl scale deployment/statefulset <app-name> -n <namespace> --replicas=0
   ```

2. **Revert Configuration**
   - Edit deployment/statefulset to use original PVC name
   - Apply changes

3. **Start Application**
   ```bash
   kubectl scale deployment/statefulset <app-name> -n <namespace> --replicas=<original-count>
   ```

### Post-Migration Rollback (Using Volsync)

1. **Create Snapshot of Current State**
   ```bash
   # Snapshot current Ceph PVC for safety
   kubectl apply -f - <<EOF
   apiVersion: snapshot.storage.k8s.io/v1
   kind: VolumeSnapshot
   metadata:
     name: pre-rollback-<pvc-name>
     namespace: <namespace>
   spec:
     volumeSnapshotClassName: csi-ceph-blockpool
     source:
       persistentVolumeClaimName: <pvc-name>-ceph
   EOF
   ```

2. **Restore from Original Backup**
   - Use Volsync ReplicationDestination to restore from pre-migration backup
   - Target a new local-path PVC

3. **Switch Application to Restored PVC**
   - Update deployment/statefulset
   - Restart application

## Maintenance Windows

### Proposed Schedule

| Date | Time (UTC) | Workload | Expected Duration | Rollback Time |
|------|------------|----------|-------------------|---------------|
| TBD | 02:00-03:00 | df-test-cache-0 | 15 minutes | 15 minutes |
| TBD | 02:00-03:00 | test-postgres-cluster-1 | 30 minutes | 30 minutes |
| TBD+1 | 02:00-04:00 | open-webui | 30 minutes | 30 minutes |
| TBD+1 | 02:00-04:00 | logs-airflow-triggerer-0 | 60 minutes | 30 minutes |
| TBD+7 | 02:00-03:00 | data-airflow-postgresql-0 | 30 minutes | 30 minutes |

**Notes:**
- All times are UTC
- Test workloads migrated first
- One week validation period before production database
- Extended window for large log volume

## Success Criteria

### Per-Workload Validation
- [ ] Application starts successfully on Ceph storage
- [ ] Data integrity verified (checksums match)
- [ ] Performance metrics acceptable
- [ ] No errors in application logs
- [ ] Monitoring/alerting functioning

### Overall Migration Success
- [ ] All PVCs migrated to Ceph storage
- [ ] No data loss incidents
- [ ] Downtime within maintenance windows
- [ ] Rollback procedures tested
- [ ] Documentation updated

## Risk Mitigation

### Identified Risks

1. **Data Corruption During Migration**
   - Mitigation: Volsync snapshots before migration
   - Verification: Checksum validation

2. **Extended Downtime**
   - Mitigation: Test migrations first
   - Fallback: Immediate rollback procedure

3. **Performance Degradation**
   - Mitigation: Benchmark before production
   - Monitoring: Grafana dashboards

4. **Node Failure During Migration**
   - Mitigation: Ceph 3-way replication
   - Recovery: Volsync backups

## Post-Migration Tasks

1. **Monitoring Setup**
   - Configure alerts for Ceph storage usage
   - Set up performance baselines
   - Enable capacity planning metrics

2. **Documentation Updates**
   - Update application READMEs
   - Create runbooks for common tasks
   - Document lessons learned

3. **Cleanup**
   - Remove old local-path PVCs (after 30 days)
   - Archive migration logs
   - Update infrastructure diagrams

## Appendix

### Volsync Configuration Templates

See `/kubernetes/components/volsync/` for reusable templates.

### Ceph Performance Benchmarks

To be completed during test workload migration.

### Communication Template

```
Subject: Scheduled Maintenance - Storage Migration

Dear Team,

We will be migrating [application] to our new distributed storage system during the following maintenance window:

Date: [date]
Time: [time] UTC
Expected Duration: [duration]
Impact: [application] will be unavailable during migration

Rollback procedures are in place. Updates will be provided via [channel].

Thank you for your patience.
```