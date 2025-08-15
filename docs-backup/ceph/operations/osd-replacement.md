# OSD Replacement Procedure

## Overview
This document outlines the procedure for replacing a failed OSD (Object Storage Daemon) disk in the Ceph cluster.

## When to Replace an OSD

Replace an OSD when:
- Disk shows SMART errors or predictive failure
- OSD repeatedly crashes or fails to start
- Disk I/O errors in system logs
- Physical disk failure confirmed

## Pre-Replacement Checklist

- [ ] Cluster health is otherwise OK (no other failing OSDs)
- [ ] Replacement disk is same size or larger (1TB NVMe)
- [ ] Talos node access is available
- [ ] Maintenance window scheduled (if production workloads exist)

## Replacement Procedure

### Step 1: Identify Failed OSD

```bash
# Check OSD tree for down OSDs
kubectl -n storage exec deploy/rook-ceph-tools -- ceph osd tree

# Example output showing osd.2 is down:
# -3         2.00000  host k8s-2
#  2    ssd  1.00000      osd.2    down  1.00000
#  3    ssd  1.00000      osd.3    up    1.00000
```

### Step 2: Verify Disk Failure

```bash
# Check OSD pod logs
kubectl -n storage logs rook-ceph-osd-2-xxxxx --tail=50

# Check node for disk errors (replace with actual node IP)
talosctl -n 192.168.1.99 dmesg | grep -E "(nvme|error|fail)" | tail -20
```

### Step 3: Mark OSD Out

```bash
# Mark the OSD as out to trigger rebalancing
kubectl -n storage exec deploy/rook-ceph-tools -- ceph osd out osd.2

# Monitor rebalancing progress
kubectl -n storage exec deploy/rook-ceph-tools -- ceph status
```

Wait for rebalancing to complete (HEALTH_OK or only the OSD down warning).

### Step 4: Remove Failed OSD

```bash
# Stop the OSD pod
kubectl -n storage scale deployment rook-ceph-osd-2 --replicas=0

# Remove OSD from cluster
kubectl -n storage exec deploy/rook-ceph-tools -- ceph osd purge osd.2 --yes-i-really-mean-it

# Delete the deployment
kubectl -n storage delete deployment rook-ceph-osd-2
```

### Step 5: Physical Disk Replacement

**For k8s-1 (192.168.1.98)**:
- Shutdown node: `talosctl -n 192.168.1.98 shutdown`
- Replace disk in slot 0 or 1 as needed
- Power on node

**For k8s-2 (192.168.1.99)**:
- Shutdown node: `talosctl -n 192.168.1.99 shutdown`
- Replace disk in slot 0 or 1 as needed
- Power on node

**For k8s-3 (192.168.1.100)**:
- Shutdown node: `talosctl -n 192.168.1.100 shutdown`
- Replace disk in slot 0 or 1 as needed
- Power on node

### Step 6: Prepare New Disk

After node is back online:

```bash
# Verify new disk is detected
talosctl -n 192.168.1.XX disks

# The disk should show as available
# Example: /dev/nvme0n1 or /dev/nvme1n1
```

### Step 7: Trigger OSD Creation

The Rook operator should automatically detect and provision the new disk. Monitor the process:

```bash
# Watch Rook operator logs
kubectl -n storage logs -f deployment/rook-ceph-operator | grep -i osd

# Check for new OSD pod
kubectl -n storage get pods | grep osd
```

If OSD is not automatically created after 5 minutes:

```bash
# Restart Rook operator to trigger discovery
kubectl -n storage delete pod -l app=rook-ceph-operator
```

### Step 8: Verify New OSD

```bash
# Check OSD tree - new OSD should be up and in
kubectl -n storage exec deploy/rook-ceph-tools -- ceph osd tree

# Verify cluster health
kubectl -n storage exec deploy/rook-ceph-tools -- ceph status

# Check that new OSD is participating
kubectl -n storage exec deploy/rook-ceph-tools -- ceph osd df
```

### Step 9: Monitor Recovery

```bash
# Watch recovery progress
kubectl -n storage exec deploy/rook-ceph-tools -- watch ceph status

# Check for misplaced objects
kubectl -n storage exec deploy/rook-ceph-tools -- ceph health detail
```

Recovery is complete when:
- Cluster shows HEALTH_OK
- No degraded or misplaced objects
- All PGs are active+clean

## Post-Replacement Verification

1. Run daily health check procedure
2. Verify all PVCs are accessible:
   ```bash
   kubectl get pvc -A | grep -v Bound
   ```
3. Test write to each namespace:
   ```bash
   ./scripts/test-storage-via-pods.ts
   ```

## Troubleshooting

### OSD Not Created Automatically

1. Check Rook operator permissions:
   ```bash
   kubectl -n storage describe deployment rook-ceph-operator
   ```

2. Manually specify the disk in the cluster CR:
   ```yaml
   # Edit the rook-ceph-cluster HelmRelease
   # Add specific device path under nodes section
   ```

### Multiple OSD Failures

**WARNING**: If multiple OSDs fail simultaneously:
- DO NOT proceed with replacement
- Risk of data loss is high
- Consult Ceph documentation for recovery procedures

### Slow Recovery

If recovery is taking too long:
```bash
# Increase recovery priority
kubectl -n storage exec deploy/rook-ceph-tools -- \
  ceph config set osd osd_recovery_priority 63

# After recovery completes, reset to default
kubectl -n storage exec deploy/rook-ceph-tools -- \
  ceph config rm osd osd_recovery_priority
```

## Quick Reference Card

```bash
# Failed OSD: osd.X on node 192.168.1.YY

# 1. Mark out
ceph osd out osd.X

# 2. Wait for rebalance
watch ceph status

# 3. Remove OSD
ceph osd purge osd.X --yes-i-really-mean-it

# 4. Replace physical disk

# 5. Verify new OSD created
ceph osd tree

# 6. Monitor recovery
watch ceph status
```

## Important Notes

- Never replace multiple OSDs simultaneously
- Always wait for recovery between replacements
- Keep the old disk for potential data recovery (if needed)
- Document all actions taken in the migration log