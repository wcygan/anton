# Storage Architecture Decision: Rook + Ceph

**Date**: January 2025  
**Status**: Accepted  
**Decision**: Deploy Rook + Ceph as the unified storage solution for the Anton homelab cluster

## Executive Summary

After evaluating multiple distributed storage solutions for our 3-node Talos Linux Kubernetes cluster, we have decided to implement Rook + Ceph as our primary storage backend. This decision provides a unified solution for block, file, and object storage needs while maximizing the learning value and utilizing our available hardware resources effectively.

## Context and Requirements

### Cluster Specifications
- **Nodes**: 3x MS-01 Mini PCs (k8s-1, k8s-2, k8s-3)
- **CPU**: 20 cores per node (60 total)
- **RAM**: 96GB per node (288GB total)
- **Storage**: 2.5TB per node (7.5TB total)
  - 1x 500GB NVMe (system disk)
  - 2x 1TB NVMe (fast storage)
- **Network**: 10 Gigabit Ethernet interconnect
- **Current Usage**: <2% of available storage capacity

### Storage Requirements
1. **Block Storage**: Database workloads (PostgreSQL, DragonflyDB)
2. **File Storage**: Shared persistent volumes for applications
3. **Object Storage**: S3-compatible storage for backups and media
4. **Durability**: Tolerate single node failure with zero data loss
5. **Performance**: Low latency for database workloads
6. **Growth**: Support future expansion without major rearchitecture

## Decision Rationale

### Why Rook + Ceph

1. **Unified Architecture**
   - Single control plane for all storage types
   - Consistent management and monitoring interface
   - Reduced operational complexity vs. multiple storage systems

2. **Resource Utilization**
   - Our hardware can comfortably support Ceph's requirements
   - ~3.5GB RAM per node overhead leaves 90+ GB for workloads
   - 10GbE network ideal for replication traffic

3. **Feature Completeness**
   - Native support for snapshots and clones
   - Built-in encryption at rest
   - Quota management and QoS controls
   - Multi-tenancy with namespace isolation

4. **Learning Value**
   - Industry-standard storage solution
   - Skills directly transferable to production environments
   - Comprehensive documentation and community support

### Alternatives Considered

| Solution | Pros | Cons | Decision |
|----------|------|------|----------|
| **Longhorn + MinIO** | Lightweight, simple operations | Multiple operators, no native file storage | Rejected |
| **OpenEBS + SeaweedFS** | Modular, low resource usage | Complex multi-system management | Rejected |
| **Local Path Only** | Zero overhead, simple | No replication, single point of failure | Rejected |

## Implementation Plan

### Phase 1: Foundation (Week 1-2)
```yaml
# Deploy Rook operator and basic Ceph cluster
# Start with block storage (RBD) only
# Use 2x1TB NVMe drives per node
# Configure replica-3 for all pools
```

### Phase 2: Expansion (Week 3-4)
```yaml
# Add CephFS for shared file storage
# Enable Ceph dashboard and Prometheus metrics
# Integrate with existing monitoring stack
# Migrate select workloads to Ceph storage
```

### Phase 3: Advanced Features (Month 2)
```yaml
# Deploy RadosGateway (RGW) for S3 API
# Configure Velero backups to RGW
# Implement snapshot policies
# Test disaster recovery procedures
```

## Technical Architecture

### Storage Classes
```yaml
# Fast NVMe pool for databases
ceph-rbd-fast:
  - Pool: nvme-fast (replica-3)
  - Drives: 2x1TB NVMe per node
  - Use case: PostgreSQL, DragonflyDB

# Shared filesystem
ceph-filesystem:
  - Pool: cephfs-data (replica-3)
  - Use case: Shared application data

# Object storage
ceph-object:
  - Pool: rgw-data (EC 4+2 for efficiency)
  - Use case: Backups, media storage
```

### Resource Allocation
- **Per Node Impact**:
  - CPU: ~200-300 mCPU baseline
  - RAM: 3-3.5 GB for Ceph daemons
  - Network: Variable based on workload
- **Remaining Capacity**: >95% resources available for applications

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Operational complexity | High | Start with basic features, expand gradually |
| Learning curve | Medium | Leverage Rook automation, follow phased approach |
| Resource overhead | Low | Monitor usage, adjust OSD memory limits if needed |
| Network saturation | Medium | Implement QoS if needed, monitor bandwidth |

## Success Criteria

1. **Performance**: <5ms average latency for database operations
2. **Reliability**: 99.9% availability over 30 days
3. **Utilization**: Achieve 30-50% storage utilization
4. **Recovery**: RTO <5 minutes for node failure
5. **Learning**: Team proficiency in Ceph operations

## Monitoring and Alerting

- Enable Ceph Prometheus exporter
- Create Grafana dashboards for:
  - Cluster health and capacity
  - IOPS and throughput metrics
  - OSD performance and latency
- Configure alerts for:
  - OSD down/out conditions
  - Capacity thresholds (70%, 85%)
  - Slow operations

## Future Considerations

1. **Expansion Options**
   - Add fourth node for better erasure coding efficiency
   - Implement tiering with additional SATA SSDs
   - Enable multi-site replication for DR

2. **Advanced Features**
   - RBD mirroring for async replication
   - CephFS snapshots for user data protection
   - RGW bucket policies and lifecycle management

## Conclusion

Rook + Ceph represents the optimal storage solution for our homelab cluster, providing a production-grade, unified storage platform that maximizes both our hardware investment and learning opportunities. The implementation will follow a phased approach to manage complexity while delivering immediate value through improved data durability and performance.

## References

- [Rook Documentation](https://rook.io/docs/rook/latest/)
- [Ceph Architecture Guide](https://docs.ceph.com/en/latest/architecture/)
- [Storage Best Practices for Kubernetes](https://kubernetes.io/docs/concepts/storage/storage-classes/)
- [Ceph on All-Flash Clusters](https://ceph.io/en/news/blog/2019/ceph-all-flash-arrays/)