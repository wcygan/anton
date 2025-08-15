# Ceph Storage Emergency Recovery Runbook

**Purpose**: Emergency procedures for recovering from Ceph storage failures in the Anton cluster.

**Last Updated**: June 13, 2025  
**Applies To**: Rook-Ceph v1.17.4, Ceph v19.2.0

## Emergency Indicators

Execute this runbook when encountering:

- **0 OSDs running** - Complete storage system failure
- **All PVCs pending** - No storage provisioning possible
- **FSID mismatch errors** - Old cluster data conflicts
- **Missing OSDs on nodes** - Hardware configuration mismatches

## Prerequisites

- Direct access to Talos nodes via `talosctl`
- Kubernetes cluster admin access
- Git repository access for configuration changes
- Understanding that **this process is destructive** to existing data

## Emergency Recovery Process

### Phase 1: Immediate Assessment

1. **Check cluster state**:
   ```bash
   kubectl get pods -n storage
   kubectl exec -n storage deploy/rook-ceph-tools -- ceph status
   kubectl get pvc -A | grep Pending
   ```

2. **Identify OSDs**:
   ```bash
   kubectl exec -n storage deploy/rook-ceph-tools -- ceph osd tree
   ```

3. **Check for FSID conflicts**:
   ```bash
   # Look for logs mentioning different FSIDs
   kubectl logs -n storage -l app=rook-ceph-osd-prepare --tail=100
   ```

### Phase 2: Emergency Recovery Execution

**⚠️ WARNING**: This process destroys all data on specified disks.

1. **Use the emergency recovery script**:
   ```bash
   cd /Users/wcygan/Development/homelab
   ./scripts/ceph-emergency-recovery.ts --auto-confirm
   ```

2. **Monitor OSD deployment**:
   ```bash
   # Watch OSDs come online
   kubectl get pods -n storage -l app=rook-ceph-osd -w
   
   # Check OSD count progress
   kubectl exec -n storage deploy/rook-ceph-tools -- ceph osd tree
   ```

3. **Verify expected OSD count**:
   - **Expected**: 6 OSDs total (2 per node)
   - **If missing OSDs**: Proceed to Phase 3

### Phase 3: Hardware Configuration Fixes

**Problem**: Missing OSDs due to device naming differences.

1. **Check actual disk layout**:
   ```bash
   # Verify disk layout per node
   talosctl get disks -n 192.168.1.98  # k8s-1
   talosctl get disks -n 192.168.1.99  # k8s-2  
   talosctl get disks -n 192.168.1.100 # k8s-3
   ```

2. **Compare with configuration**:
   ```bash
   # Check current Rook configuration
   kubectl get cephcluster -n storage storage -o yaml | grep -A20 "devices:"
   ```

3. **Update device configuration if needed**:
   - Edit `kubernetes/apps/storage/rook-ceph-cluster/app/cluster.yaml`
   - Edit `kubernetes/apps/storage/rook-ceph-cluster/app/helmrelease.yaml`
   - **Critical**: k8s-3 uses `nvme2n1` for second drive, not `nvme1n1`

4. **Apply configuration changes**:
   ```bash
   git add kubernetes/apps/storage/
   git commit -m "fix(storage): correct device configuration for missing OSDs"
   git push
   
   # Force Flux reconciliation
   flux reconcile source git flux-system
   flux reconcile kustomization cluster-apps
   ```

### Phase 4: Validation

1. **Verify all OSDs running**:
   ```bash
   kubectl exec -n storage deploy/rook-ceph-tools -- ceph osd tree
   # Should show 6 OSDs total, 2 per node
   ```

2. **Check Ceph health**:
   ```bash
   kubectl exec -n storage deploy/rook-ceph-tools -- ceph health detail
   # Target: HEALTH_OK
   ```

3. **Test storage provisioning**:
   ```bash
   # Check PVC status
   kubectl get pvc -A
   
   # All PVCs should be Bound, no Pending
   ```

4. **Verify application recovery**:
   ```bash
   kubectl get pods -A | grep -v Running
   # All pods should be Running
   ```

## Known Hardware Configurations

### Node Disk Layout

- **k8s-1 & k8s-2**: Use `nvme0n1` and `nvme1n1` for Ceph
- **k8s-3**: Uses `nvme0n1` and `nvme2n1` for Ceph ⚠️

### Correct Rook Configuration

```yaml
# cluster.yaml deviceFilter
deviceFilter: "^nvme[012]n1$"

# helmrelease.yaml nodes section
nodes:
  - name: k8s-1
    devices:
      - name: /dev/nvme0n1
      - name: /dev/nvme1n1
  - name: k8s-2  
    devices:
      - name: /dev/nvme0n1
      - name: /dev/nvme1n1
  - name: k8s-3
    devices:
      - name: /dev/nvme0n1
      - name: /dev/nvme2n1  # Different!
```

## Emergency Recovery Script

The `scripts/ceph-emergency-recovery.ts` script handles:

- FSID verification and conflict detection
- Safe disk cleanup across all nodes
- OSD deployment monitoring
- Health validation post-recovery
- Safety checks and confirmations

**Usage**:
```bash
# Interactive mode (recommended)
./scripts/ceph-emergency-recovery.ts

# Auto-confirm mode (for emergencies)
./scripts/ceph-emergency-recovery.ts --auto-confirm
```

## Common Failure Patterns

### FSID Mismatch
- **Cause**: Previous Ceph cluster data on disks
- **Symptom**: OSDs fail to start, different FSID in logs
- **Solution**: Emergency disk cleanup

### Missing 6th OSD
- **Cause**: k8s-3 device naming difference
- **Symptom**: Only 5 OSDs instead of 6
- **Solution**: Update device configuration for k8s-3

### Stuck CephBlockPool Deletion
- **Cause**: Finalizer prevents deletion
- **Solution**: Remove finalizer manually
  ```bash
  kubectl patch cephblockpool replicapool -n storage --type json \
    -p='[{"op": "remove", "path": "/metadata/finalizers"}]'
  ```

### Connection Refused Errors
- **Cause**: Temporary node connectivity issues during recovery
- **Impact**: Usually self-resolving, script continues
- **Action**: Monitor progress, no intervention needed

## Prevention Measures

1. **Regular Health Monitoring**:
   ```bash
   # Daily health check
   ./scripts/storage-health-check.ts --detailed
   ```

2. **Hardware Documentation**:
   - Maintain accurate disk layout documentation
   - Update immediately after hardware changes

3. **Configuration Validation**:
   ```bash
   # Before major changes
   deno task validate
   ./scripts/check-flux-config.ts
   ```

4. **Backup Critical Data**:
   - Use Volsync for automated backups
   - Test restore procedures regularly

## Recovery Time Expectations

- **Emergency Recovery**: 5-10 minutes
- **OSD Deployment**: 2-5 minutes per OSD
- **Health Convergence**: 5-15 minutes
- **Application Recovery**: 1-5 minutes

**Total Recovery Time**: 15-35 minutes typical

## Escalation Criteria

Contact cluster administrator if:
- Recovery script fails repeatedly
- OSDs don't deploy after 15 minutes
- Ceph health doesn't reach HEALTH_OK after 30 minutes
- Applications don't recover after storage is healthy

## References

- [Emergency Recovery Script](/scripts/ceph-emergency-recovery.ts)
- [Node Disk Layout](/docs/talos-linux/disk-layout.md)
- [Ceph Storage Recovery Milestone](/docs/milestones/2025-06-13-ceph-storage-recovery.md)
- [Rook Troubleshooting](https://rook.io/docs/rook/latest-release/Troubleshooting/ceph-common-issues/)