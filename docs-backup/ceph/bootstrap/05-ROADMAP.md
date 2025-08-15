# Initiative: Ceph Distributed Storage Implementation for Anton Homelab

## Overview

Transform the Anton homelab's storage infrastructure from simple local-path provisioning to a production-grade distributed storage system using Rook-Ceph. This initiative will provide unified block, file, and object storage capabilities while maintaining operational simplicity through a phased "Hybrid Progressive" deployment approach.

## Strategic Goals

### Goal 1: Storage Infrastructure Readiness

- **Objective**: Prepare hardware and validate Talos Linux compatibility for Ceph deployment
- **Success Metrics**: 
  - All 6 NVMe drives unmounted and ready for Ceph
  - RBD kernel module verified in Talos
  - GitOps directory structure created and validated
- **Timeline**: 2-3 days when triggered

### Goal 2: Phase 1 - Block Storage Implementation

- **Objective**: Deploy Rook-Ceph operator and cluster with RBD (block storage) only
- **Success Metrics**:
  - Ceph cluster healthy with 3 OSDs per node
  - Block storage class created and tested
  - <5ms latency and >1GB/s throughput achieved
  - Monitoring integrated with Prometheus/Grafana
- **Timeline**: 1 week after Goal 1

### Goal 3: Phase 2 - Filesystem Storage (When Needed)

- **Objective**: Enable CephFS for multi-pod read/write access
- **Success Metrics**:
  - CephFS deployed with MDS pods healthy
  - RWX storage class functional
  - Successful multi-pod write testing
- **Timeline**: On-demand (when RWX required)

### Goal 4: Phase 3 - Object Storage (When Needed)

- **Objective**: Deploy S3-compatible object storage via RGW
- **Success Metrics**:
  - RGW pods healthy and accessible
  - S3 API tested with standard tools
  - Backup integration validated
- **Timeline**: On-demand (when S3 required)

### Goal 5: Production Migration

- **Objective**: Migrate critical workloads to Ceph storage
- **Success Metrics**:
  - All production workloads using Ceph
  - Zero data loss during migration
  - Documented runbooks for operations
- **Timeline**: 2-4 weeks after relevant phases

## Roadmap & Checkpoints

### Phase 0: Pre-Implementation (Trigger-Based)

**Checkpoint 0.1**: Deployment Decision
- [ ] Monitor for trigger conditions:
  - Production workload requirement
  - Storage usage exceeds 100Gi
  - Multi-pod write access needed
  - S3-compatible storage required
- [ ] Document specific use case driving deployment
- **Dependencies**: Current workload analysis
- **Estimated Effort**: Ongoing monitoring

**Checkpoint 0.2**: Full Data Backup
- [ ] Backup all PVCs using local-path
- [ ] Verify backup restoration process
- [ ] Document current storage usage
- **Dependencies**: Trigger activated
- **Estimated Effort**: 2-4 hours

### Phase 1: Infrastructure Preparation (Days 1-3)

**Checkpoint 1.1**: Hardware Validation
- [ ] Verify Talos kernel modules: `talosctl -n <node> read /proc/modules | grep rbd`
- [ ] Check kernel version ≥4.17 for CephFS readiness
- [ ] Validate 10GbE network connectivity between nodes
- **Dependencies**: Talos cluster access
- **Estimated Effort**: 2 hours

**Checkpoint 1.2**: Storage Device Preparation
- [ ] Identify NVMe devices on each node
- [ ] Create Talos machine config patches to unmount devices
- [ ] Apply patches and verify devices are raw/unformatted
- [ ] Document device paths for Ceph configuration
- **Dependencies**: Maintenance window
- **Estimated Effort**: 4 hours

**Checkpoint 1.3**: GitOps Structure Creation
- [ ] Create full directory structure under `kubernetes/apps/storage/`
- [ ] Implement base Kustomizations with `.disabled` suffixes for phases 2-3
- [ ] Configure Flux dependencies and health checks
- [ ] Validate manifests with pre-commit checks
- **Dependencies**: Git repository access
- **Estimated Effort**: 4 hours

### Phase 2: Rook-Ceph Deployment (Week 1)

**Checkpoint 2.1**: Operator Installation
- [ ] Deploy Rook-Ceph operator via HelmRelease
- [ ] Verify operator pods are running
- [ ] Check CRD installation
- [ ] Configure resource limits
- **Dependencies**: Phase 1 complete
- **Estimated Effort**: 2 hours

**Checkpoint 2.2**: Cluster Bootstrap
- [ ] Deploy CephCluster CR with block storage only
- [ ] Monitor OSD creation (6 total, 2 per node)
- [ ] Verify MON quorum establishment
- [ ] Check cluster health: `kubectl -n rook-ceph exec -it deploy/rook-ceph-tools -- ceph status`
- **Dependencies**: Operator healthy
- **Estimated Effort**: 4 hours

**Checkpoint 2.3**: Block Storage Configuration
- [ ] Create RBD storage class with 3-way replication
- [ ] Deploy test PVC and pod
- [ ] Benchmark performance (fio tests)
- [ ] Verify compression is active
- **Dependencies**: Cluster healthy
- **Estimated Effort**: 3 hours

**Checkpoint 2.4**: Monitoring Integration
- [ ] Deploy Ceph Prometheus exporters
- [ ] Import Grafana dashboards
- [ ] Configure health alerts
- [ ] Test alert routing
- **Dependencies**: Monitoring stack operational
- **Estimated Effort**: 3 hours

### Phase 3: Optional Components (On-Demand)

**Checkpoint 3.1**: CephFS Activation
- [ ] Remove `.disabled` suffix from filesystem manifests
- [ ] Deploy MDS pods
- [ ] Create CephFS storage class
- [ ] Test multi-pod write scenarios
- **Dependencies**: RWX requirement identified
- **Estimated Effort**: 4 hours

**Checkpoint 3.2**: Object Storage Activation
- [ ] Remove `.disabled` suffix from objectstore manifests
- [ ] Deploy RGW pods
- [ ] Configure ingress for S3 endpoint
- [ ] Test with S3 CLI tools
- **Dependencies**: S3 requirement identified
- **Estimated Effort**: 4 hours

### Phase 4: Production Migration (Weeks 2-4)

**Checkpoint 4.1**: Migration Planning
- [ ] Inventory all workloads using storage
- [ ] Create migration priority list
- [ ] Design rollback procedures
- [ ] Schedule maintenance windows
- **Dependencies**: Ceph stable for 1 week
- **Estimated Effort**: 4 hours

**Checkpoint 4.2**: Gradual Migration
- [ ] Migrate test workloads first
- [ ] Validate data integrity
- [ ] Migrate production workloads in priority order
- [ ] Update application manifests
- **Dependencies**: Migration plan approved
- **Estimated Effort**: 8-16 hours

**Checkpoint 4.3**: Operational Handoff
- [ ] Create runbooks for common operations
- [ ] Document troubleshooting procedures
- [ ] Establish backup/restore workflows
- [ ] Train on Ceph management
- **Dependencies**: All workloads migrated
- **Estimated Effort**: 8 hours

## Risk Matrix

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| RBD kernel module missing in Talos | High | Medium | Pre-validate before deployment; consider CSI-only approach |
| NVMe device preparation fails | High | Low | Maintain detailed device inventory; test on single node first |
| Performance doesn't meet targets | Medium | Medium | Start with test workloads; tune Ceph settings iteratively |
| OSD creation failures | High | Low | Ensure devices are completely wiped; check Rook logs |
| Network latency impacts replication | Medium | Low | Validate 10GbE connectivity; consider dedicated replication network |
| Operator upgrade breaks cluster | High | Low | Pin versions; test upgrades in phases |
| Storage capacity miscalculation | Medium | Medium | Monitor usage closely; plan for 3x replication overhead |

## Dependencies & Requirements

### Technical Dependencies
- Talos Linux with RBD kernel module support
- Unmounted/raw NVMe devices (currently require machine config changes)
- Functional Prometheus/Grafana stack for monitoring
- GitOps infrastructure (Flux) operational
- 1Password Connect for secret management

### Resource Requirements
- 3.5GB RAM per node for Ceph overhead
- 10GbE network bandwidth for replication
- ~2TB usable capacity with 3-way replication
- Maintenance windows for device preparation

### Knowledge Requirements
- Ceph architecture and concepts
- Rook operator management
- Talos Linux machine configuration
- GitOps/Flux troubleshooting
- Storage performance tuning

## Next Steps

1. **Immediate Actions** (When Triggered):
   - Run hardware validation script: `./scripts/validate-ceph-readiness.ts`
   - Create feature branch: `feat/ceph-storage`
   - Begin Phase 0 checkpoint execution

2. **Stakeholder Involvement**:
   - Review roadmap and approve approach
   - Schedule maintenance window for device preparation
   - Align on production workload migration timing

3. **First Checkpoint Target**:
   - Complete Checkpoint 0.1 (Deployment Decision) when trigger conditions are met
   - Target 1-week completion for Phase 1 after trigger
   - Establish weekly progress reviews during active implementation

## Success Criteria

The initiative will be considered successful when:
- Ceph cluster runs stable for 30 days without intervention
- All production workloads successfully migrated
- Performance targets met (<5ms latency, >1GB/s throughput)
- Operational runbooks proven through actual incidents
- Team confident in managing Ceph operations