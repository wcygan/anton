# Homelab Backup Strategy

## Overview

This homelab employs a multi-layered backup strategy using two complementary tools:
- **Velero**: Kubernetes resource and metadata backups
- **Volsync**: Persistent volume data replication

## Backup Tools Comparison

| Feature | Velero | Volsync |
|---------|---------|----------|
| **Primary Use** | Cluster resources & metadata | Persistent volume data |
| **Backup Type** | Logical (YAML manifests) | Block/File level |
| **Storage Backend** | S3 (Ceph RGW) | S3/NFS/Restic |
| **Scheduling** | Built-in schedules | CronJob-based |
| **Restore Granularity** | Namespace/Resource level | PVC level |
| **Cross-cluster** | Yes | Yes |
| **Incremental** | No | Yes (Restic) |
| **Best For** | Disaster recovery, migrations | Data protection |

## When to Use Each Tool

### Use Velero When:
- Backing up entire namespaces or clusters
- Migrating applications between clusters
- Protecting Kubernetes resources (ConfigMaps, Secrets, Deployments)
- Needing point-in-time cluster recovery
- Backing up resources without persistent data

### Use Volsync When:
- Protecting persistent volume data
- Needing incremental backups
- Requiring offsite data replication
- Backing up large datasets efficiently
- Implementing 3-2-1 backup strategy for data

## Current Implementation

### Velero Configuration
- **Schedule**: Daily at 2 AM, Weekly on Sundays at 3 AM
- **Retention**: 30 days (daily), 90 days (weekly)
- **Storage**: Ceph S3 bucket `velero`
- **Scope**: All namespaces except system

### Volsync Configuration
- **Schedule**: Configurable per PVC
- **Retention**: 7 daily, 4 weekly, 3 monthly
- **Storage**: External S3 or NFS
- **Scope**: Selected PVCs with ReplicationSource

## Backup Coverage Matrix

| Namespace | Velero | Volsync | Critical Data |
|-----------|---------|----------|---------------|
| airflow | ✅ Daily | ❌ | DAGs, logs |
| monitoring | ✅ Daily | ✅ Prometheus | Metrics, dashboards |
| storage | ✅ Daily | N/A | Ceph config |
| database | ✅ Daily | ✅ All PVCs | PostgreSQL, Dragonfly |
| default | ✅ Daily | Case-by-case | Application data |
| cert-manager | ✅ Daily | ❌ | Certificates |
| external-secrets | ✅ Daily | ❌ | Secret configs |

## Retention Policies

### Velero Retention
```yaml
Daily Backups: 30 days
Weekly Backups: 90 days
Manual Backups: 24 hours (unless specified)
Pre-maintenance: 7 days
```

### Volsync Retention
```yaml
Daily: 7 backups
Weekly: 4 backups  
Monthly: 3 backups
Yearly: 1 backup (critical data only)
```

## Storage Requirements

### Current Usage (Estimated)
- **Velero**: ~100GB (30 daily + 12 weekly backups)
- **Volsync**: ~500GB (depends on PVC sizes)
- **Total**: ~600GB backup storage needed

### Growth Projections
- Monthly growth: ~10%
- Yearly capacity needed: ~1TB

### Storage Locations
- **Primary**: Ceph S3 (local)
- **Secondary**: External NFS/S3 (offsite)

## Recovery Objectives

### Recovery Time Objective (RTO)
- **Critical Services**: < 1 hour
- **Standard Services**: < 4 hours
- **Full Cluster**: < 8 hours

### Recovery Point Objective (RPO)
- **Databases**: < 24 hours
- **Application State**: < 24 hours
- **Logs/Metrics**: < 7 days

## Backup Verification

### Automated Testing
```bash
# Velero integration test (runs weekly)
deno task test:velero:full

# Volsync verification (per PVC)
kubectl get replicationsource -A
```

### Manual Testing Schedule
- **Monthly**: Restore test in isolated namespace
- **Quarterly**: Full application restore drill
- **Annually**: Complete disaster recovery exercise

## Disaster Recovery Scenarios

### Scenario 1: Namespace Corruption
**Tools**: Velero  
**Process**: Restore namespace from latest backup

### Scenario 2: PVC Data Loss
**Tools**: Volsync  
**Process**: Restore PVC from Restic backup

### Scenario 3: Complete Cluster Loss
**Tools**: Velero + Volsync  
**Process**:
1. Rebuild cluster infrastructure
2. Restore cluster resources with Velero
3. Restore persistent data with Volsync

### Scenario 4: Region Migration
**Tools**: Velero  
**Process**: Backup in source, restore in destination

## Best Practices

1. **Follow 3-2-1 Rule**:
   - 3 copies of data
   - 2 different storage types
   - 1 offsite location

2. **Test Regularly**:
   - Monthly restore tests
   - Quarterly DR drills
   - Document results

3. **Monitor Continuously**:
   - Backup completion status
   - Storage usage trends
   - Alert on failures

4. **Document Everything**:
   - Application restore procedures
   - Critical resource lists
   - Contact information

## Implementation Checklist

### For New Applications
- [ ] Add to Velero backup schedule
- [ ] Evaluate PVC backup needs
- [ ] Configure Volsync if needed
- [ ] Document restore procedure
- [ ] Test backup/restore cycle

### For Critical Data
- [ ] Enable Volsync replication
- [ ] Configure offsite backup
- [ ] Set appropriate retention
- [ ] Monitor backup health
- [ ] Schedule restore tests

## Quick Decision Tree

```
Need to backup?
├── Kubernetes Resources (ConfigMaps, Secrets, etc.)
│   └── Use Velero
├── Persistent Volume Data
│   ├── Small dataset (<10GB)
│   │   └── Use Velero with FSB
│   └── Large dataset (>10GB)
│       └── Use Volsync
└── Both Resources and Data
    └── Use both Velero and Volsync
```

## Cost Optimization

1. **Compress Backups**: Enable compression in Volsync
2. **Deduplicate**: Use Restic for incremental backups
3. **Lifecycle Policies**: Auto-delete old backups
4. **Tiered Storage**: Use cheaper storage for old backups

## Compliance and Security

1. **Encryption**: All backups encrypted at rest
2. **Access Control**: RBAC for backup operations
3. **Audit Trail**: Log all backup/restore operations
4. **Retention Compliance**: Meet data retention requirements
5. **Regular Reviews**: Quarterly backup policy reviews

## References

- [Velero Documentation](./velero/README.md)
- [Velero Operations Guide](./velero/operations.md)
- [Volsync Backup Procedures](./ceph/operations/backup-restore.md)
- [Disaster Recovery Plan](./disaster-recovery/README.md)
- [Integration Test Scripts](/scripts/test-velero-backup.ts)