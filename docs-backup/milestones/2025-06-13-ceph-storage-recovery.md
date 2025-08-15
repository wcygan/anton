# Milestone: Ceph Storage Recovery and 6th OSD Addition

**Date**: June 13, 2025
**Type**: Emergency Recovery & Enhancement
**Components**: Rook-Ceph, Storage, Kubernetes

## Overview

Successfully recovered from complete Ceph storage failure where all OSDs were missing due to FSID mismatch, and added the missing 6th OSD that was being skipped due to device naming differences.

## Initial Problem

1. **Critical Storage Failure**:
   - 0 OSDs running, entire storage system down
   - All PVCs pending, no provisioning possible
   - Root cause: Old cluster FSID (58ae2262-9536-478a-aa14-fa34b8d7ff07) on disks conflicted with current cluster (d30ef4d2-60b2-4daf-9b3a-71bfd8ecb182)

2. **Missing 6th OSD**:
   - Only 5 OSDs instead of expected 6
   - k8s-3 only had 1 OSD instead of 2

## Root Causes Discovered

1. **FSID Mismatch**: Previous Ceph cluster data on disks prevented new OSDs from being created
2. **Device Naming Difference**: k8s-3 has different NVMe device layout:
   - k8s-1 & k8s-2: nvme0n1 and nvme1n1 are WD_BLACK drives
   - k8s-3: nvme0n1 and nvme2n1 are WD_BLACK drives (nvme1n1 is system disk)
3. **Configuration Mismatch**: Rook was configured to use nvme1n1 for all nodes

## Recovery Process

### Phase 1: Emergency Recovery Script
Created `scripts/ceph-emergency-recovery.ts` that:
- Verifies cluster state and disk FSIDs
- Cleans all Ceph data from specified disks
- Monitors OSD deployment
- Includes safety checks and user confirmation

### Phase 2: Disk Cleanup
- Ran emergency recovery script with auto-confirmation
- Successfully cleaned disks on all nodes
- Rook operator created 5 OSDs automatically

### Phase 3: 6th OSD Investigation
- Discovered k8s-3 uses nvme2n1 instead of nvme1n1
- Updated configurations:
  - `kubernetes/apps/storage/rook-ceph-cluster/app/cluster.yaml`
  - `kubernetes/apps/storage/rook-ceph-cluster/app/helmrelease.yaml`
- Changed device filter to include nvme2n1: `^nvme[012]n1$`

### Phase 4: Cleanup
- Removed empty Talos storage patches
- Updated talconfig.yaml
- Created comprehensive disk layout documentation

## Implementation Details

### Files Modified
- `kubernetes/apps/storage/rook-ceph-cluster/app/cluster.yaml` - Updated k8s-3 devices
- `kubernetes/apps/storage/rook-ceph-cluster/app/helmrelease.yaml` - Updated k8s-3 devices
- `talos/talconfig.yaml` - Removed empty patch references

### Files Created
- `scripts/ceph-emergency-recovery.ts` - Emergency recovery tool
- `docs/talos-linux/disk-layout.md` - Node disk layout documentation

### Files Removed
- `talos/patches/k8s-1/storage.yaml` - Empty patch file
- `talos/patches/k8s-2/storage.yaml` - Empty patch file
- `talos/patches/k8s-3/storage.yaml` - Empty patch file

## Challenges & Resolutions

1. **Connection Errors During Recovery**:
   - Some nodes showed connection refused errors
   - Script continued and eventually succeeded

2. **Stuck CephBlockPool Deletion**:
   - Removed finalizer to force deletion
   - Resolved after OSDs came online

3. **Configuration Not Updating**:
   - Initial fix only updated cluster.yaml
   - Had to also update HelmRelease values
   - Required Git push before Flux could sync

## Validation

- All 6 OSDs now running (2 per node)
- Ceph health: HEALTH_OK
- All PVCs bound and pods running
- Storage provisioning functional

## Lessons Learned

1. **Always Verify Physical Layout**: Don't assume all nodes have identical device naming
2. **Check Multiple Config Locations**: Both CephCluster CR and HelmRelease may need updates
3. **Git Push Required**: Flux only deploys committed and pushed changes
4. **Document Hardware Differences**: Created disk layout documentation for future reference
5. **Emergency Tools Valuable**: Recovery script will help in future disasters

## Future Recommendations

1. Monitor disk health proactively
2. Keep emergency recovery script updated
3. Consider automated disk discovery instead of explicit device lists
4. Regular Ceph health checks in monitoring
5. Document any hardware changes immediately

## Commands for Verification

```bash
# Check OSD tree
kubectl exec -n storage deploy/rook-ceph-tools -- ceph osd tree

# Verify disk layout on nodes
talosctl get disks -n <node-ip>

# Check Ceph health
kubectl exec -n storage deploy/rook-ceph-tools -- ceph health detail

# Monitor PVC provisioning
kubectl get pvc -A -w
```

## References

- [Ceph Emergency Recovery Script](/scripts/ceph-emergency-recovery.ts)
- [Node Disk Layout Documentation](/docs/talos-linux/disk-layout.md)
- [Rook Storage Selection](https://rook.io/docs/rook/latest-release/CRDs/Cluster/ceph-cluster-crd/#storage-selection-settings)