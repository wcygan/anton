# Ceph Storage Migration Plan for Anton Homelab

**Date**: June 2025  
**Status**: Planning Phase  
**Priority**: Low (Non-Production Workloads)

## Executive Summary

Based on analysis of the current cluster configuration, the Anton homelab has minimal storage requirements with primarily test workloads. All identified applications can continue operating on the existing local-path provisioner without impact. This migration plan documents current storage usage and provides a roadmap for future Ceph adoption when production workloads are deployed.

## Current Storage Analysis

### Applications Using Persistent Storage

#### Test Database Workloads (`database` namespace)
```yaml
# CloudNativePG Test Cluster
- name: test-db
  storage: 5Gi
  storageClass: local-path (default)
  priority: Low - test workload only

# DragonflyDB Test Cache  
- name: test-cache
  storage: 1Gi
  storageClass: local-path (explicit)
  priority: Low - cache snapshots for testing
```

#### Development Airflow (`airflow` namespace)
```yaml
# Apache Airflow PostgreSQL
- name: airflow-postgresql
  storage: ~10-20Gi (chart defaults)
  storageClass: local-path (default)
  priority: Low - development/learning environment
```

#### Monitoring Stack (`monitoring` namespace)
```yaml
# Prometheus/Grafana (implicit storage)
- name: prometheus-storage
  storage: Chart defaults (ephemeral)
  storageClass: local-path (default)
  priority: Low - basic cluster monitoring
```

### Total Current Usage
- **Active PVCs**: ~11Gi across all workloads
- **Storage Pattern**: Single-node, non-replicated
- **Workload Type**: Development, testing, and learning

## Migration Priority Assessment

### Low Priority Justification

1. **Non-Production Workloads**
   - All current applications are for testing and development
   - No business-critical data or high-availability requirements
   - Acceptable to lose data during learning/experimentation

2. **Minimal Storage Requirements**
   - Total usage is <1% of available storage capacity
   - Local-path provisioner meets current performance needs
   - No multi-node access patterns required

3. **Cluster Learning Phase**
   - Focus should be on core infrastructure stability
   - Ceph adds operational complexity for limited benefit
   - Current setup is sufficient for skill development

4. **Resource Optimization**
   - Ceph requires 3.5GB RAM per node for minimal deployment
   - Local-path has near-zero overhead
   - Better to preserve resources for application experimentation

## Future Migration Triggers

### When to Revisit Ceph Migration

1. **Production Workloads Deployment**
   - Real applications with high-availability needs
   - Business-critical data requiring replication
   - Multi-tenant or shared storage requirements

2. **Storage Growth**
   - Total usage exceeds 100Gi
   - Need for cross-node data sharing
   - Backup and disaster recovery requirements

3. **Advanced Features Needed**
   - Snapshots for data protection
   - Storage classes with different performance tiers
   - Object storage (S3-compatible) requirements

4. **Operational Maturity**
   - Team comfortable with Kubernetes storage concepts
   - Monitoring and alerting infrastructure mature
   - Disaster recovery procedures established

## Recommended Current State

### Keep Local-Path Provisioner

```yaml
# Continue using for current workloads
storageClass: local-path
benefits:
  - Zero operational overhead
  - Adequate performance for current needs
  - Simple troubleshooting and recovery
  - No additional resource consumption
```

### Storage Strategy for New Applications

1. **Default to local-path** for development workloads
2. **Plan for Ceph** when deploying production services
3. **Monitor usage patterns** to identify migration triggers
4. **Document learnings** from current storage operations

## Migration Readiness Checklist

### Current Status: Not Required ✅

- [ ] ~~Backup current PVCs~~ (test data, acceptable loss)
- [ ] ~~Plan maintenance window~~ (no downtime requirements)
- [ ] ~~Storage device preparation~~ (defer until needed)
- [x] Document current state (this document)
- [x] Identify future triggers (production workloads)

### Future Preparation (When Triggered)

- [ ] Complete Ceph readiness assessment tasks
- [ ] Deploy Ceph cluster alongside local-path
- [ ] Test with non-critical workloads first
- [ ] Migrate production workloads with proper backups
- [ ] Deprecate local-path for new applications

## Architecture Considerations for Future

### Planned Ceph Implementation

When migration becomes necessary:

```yaml
# Block Storage (RBD)
ceph-rbd:
  replicas: 3
  devices: nvme-only
  use-cases: [databases, high-performance apps]

# File Storage (CephFS)  
ceph-fs:
  replicas: 3
  use-cases: [shared data, AI models, logs]

# Object Storage (RGW)
ceph-object:
  replicas: 3
  use-cases: [backups, static assets, S3-compatible apps]
```

### Coexistence Strategy

- **Local-path**: Development and ephemeral workloads
- **Ceph-RBD**: Production databases and high-performance storage
- **Ceph-FS**: Shared filesystem needs
- **Ceph-Object**: Backup and archive storage

## Conclusion

The current Anton homelab storage needs are well-served by the local-path provisioner. Migration to Ceph should be deferred until production workloads are deployed or storage requirements exceed the capabilities of single-node storage. This approach maintains operational simplicity while preserving the option for future storage infrastructure expansion.

### Current Recommendation: **Continue with Local-Path**

**Benefits:**
- Zero additional operational complexity
- Adequate performance for current workloads  
- Resource efficiency for learning environment
- Simple disaster recovery (acceptable data loss)

**Future Path:**
- Monitor for production workload deployment
- Reassess when storage exceeds 100Gi
- Implement Ceph when high-availability is required
- Maintain documentation for smooth future transition

**Next Review Date**: When first production workload is planned for deployment