# Ceph Bootstrap Plan for Anton Homelab

**Date**: January 2025  
**Status**: Planning Phase  
**Target Implementation**: When production workloads require distributed storage

## Executive Summary

This plan outlines the strategic approach for introducing Rook Ceph to the Anton homelab cluster. Based on comprehensive analysis of the current infrastructure, example implementations, and official documentation, we recommend a **Hybrid Progressive strategy** that combines onedr0p's simplicity with joryirving's enterprise structure.

**Key Decision**: Continue with local-path provisioner until production workloads require distributed storage. When triggered, implement the Hybrid Progressive approach: start with block storage only while maintaining a structure that supports future expansion to full Ceph capabilities.

## Current State Assessment

### Infrastructure Overview
- **Cluster**: 3x MS-01 mini PCs running Talos Linux
- **Storage**: 6x 1TB NVMe drives (2 per node)
- **Network**: 10 Gigabit Ethernet
- **Current Usage**: ~11Gi test workloads on local-path provisioner

### Readiness Score: 8/10
- ✅ Hardware exceeds requirements
- ✅ Network infrastructure optimal
- ✅ Kubernetes version compatible (v1.33.1)
- ⚠️ Storage devices need preparation
- ⚠️ Kernel modules require verification

## Implementation Strategy: Hybrid Progressive

### Current State (Pre-Trigger)
**Timeline**: Ongoing  
**Actions**: Continue with local-path provisioner

Continue using local-path provisioner while:
- Learning Ceph concepts through documentation
- Monitoring for migration triggers
- Building operational expertise with current stack

### Phase 1: Foundation - Block Storage Only (Week 1)
**Timeline**: 7 days when triggered  
**Approach**: onedr0p pattern for simplicity

#### Day 1-2: Prerequisites & Planning
- [ ] Verify RBD kernel module in Talos
- [ ] Document NVMe device paths/serials
- [ ] Create full backup of existing data
- [ ] Set up test namespace for validation

#### Day 3-4: GitOps Structure
- [ ] Create full directory structure (supports future phases)
- [ ] Configure Helm repository
- [ ] Set up Flux Kustomizations
- [ ] Implement secret management

#### Day 5-6: Core Deployment
```yaml
# Deploy only these components
storage-types:
  block: enabled        # Phase 1
  filesystem: disabled  # Phase 2 (future)
  object: disabled      # Phase 3 (future)

configuration:
  replicas: 3
  failure-domain: host
  compression: zstd
  network: host-networking
```

#### Day 7: Validation
- [ ] Test PVC provisioning
- [ ] Verify backup integration
- [ ] Run performance benchmarks
- [ ] Document operational procedures

### Phase 2: Filesystem Addition (When Needed)
**Timeline**: 1 week after Phase 1 stability proven  
**Trigger**: First application requiring shared storage (RWX)

#### Implementation
- [ ] Deploy MDS pods (2 instances)
- [ ] Create CephFilesystem CR
- [ ] Configure filesystem StorageClass
- [ ] Test multi-pod access patterns

```yaml
# Add to existing cluster
ceph-filesystem:
  metadata:
    activeStandby: true
    replicas: 3
  data:
    replicas: 3
  storageClass: ceph-filesystem
```

### Phase 3: Object Store Addition (When Needed)
**Timeline**: 1 week after Phase 2 stability proven  
**Trigger**: S3-compatible storage requirement

#### Implementation
- [ ] Deploy RGW instances (2 pods)
- [ ] Create CephObjectStore CR
- [ ] Configure bucket StorageClass
- [ ] Set up S3 access credentials

```yaml
# Add to existing cluster
ceph-objectstore:
  gateway:
    instances: 2
  storageClass: ceph-bucket
  preservePoolsOnDelete: true
```

### Key Differentiator: Structure Ready from Day 1

```
# Full structure created in Phase 1, partially populated
kubernetes/apps/storage/
├── rook-ceph-operator/     # ✓ Phase 1: Deployed
├── rook-ceph-cluster/      # ✓ Phase 1: Deployed (block only)
├── rook-ceph-filesystem/   # ⧖ Phase 2: Empty, structure ready
└── rook-ceph-objectstore/  # ⧖ Phase 3: Empty, structure ready
```

## Technical Requirements

### Kernel Module Verification Script
```bash
#!/bin/bash
# Check RBD module on all nodes
for node in 192.168.1.98 192.168.1.99 192.168.1.100; do
  echo "Checking $node..."
  talosctl -n $node read /proc/modules | grep rbd
  talosctl -n $node version --kernel
done
```

### Storage Device Preparation
```bash
# Wipe devices before Ceph usage
for device in /dev/nvme0n1 /dev/nvme2n1; do
  dd if=/dev/zero bs=1M count=100 oflag=direct of=$device
done
```

### GitOps Structure
```
kubernetes/
├── apps/
│   └── storage/
│       └── rook-ceph/
│           ├── operator/
│           │   ├── ks.yaml
│           │   └── app/
│           │       ├── helmrelease.yaml
│           │       └── kustomization.yaml
│           └── cluster/
│               ├── ks.yaml
│               └── app/
│                   ├── helmrelease.yaml
│                   ├── cluster.yaml
│                   └── kustomization.yaml
└── flux/
    └── meta/
        └── repos/
            └── rook-release.yaml
```

## Migration Decision Framework

### Deploy Ceph When:
- [ ] Production workload requires high availability
- [ ] Storage needs exceed 100Gi
- [ ] Multi-pod write access needed (RWX)
- [ ] S3-compatible object storage required
- [ ] Advanced features needed (snapshots, clones)

### Continue Local-Path When:
- [x] All workloads are test/development
- [x] Single-node access sufficient
- [x] Operational simplicity is priority
- [x] Learning Kubernetes fundamentals

## Risk Mitigation

### Technical Risks
| Risk | Mitigation |
|------|------------|
| Data loss during migration | Full backup before deployment |
| Kernel module missing | Verify prerequisites checklist |
| Performance impact | Start with resource limits |
| Complexity overhead | Phased deployment approach |

### Operational Safeguards
- Never test on production hardware
- Maintain rollback procedures
- Document all customizations
- Monitor resource consumption

## Key Learnings from Examples

### From joryirving-home-ops:
- Dual HelmRelease pattern for lifecycle management
- Extended timeouts (15m) for cluster operations
- Comprehensive monitoring integration
- Advanced features (compression, autoscaling)

### From onedr0p-home-ops:
- Start with block storage only
- Bootstrap automation scripts
- Simplified resource management
- Volsync backup integration

### From Official Documentation:
- Always use `rook-ceph` namespace
- Upgrade operator before cluster
- Enable privileged pods in namespace
- Check cluster health during maintenance

## Success Metrics

### Phase 2 (Test Deployment)
- [ ] Ceph cluster reaches HEALTH_OK
- [ ] Test PVC provisions successfully
- [ ] Monitoring dashboards operational
- [ ] Resource usage within limits

### Phase 3 (Production)
- [ ] All storage types operational
- [ ] <5ms latency for block storage
- [ ] >1GB/s throughput achieved
- [ ] Zero data loss during migration

### Phase 4 (Optimization)
- [ ] Automated backups running
- [ ] Compression reducing storage 30%+
- [ ] Self-healing from node failures
- [ ] Documented runbooks complete

## Next Steps

1. **Immediate** (When triggered):
   - Run kernel module verification
   - Review latest Rook release notes
   - Create test VM environment

2. **Pre-Deployment**:
   - Design backup strategy
   - Plan maintenance windows
   - Create monitoring dashboards

3. **Documentation**:
   - Migration runbook
   - Operational procedures
   - Troubleshooting guide

## Hybrid Progressive Strategy Summary

The Hybrid Progressive approach uniquely combines the best of both worlds:

1. **Start Simple** (onedr0p pattern)
   - Deploy only block storage initially
   - Minimal operational complexity
   - Proven stability pattern

2. **Structure for Growth** (joryirving pattern)
   - Full directory structure from day one
   - No future refactoring needed
   - Clear expansion path

3. **Progressive Enhancement**
   - Phase 1: Block storage only
   - Phase 2: Add filesystem when needed
   - Phase 3: Add object storage when needed

This strategy allows you to gain operational experience with Ceph's simplest form while maintaining the flexibility to expand to full enterprise capabilities without restructuring your GitOps repository.

## Conclusion

The Anton homelab is well-positioned for Ceph deployment when production requirements emerge. The Hybrid Progressive strategy provides an optimal path that balances immediate simplicity with future flexibility. By creating the full structure upfront but deploying features progressively, we minimize both initial complexity and future refactoring effort.

**Review Schedule**: Quarterly or when production workload deployment is planned  
**Next Document**: See `04-gitops.md` for detailed implementation structure