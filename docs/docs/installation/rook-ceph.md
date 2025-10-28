---
sidebar_position: 5
---

# Rook Ceph Installation Guide

Complete guide for installing Rook Ceph distributed storage on Talos Kubernetes using Flux GitOps.

## Overview

Rook automates Ceph storage deployment in Kubernetes, providing self-managing, self-scaling, and self-healing distributed storage with native Kubernetes integration.

**Key Components:**
- **Rook Operator**: Manages Ceph lifecycle via Custom Resource Definitions
- **Ceph MON**: 3 monitor daemons maintain cluster consensus
- **Ceph MGR**: 2 manager daemons provide dashboard and metrics
- **Ceph OSD**: Object Storage Daemons (1 per physical disk)
- **CSI Drivers**: Enable dynamic RBD block and CephFS filesystem provisioning

**Benefits:**
- Dynamic PersistentVolumeClaim provisioning
- High availability with 3x data replication
- S3-compatible object storage
- Automated failover and self-healing
- NVMe performance optimization

## Prerequisites

### Cluster Requirements

| Requirement | Value |
|------------|-------|
| Kubernetes | v1.29+ (Talos Linux) |
| Nodes | 3+ control plane nodes |
| CPU (per OSD) | 500m request |
| Memory (per OSD) | 2Gi request, 4Gi limit |
| Network | Host networking (Talos default) |

### This Cluster's Hardware Configuration

| Node | System Disk | Ceph Disks | Usable |
|------|------------|------------|--------|
| k8s-1 (192.168.1.98) | nvme2n1 (500GB) | nvme0n1 + nvme1n1 (2TB) | 667GB |
| k8s-2 (192.168.1.99) | nvme0n1 (500GB) | nvme1n1 + nvme2n1 (2TB) | 667GB |
| k8s-3 (192.168.1.100) | nvme1n1 (500GB) | nvme0n1 + nvme2n1 (2TB) | 667GB |
| **Total** | | **6TB raw** | **2TB** (3x replication) |

**Key Points:**
- All Ceph disks are 1TB WD_BLACK SN7100 NVMe drives
- System disks are 500GB Crucial CT500P3SSD8
- 3x replication provides fault tolerance for 1 node failure
- Disks must be raw block devices (no partitions or filesystems)

### Software Requirements

- Flux CD installed and syncing from Git
- SOPS configured for secret encryption
- Talos Linux cluster fully operational

---

## Pre-Installation: Cleaning Disks from Previous Rook Installation

**CRITICAL**: If disks previously had Rook Ceph, you **MUST** clean them. Rook will fail to initialize OSDs if existing Ceph metadata is detected.

### Check for Existing Ceph Data

```bash
# Check for Rook metadata directories on each node
talosctl --nodes 192.168.1.98 ls /var/lib/rook 2>&1
talosctl --nodes 192.168.1.99 ls /var/lib/rook 2>&1
talosctl --nodes 192.168.1.100 ls /var/lib/rook 2>&1

# If directories exist with content, disk cleaning is required
```

### Disk Cleaning Methods

**Target Disks** (must be wiped):
- **k8s-1**: nvme0n1, nvme1n1
- **k8s-2**: nvme1n1, nvme2n1
- **k8s-3**: nvme0n1, nvme2n1

#### Method 1: Rook Cleanup Policy (Recommended)

If the old Rook cluster is still accessible, use automated cleanup:

```bash
# Enable cleanup before deletion
kubectl -n storage patch cephcluster rook-ceph --type merge \
  -p '{"spec":{"cleanupPolicy":{"confirmation":"yes-really-destroy-data"}}}'

# Delete cluster (triggers cleanup jobs)
kubectl -n storage delete cephcluster rook-ceph

# Monitor cleanup progress
kubectl get jobs -n storage -w

# Wait for all jobs to complete
```

**What happens**:
- Cleanup jobs run on each node
- Removes `/var/lib/rook` directories
- Wipes partition tables from configured disks
- Zeroes first 100MB of each disk
- Most reliable method for complete Rook removal

#### Method 2: Manual Wiping via Talos Shell

If Rook cleanup isn't available, manually wipe using Talos:

```bash
# k8s-1 (192.168.1.98) - wipe nvme0n1 and nvme1n1
talosctl --nodes 192.168.1.98 shell -- bash -c '
  for disk in nvme0n1 nvme1n1; do
    echo "Wiping /dev/$disk..."
    dd if=/dev/zero of=/dev/$disk bs=1M count=100 conv=fsync
    sgdisk --zap-all /dev/$disk
    partprobe /dev/$disk
  done
'

# k8s-2 (192.168.1.99) - wipe nvme1n1 and nvme2n1
talosctl --nodes 192.168.1.99 shell -- bash -c '
  for disk in nvme1n1 nvme2n1; do
    echo "Wiping /dev/$disk..."
    dd if=/dev/zero of=/dev/$disk bs=1M count=100 conv=fsync
    sgdisk --zap-all /dev/$disk
    partprobe /dev/$disk
  done
'

# k8s-3 (192.168.1.100) - wipe nvme0n1 and nvme2n1
talosctl --nodes 192.168.1.100 shell -- bash -c '
  for disk in nvme0n1 nvme2n1; do
    echo "Wiping /dev/$disk..."
    dd if=/dev/zero of=/dev/$disk bs=1M count=100 conv=fsync
    sgdisk --zap-all /dev/$disk
    partprobe /dev/$disk
  done
'
```

**What this does**:
- `dd`: Zeroes first 100MB (destroys partition tables and filesystem signatures)
- `sgdisk --zap-all`: Removes GPT partition table and backup
- `partprobe`: Refreshes kernel partition table cache

**Why not `talosctl wipe disk`?**
Talos's `wipe disk` command only works on Talos-managed partitions (e.g., `nvme0n1p2`) configured via machine config, not raw disks used directly by Rook.

#### Method 3: Full Node Reset (Last Resort)

**WARNING**: Resets entire node including Talos OS state. Only use if other methods fail.

```bash
# Reset one node at a time (never all at once!)
talosctl --nodes 192.168.1.98 reset \
  --graceful=false \
  --system-labels-to-wipe STATE \
  --system-labels-to-wipe EPHEMERAL

# Wait for node reboot, then reapply configuration
task talos:apply-node IP=192.168.1.98 MODE=auto

# Verify node rejoins cluster
kubectl get nodes

# Repeat for remaining nodes one at a time
```

**When to use**:
- Disk wiping via shell fails with "device busy"
- Corrupted Talos state preventing disk access
- Complete cluster rebuild required

### Verify Disks Are Clean

After cleaning, confirm disks have no partitions:

```bash
# Check all disks
talosctl --nodes 192.168.1.98,192.168.1.99,192.168.1.100 get disks

# Verify no Rook metadata
for node in 192.168.1.98 192.168.1.99 192.168.1.100; do
  echo "Node $node:"
  talosctl --nodes $node ls /var/lib/rook 2>&1 || echo "  ✓ Clean"
done

# Expected: Disks show SIZE but no partitions
```

### Skip Cleaning If

- Fresh Talos installation with factory-clean disks
- Nodes fully reset via `talosctl reset`
- New hardware never used for storage

**Best Practice**: Clean proactively to avoid OSD initialization failures.

---

## Installation Steps

### Step 1: Verify Disk Configuration

Confirm disk layout matches expected configuration:

```bash
# Check all nodes
talosctl --nodes 192.168.1.98 get disks
talosctl --nodes 192.168.1.99 get disks
talosctl --nodes 192.168.1.100 get disks

# Expected: 1TB WD_BLACK drives on correct nvme devices per node
```

Configuration is pre-set in:
`kubernetes/apps/storage/rook-ceph-cluster/app/helmrelease.yaml`

### Step 2: Deploy Rook via Flux

**Validate configuration**:
```bash
task configure
```

**Commit and push**:
```bash
git add kubernetes/apps/storage/
git commit -m "feat: add rook-ceph with 6x1TB OSDs"
git push
```

**Monitor deployment**:
```bash
# Watch Flux reconciliation
watch flux get ks -A

# Monitor Rook pods
watch kubectl get pods -n storage

# Expected timeline:
# - rook-ceph-operator: 2-3 minutes
# - rook-ceph-cluster: 5-10 minutes
# - Total: ~15 minutes for full deployment
```

**Expected pods**:
- `rook-ceph-operator-*` (1 replica)
- `rook-ceph-mon-a/b/c` (3 monitors)
- `rook-ceph-mgr-a/b` (2 managers)
- `rook-ceph-osd-0/1/2/3/4/5` (6 OSDs: 2 per node)
- `rook-ceph-tools-*` (1 toolbox)

### Step 3: Verify Cluster Health

Once all pods are `Running`, check Ceph status:

```bash
# Access toolbox
kubectl -n storage exec -it deploy/rook-ceph-tools -- bash

# Check cluster health
ceph status

# Expected output:
#   cluster:
#     health: HEALTH_OK
#   services:
#     mon: 3 daemons, quorum a,b,c
#     mgr: a(active, since Xs), standby: b
#     osd: 6 osds: 6 up, 6 in
#   data:
#     pools:   1 pools, 128 pgs
#     objects: 0 objects, 0 B
#     usage:   6 GiB used, 5.9 TiB / 6 TiB avail
#     pgs:     128 active+clean
```

**Verify OSD topology**:
```bash
ceph osd tree

# Should show 6 OSDs distributed across 3 hosts (k8s-1, k8s-2, k8s-3)
```

**Health checklist**:
- ✓ `health: HEALTH_OK`
- ✓ `mon: 3 daemons` with quorum
- ✓ `mgr: <active>, standby: <standby>`
- ✓ `osd: 6 osds: 6 up, 6 in`
- ✓ `pgs: X active+clean`
- ✓ `usage: ~6 TiB available`

### Step 4: Test Storage Provisioning

Verify the default storage class:

```bash
kubectl get storageclass

# Expected:
# NAME                   PROVISIONER                    RECLAIMPOLICY   VOLUMEBINDINGMODE
# ceph-block (default)   rook-ceph.rbd.csi.ceph.com    Delete          Immediate
```

**Test PVC creation**:
```bash
# Create test PVC
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: test-rbd-pvc
  namespace: default
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 1Gi
  storageClassName: ceph-block
EOF

# Verify binding
kubectl get pvc -n default test-rbd-pvc

# Expected: STATUS = Bound

# Cleanup
kubectl delete pvc -n default test-rbd-pvc
```

---

## Configuration Reference

### Storage Layout

**File**: `kubernetes/apps/storage/rook-ceph-cluster/app/helmrelease.yaml`

```yaml
storage:
  nodes:
    - name: k8s-1
      devices:
        - name: /dev/nvme0n1  # 1TB WD_BLACK
        - name: /dev/nvme1n1  # 1TB WD_BLACK
    - name: k8s-2
      devices:
        - name: /dev/nvme1n1  # 1TB WD_BLACK
        - name: /dev/nvme2n1  # 1TB WD_BLACK
    - name: k8s-3
      devices:
        - name: /dev/nvme0n1  # 1TB WD_BLACK
        - name: /dev/nvme2n1  # 1TB WD_BLACK
```

### Block Pool Configuration

```yaml
cephBlockPools:
  - name: ceph-blockpool
    spec:
      failureDomain: host        # Replicas on different nodes
      replicated:
        size: 3                  # 3x replication
        requireSafeReplicaSize: true
      parameters:
        compression_mode: aggressive
        compression_algorithm: zstd  # Fast compression
```

**Capacity math**:
```
Raw:    6 disks × 1TB = 6TB
Factor: 3x replication
Usable: 6TB ÷ 3 = 2TB
```

### Dashboard Access

Get dashboard credentials:
```bash
kubectl -n storage get secret rook-ceph-dashboard-password \
  -o jsonpath="{['data']['password']}" | base64 --decode && echo
```

Port forward:
```bash
kubectl -n storage port-forward svc/rook-ceph-mgr-dashboard 7000:7000
```

Access at http://localhost:7000
- Username: `admin`
- Password: (from command above)

---

## Operations

### Monitor Cluster Health

```bash
# Overall status
kubectl -n storage exec deploy/rook-ceph-tools -- ceph status

# OSD topology
kubectl -n storage exec deploy/rook-ceph-tools -- ceph osd tree

# Pool usage
kubectl -n storage exec deploy/rook-ceph-tools -- ceph df

# Placement group status
kubectl -n storage exec deploy/rook-ceph-tools -- ceph pg stat
```

### Expand Storage

Current configuration uses all 1TB drives. To expand:
1. Install additional physical disks
2. Update `helmrelease.yaml` storage.nodes configuration
3. Commit and push
4. Verify new OSDs appear in `ceph osd tree`

### Upgrade Ceph

```bash
# Update version in helmrelease.yaml
cephVersion:
  image: 'quay.io/ceph/ceph:v19.2.4'

# Commit and push
git add kubernetes/apps/storage/rook-ceph-cluster/app/helmrelease.yaml
git commit -m "chore: upgrade ceph to v19.2.4"
git push

# Monitor upgrade
kubectl -n storage get cephcluster -w
```

Rook upgrades Ceph components safely with rolling updates.

---

## Troubleshooting

### OSD Pod Not Starting

**Symptoms**: `CrashLoopBackOff` or `Init:Error`

**Diagnosis**:
```bash
kubectl -n storage logs -l app=rook-ceph-osd --tail=100
kubectl -n storage logs -l app=rook-ceph-operator --tail=100
```

**Common causes**:
- Disk has old Ceph data → Clean disks (see Pre-Installation)
- Wrong disk path in config → Verify with `talosctl get disks`
- Insufficient space (need 10GB+ per disk)

**Fix**: Clean disks and redeploy

### PVC Stuck in Pending

**Diagnosis**:
```bash
kubectl describe pvc <pvc-name>
kubectl -n storage exec deploy/rook-ceph-tools -- ceph status
kubectl get pods -n storage -l app=csi-rbdplugin
```

**Common causes**:
- Cluster not healthy (`ceph status` != HEALTH_OK)
- CSI driver pods not running
- Insufficient capacity

**Fix**:
```bash
# Restart CSI provisioner
kubectl rollout restart -n storage deployment/csi-rbdplugin-provisioner
```

### Health Warnings

```bash
kubectl -n storage exec deploy/rook-ceph-tools -- ceph health detail
```

| Warning | Cause | Fix |
|---------|-------|-----|
| `mon is allowing insecure global_id reclaim` | Initial setup | Resolves automatically |
| `clock skew detected` | NTP drift | Check node NTP config |
| `N OSD(s) down` | OSD pod failed | Check OSD logs |
| `pgs not deep-scrubbed` | Scrub delayed | Wait or increase resources |

---

## Uninstalling

**WARNING**: Destructive operation. All data will be lost.

```bash
# 1. Delete all PVCs
kubectl get pvc -A -o wide | grep ceph-block

# 2. Enable cleanup
kubectl -n storage patch cephcluster rook-ceph --type merge \
  -p '{"spec":{"cleanupPolicy":{"confirmation":"yes-really-destroy-data"}}}'

# 3. Remove cluster
git rm -r kubernetes/apps/storage/rook-ceph-cluster/
git commit -m "chore: remove rook-ceph-cluster"
git push && task reconcile

# 4. Remove operator
git rm -r kubernetes/apps/storage/rook-ceph-operator/
git commit -m "chore: remove rook-ceph-operator"
git push && task reconcile

# 5. Clean disks (see Pre-Installation section)
```

---

## Best Practices

### Capacity Management

- Monitor at 60% utilization, alert at 70%
- Current capacity: 2TB usable
- Plan expansion before reaching 70%
- Use `ceph df` for capacity monitoring

### High Availability

- Rook distributes OSDs across nodes automatically
- MONs use anti-affinity for HA
- `failureDomain: host` ensures replica separation
- Cluster survives single node failure

### Backup Strategy

- Deploy Velero with CSI snapshot support
- Critical metadata in `/var/lib/rook`
- Test restore procedures regularly
- Document recovery runbooks

### Monitoring

- Set up Grafana dashboards for Ceph metrics
- Alert on HEALTH_WARN status
- Monitor OSD utilization per disk
- Track placement group distribution

---

## Reference Links

- [Rook Documentation](https://rook.io/docs/rook/latest-release/)
- [Ceph Documentation](https://docs.ceph.com/)
- [Talos Storage Guide](https://docs.siderolabs.com/kubernetes-guides/csi/storage/)
- [Rook Teardown Guide](https://rook.io/docs/rook/latest-release/Getting-Started/ceph-teardown/)
