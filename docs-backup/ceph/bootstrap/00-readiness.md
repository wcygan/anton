# Rook Ceph Readiness Assessment for Anton Homelab

**Date**: June 2025  
**Status**: Ready with Prerequisites  
**Assessment**: The cluster meets all hardware requirements but needs preparation steps

## Executive Summary

The Anton homelab cluster is well-positioned for Rook Ceph deployment with excellent hardware specifications and recent NVMe additions. Our goal is to leverage the **full Ceph stack** - block storage (RBD), file storage (CephFS), and object storage (RGW) - to create a unified storage platform that eliminates the need for multiple storage solutions. The cluster requires some preparation work, primarily around storage device management and kernel module verification, before proceeding with Rook Ceph installation.

## Hardware Readiness ✅

### Compute Resources
- **CPU**: 60 cores total (20 per node) - **Exceeds requirements**
- **RAM**: 288GB total (96GB per node) - **Exceeds requirements**
- **Expected Ceph overhead**: ~3.5GB RAM per node, leaving 90+ GB for workloads

### Storage Resources
- **Total raw capacity**: 7.5TB across cluster
- **Per node**: 2x 1TB WD_BLACK SN7100 NVMe drives
- **Current usage**: <2% - **Excellent headroom**
- **Storage type**: High-performance NVMe ideal for Ceph

### Network Infrastructure
- **Speed**: 10 Gigabit Ethernet interconnect
- **Topology**: Full mesh between all nodes
- **Assessment**: **Optimal for Ceph replication traffic**

## Software Prerequisites

### ✅ Met Requirements

1. **Kubernetes Version**
   - Current: v1.33.1
   - Required: v1.16+ (v1.28-v1.33 supported)
   - **Status**: Compatible

2. **Operating System**
   - Current: Talos Linux
   - **Status**: Officially supported with documentation

3. **Node Count**
   - Current: 3 control plane nodes
   - Required: 3+ for production
   - **Status**: Meets minimum requirements

4. **Helm**
   - Available via Flux HelmController
   - **Status**: Ready for Rook Helm charts

### ⚠️ Requires Verification

1. **RBD Kernel Module**
   ```bash
   # Verify on all nodes
   for node in 192.168.1.98 192.168.1.99 192.168.1.100; do
     echo "Checking $node..."
     talosctl -n $node read /proc/modules | grep rbd
   done
   ```
   - **Required for**: Ceph block storage (RBD)
   - **Action**: Must verify presence before deployment

2. **Kernel Version**
   ```bash
   # Check kernel version
   kubectl get nodes -o wide
   ```
   - **Recommended**: 4.17+ for CephFS RWX volumes (critical for our full stack approach)
   - **Action**: Verify current kernel version
   - **Note**: CephFS is essential for our unified storage strategy

### ❌ Requires Action

1. **Storage Device Preparation**
   - **Current state**: NVMe drives mounted with XFS at `/var/mnt/fast1` and `/var/mnt/fast2`
   - **Required state**: Raw, unformatted devices
   - **Action**: Unmount and wipe devices before Ceph can use them

2. **LVM2 Package** (if using encryption)
   - **Status**: Verify if available in Talos
   - **Action**: Only needed if encryption is planned

## Storage Device Inventory

| Node | Device | Serial | Current Mount | Size | Action Required |
|------|--------|--------|---------------|------|----------------|
| k8s-1 | nvme0n1 | 251021802190 | /var/mnt/fast1 | 1TB | Unmount & wipe |
| k8s-1 | nvme2n1 | 251021802186 | /var/mnt/fast2 | 1TB | Unmount & wipe |
| k8s-2 | nvme0n1 | 251021802221 | /var/mnt/fast1 | 1TB | Unmount & wipe |
| k8s-2 | nvme1n1 | 251021801877 | /var/mnt/fast2 | 1TB | Unmount & wipe |
| k8s-3 | nvme0n1 | 251021801882 | /var/mnt/fast2 | 1TB | Unmount & wipe |
| k8s-3 | nvme2n1 | 251021800405 | /var/mnt/fast1 | 1TB | Unmount & wipe |

## Workload Migration Requirements

### Current Storage Usage
- **PostgreSQL databases**: Using local-path provisioner
- **DragonflyDB cache**: 1Gi PVC
- **Airflow**: 108Gi total (logs + PostgreSQL)
- **Open WebUI**: 2Gi PVC
- **Total PVCs**: ~120Gi across all workloads

### Migration Strategy for Full Stack Implementation
1. Backup all persistent data
2. Deploy Rook Ceph with all three storage types enabled
3. Migrate workloads by storage type:
   - **Block**: Database workloads to RBD
   - **File**: Shared data to CephFS
   - **Object**: Backups and archives to RGW
4. Decommission local-path volumes
5. Validate all three storage interfaces are operational

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Data loss during migration | Medium | High | Full backup before starting |
| RBD module missing | Low | High | Verify before deployment |
| Performance degradation | Low | Medium | Start with resource limits |
| Operational complexity | High | Medium | Phased deployment approach |

## Readiness Checklist

### Pre-Deployment Tasks
- [ ] Verify RBD kernel module on all nodes
- [ ] Check kernel version (4.17+ recommended)
- [ ] Create full backup of all PVCs
- [ ] Document current storage configuration
- [ ] Plan maintenance window for device preparation

### Deployment Prerequisites
- [ ] Remove NVMe mounts from Talos configuration
- [ ] Wipe target storage devices
- [ ] Create `rook-ceph` namespace
- [ ] Configure Flux HelmRepository for Rook

### Post-Deployment Validation
- [ ] Verify Ceph cluster health
- [ ] Test CSI driver functionality
- [ ] Create test PVC with each storage class
- [ ] Validate performance metrics

## Recommended Deployment Approach

### Phase 1: Preparation (Week 1)
1. Kernel module verification
2. Backup all data
3. Test deployment in isolated namespace
4. Create migration runbook

### Phase 2: Initial Deployment (Week 2)
1. Deploy Rook operator
2. Start with single OSD per node
3. Create basic storage pools
4. Test with non-critical workloads

### Phase 3: Production Migration (Week 3)
1. Add remaining storage devices
2. Migrate critical workloads
3. Configure monitoring and alerts
4. Performance tuning

### Phase 4: Full Stack Implementation (Week 4)
1. **CephFS Deployment** - Shared filesystem for multi-pod access
2. **RadosGateway (RGW)** - S3-compatible object storage
3. **Advanced Features** - Compression, snapshots, lifecycle policies
4. **Integration** - Connect all three storage types to applications

## Architecture Recommendations

### Full Stack Storage Design

Our architecture will implement all three Ceph storage types to maximize flexibility:

#### 1. Block Storage (RBD)
```yaml
# Fast NVMe pool for databases
ceph-block-nvme:
  replicas: 3
  compression: aggressive
  devices: nvme only
  use-cases:
    - PostgreSQL databases
    - DragonflyDB cache
    - High-performance workloads
```

#### 2. File Storage (CephFS)
```yaml
# Shared filesystem for multi-pod access
ceph-filesystem:
  metadata-replicas: 3
  data-replicas: 3
  compression: passive
  use-cases:
    - Shared application data
    - Media files
    - Log aggregation
    - AI model storage
```

#### 3. Object Storage (RGW)
```yaml
# S3-compatible object store
ceph-objectstore:
  metadata-replicas: 3
  data-replicas: 3
  erasure-coding: optional (4+2)
  use-cases:
    - Backup storage (Velero)
    - Static assets
    - Archive data
    - S3-compatible applications
```

### Network Configuration
- Use host networking for Ceph daemons
- No dedicated Ceph network needed with 10GbE
- Monitor bandwidth usage during rebalancing

### Resource Allocation
```yaml
# Conservative starting limits
mon:
  cpu: 1
  memory: 2Gi
osd:
  cpu: 2
  memory: 4Gi
mgr:
  cpu: 1
  memory: 1Gi
```

## Success Criteria

1. **Functional Requirements**
   - All nodes contributing storage
   - Three-way replication active
   - **Block Storage**: RBD CSI driver operational
   - **File Storage**: CephFS CSI driver operational
   - **Object Storage**: RGW S3 API accessible
   - PVCs provisioning successfully for all storage types

2. **Performance Targets**
   - <5ms latency for database operations
   - >1GB/s sequential throughput
   - <30s PVC provisioning time

3. **Operational Goals**
   - Automated monitoring via Prometheus
   - Clear alerting for failures
   - Documented runbooks
   - Successful disaster recovery test

## Next Steps

1. **Immediate Actions**
   - Run kernel module verification script
   - Review Talos Ceph documentation
   - Create backup of current state

2. **Planning Tasks**
   - Schedule maintenance window
   - Draft migration runbook
   - Identify test workloads

3. **Preparation Work**
   - Setup monitoring dashboards
   - Configure alerting rules
   - Document rollback procedures

## Conclusion

The Anton homelab cluster has excellent hardware specifications for deploying the **full Rook Ceph stack**. By implementing block storage (RBD), file storage (CephFS), and object storage (RGW), we will create a unified storage platform that eliminates the need for separate solutions like MinIO, SeaweedFS, or NFS. The primary work involves preparing the storage devices and verifying kernel compatibility. With careful planning and a phased approach, the cluster can successfully run a production-grade Ceph storage system that serves all storage needs through a single, integrated solution.

### Readiness Score: 8/10

**Strengths:**
- Excellent hardware specifications
- Optimal network infrastructure  
- Kubernetes version compatibility
- Clear architectural patterns from examples

**Areas Requiring Attention:**
- Storage device preparation
- Kernel module verification
- Workload migration planning
- Operational knowledge building