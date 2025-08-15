# k8s-3 NVMe Storage Addition Example

This document provides a complete example of adding NVMe storage to a Talos Linux cluster node, using the successful k8s-3 installation as a reference.

## Overview

**Objective**: Add 2x 1TB WD_BLACK SN7100 NVMe SSDs to k8s-3 (192.168.1.100) for additional fast storage.

**Result**: Successfully mounted both SSDs with XFS filesystems at `/var/mnt/fast1` and `/var/mnt/fast2`.

## Hardware Configuration

### Before Installation
- **System Drive**: CT500P3SSD8 (500GB) - Serial: 24304A23705F
- **Available Slots**: 2 empty M.2 slots (left and middle)

### After Installation
- **nvme0n1**: WD_BLACK SN7100 1TB - Serial: 251021801882 → `/var/mnt/fast2`
- **nvme1n1**: CT500P3SSD8 500GB - Serial: 24304A23705F → system drive
- **nvme2n1**: WD_BLACK SN7100 1TB - Serial: 251021800405 → `/var/mnt/fast1`

> **Note**: The original system drive moved from nvme0n1 to nvme1n1 during installation.

## Pre-Installation Steps

### 1. Cluster Health Verification

```bash
# Check overall cluster health
deno task monitor:all

# Verify all nodes are Ready
kubectl get nodes

# Check etcd health
kubectl -n kube-system get pods -l component=etcd

# Ensure no pending Flux reconciliations
flux get all -A
```

### 2. Create Backup and Inventory

```bash
# Create gitignored directory for sensitive data
mkdir -p progress/ssd-installation

# Backup Talos configuration
cp -r talos/clusterconfig talos/clusterconfig.backup-$(date +%Y%m%d)

# Export current disk configuration
for ip in 192.168.1.98 192.168.1.99 192.168.1.100; do
  echo "=== Node $ip ===" >> progress/ssd-installation/pre-ssd-disk-inventory.txt
  talosctl get disks -n $ip >> progress/ssd-installation/pre-ssd-disk-inventory.txt
done

# Save cluster state
kubectl cluster-info dump --output-directory=progress/ssd-installation/cluster-state-$(date +%Y%m%d)

# Document storage baseline
./scripts/storage-health-check.ts --json > progress/ssd-installation/pre-ssd-storage-state.json
```

## Node Preparation and Drain

### 1. Set Node Variables

```bash
export NODE_NAME="k8s-3"
export NODE_IP="192.168.1.100"
```

### 2. Graceful Workload Migration

```bash
# Check current workloads
kubectl get pods --field-selector spec.nodeName=${NODE_NAME} -A

# Cordon node to prevent new scheduling
kubectl cordon ${NODE_NAME}

# Drain all pods (may take several minutes)
kubectl drain ${NODE_NAME} --ignore-daemonsets --delete-emptydir-data --force --timeout=600s

# Verify only DaemonSets and control plane remain
kubectl get pods --field-selector spec.nodeName=${NODE_NAME} -A
```

### 3. Power Down Node

```bash
# Graceful shutdown via Talos
talosctl shutdown -n ${NODE_IP}

# Verify complete shutdown
ping -c 3 ${NODE_IP}  # Should timeout with 100% packet loss
```

## Physical Installation

1. **Locate MS-01 mini PC** for k8s-3 (192.168.1.100)
2. **Open case** and identify M.2 slots:
   - Right slot: Current system drive (keep as-is)
   - Middle slot: Install first new SSD
   - Left slot: Install second new SSD
3. **Install both M.2 SSDs** in available slots
4. **Close case** and power on

## Post-Installation Configuration

### 1. Verify Hardware Detection

```bash
# Wait for node to boot
talosctl health -n ${NODE_IP} --wait-timeout 10m

# Check new disk configuration
talosctl get disks -n ${NODE_IP}
```

**Expected Output:**
```
NODE            NAMESPACE   TYPE   ID        SIZE     MODEL                 SERIAL
192.168.1.100   runtime     Disk   nvme0n1   1.0 TB   WD_BLACK SN7100 1TB   251021801882
192.168.1.100   runtime     Disk   nvme1n1   500 GB   CT500P3SSD8           24304A23705F
192.168.1.100   runtime     Disk   nvme2n1   1.0 TB   WD_BLACK SN7100 1TB   251021800405
```

### 2. Create Storage Patch

Create node-specific storage configuration:

```bash
mkdir -p talos/patches/k8s-3
cat > talos/patches/k8s-3/storage.yaml << 'EOF'
machine:
  disks:
    - device: /dev/disk/by-id/nvme-WD_BLACK_SN7100_1TB_251021801882
      partitions:
        - mountpoint: /var/mnt/fast1
    - device: /dev/disk/by-id/nvme-WD_BLACK_SN7100_1TB_251021800405
      partitions:
        - mountpoint: /var/mnt/fast2
EOF
```

### 3. Update Talos Configuration

Add the storage patch to `talos/talconfig.yaml`:

```yaml
# Find the k8s-3 node section and add patches
- hostname: "k8s-3"
  ipAddress: "192.168.1.100"
  installDiskSelector:
    serial: "24304A23705F"
  # ... other config ...
  patches:
    - "@./patches/k8s-3/storage.yaml"
```

### 4. Generate and Apply Configuration

```bash
# Generate new configuration with storage patches
task talos:generate-config

# Apply configuration (will trigger reboot)
task talos:apply-node IP=${NODE_IP} MODE=auto
```

**Expected Output:**
```
Applied configuration with a reboot: this config change can't be applied in immediate mode
diff:
--- a
+++ b
@@ -37,6 +37,13 @@
         disableSearchDomain: true
+    disks:
+        - device: /dev/disk/by-id/nvme-WD_BLACK_SN7100_1TB_251021801882
+          partitions:
+            - mountpoint: /var/mnt/fast1
+        - device: /dev/disk/by-id/nvme-WD_BLACK_SN7100_1TB_251021800405
+          partitions:
+            - mountpoint: /var/mnt/fast2
```

## Verification and Restoration

### 1. Wait for Node Recovery

```bash
# Wait for node to become Ready
kubectl wait --for=condition=Ready node/${NODE_NAME} --timeout=300s

# Check node status
kubectl get node ${NODE_NAME}
```

### 2. Verify Storage Mounts

```bash
# Check mounted filesystems
talosctl read /proc/mounts -n ${NODE_IP} | grep fast
```

**Expected Output:**
```
/dev/nvme0n1p1 /var/mnt/fast2 xfs rw,seclabel,relatime,attr2,inode64,logbufs=8,logbsize=32k,sunit=64,swidth=512,noquota 0 0
/dev/nvme1n1p1 /var/mnt/fast1 xfs rw,seclabel,relatime,attr2,inode64,logbufs=8,logbsize=32k,sunit=64,swidth=512,noquota 0 0
```

### 3. Verify Storage Accessibility

```bash
# Test both mount points
talosctl ls /var/mnt/fast1 -n ${NODE_IP}
talosctl ls /var/mnt/fast2 -n ${NODE_IP}
```

### 4. Restore Workload Scheduling

```bash
# Re-enable scheduling
kubectl uncordon ${NODE_NAME}

# Verify workloads return
kubectl get pods --field-selector spec.nodeName=${NODE_NAME} -A
```

## Final Health Checks

### 1. Node and Cluster Status

```bash
# Verify node is healthy
kubectl get node ${NODE_NAME}

# Check Flux reconciliations
flux get all -A | grep False  # Should show no failures

# Run comprehensive health check
deno task monitor:all
```

### 2. Storage Performance Test

```bash
# Create test pod to verify storage
kubectl apply -f - << 'EOF'
apiVersion: v1
kind: Pod
metadata:
  name: storage-test-k8s-3
  namespace: default
spec:
  containers:
  - name: test
    image: busybox
    command: ['sh', '-c', 'echo "Fast storage test" > /mnt/fast1/test1.txt && echo "Fast storage test" > /mnt/fast2/test2.txt && ls -la /mnt/fast*']
    volumeMounts:
    - name: fast-storage-1
      mountPath: /mnt/fast1
    - name: fast-storage-2
      mountPath: /mnt/fast2
  volumes:
  - name: fast-storage-1
    hostPath:
      path: /var/mnt/fast1
      type: Directory
  - name: fast-storage-2
    hostPath:
      path: /var/mnt/fast2
      type: Directory
  nodeSelector:
    kubernetes.io/hostname: k8s-3
  restartPolicy: Never
EOF

# Check test results
kubectl logs storage-test-k8s-3

# Clean up test pod
kubectl delete pod storage-test-k8s-3
```

## Configuration Files Reference

### Talos Storage Patch (`talos/patches/k8s-3/storage.yaml`)

```yaml
machine:
  disks:
    - device: /dev/disk/by-id/nvme-WD_BLACK_SN7100_1TB_251021801882
      partitions:
        - mountpoint: /var/mnt/fast1
    - device: /dev/disk/by-id/nvme-WD_BLACK_SN7100_1TB_251021800405
      partitions:
        - mountpoint: /var/mnt/fast2
```

### Node Configuration Update (`talos/talconfig.yaml`)

```yaml
- hostname: "k8s-3"
  ipAddress: "192.168.1.100"
  installDiskSelector:
    serial: "24304A23705F"  # Original system disk
  machineSpec:
    secureboot: false
  talosImageURL: factory.talos.dev/installer/064d2c892ac9a3a7da7fa550dbdd1516908bd9dfe355ad345ff4e9d8f8b34930
  controlPlane: true
  networkInterfaces:
    - deviceSelector:
        hardwareAddr: "58:47:ca:7a:54:aa"
      dhcp: false
      addresses:
        - "192.168.1.100/24"
      routes:
        - network: "0.0.0.0/0"
          gateway: "192.168.1.254"
      mtu: 1500
      vip:
        ip: "192.168.1.101"
  patches:
    - "@./patches/k8s-3/storage.yaml"  # Add this line
```

## Key Learnings

### 1. Hardware Slot Mapping
- M.2 slot positions can affect device naming (nvme0n1, nvme1n1, nvme2n1)
- Use device IDs with serial numbers for reliable identification
- System disk may change device names after adding storage

### 2. Talos Configuration Best Practices
- Always use device IDs with serial numbers instead of device paths
- Node-specific patches should be in `talos/patches/{node-name}/`
- Configuration changes requiring disk formatting trigger automatic reboot

### 3. Cluster Management
- Drain nodes gracefully to avoid workload disruption
- Monitor etcd health during control plane node operations
- Verify Flux reconciliations after configuration changes

### 4. Storage Considerations
- XFS filesystem is automatically chosen for additional storage
- Mount points should be under `/var/mnt/` for persistence
- Test storage accessibility after configuration changes

## Troubleshooting

### Common Issues

**1. YAML Syntax Errors in Storage Patch**
```bash
# Validate YAML syntax
task talos:generate-config
# Look for "unknown keys" or "could not find expected" errors
```

**2. Device Not Found After Reboot**
```bash
# Check if device IDs are correct
talosctl get disks -n ${NODE_IP}
# Update patch with actual device IDs from output
```

**3. Node Won't Rejoin Cluster**
```bash
# Check Talos health
talosctl health -n ${NODE_IP}
# Verify etcd cluster health
kubectl -n kube-system exec -it etcd-k8s-1 -- etcdctl member list
```

**4. Workloads Not Scheduling Back**
```bash
# Ensure node is uncordoned
kubectl get node ${NODE_NAME}
# Check for taints or resource constraints
kubectl describe node ${NODE_NAME}
```

## Next Steps

After successful storage addition:

1. **Update monitoring thresholds** for new storage capacity
2. **Configure applications** to use fast storage mount points
3. **Document storage allocation** in cluster documentation
4. **Repeat process** for remaining nodes (k8s-2, k8s-1)
5. **Consider storage classes** for Kubernetes persistent volumes

## Files Modified

- `talos/talconfig.yaml` - Added storage patch reference
- `talos/patches/k8s-3/storage.yaml` - Storage configuration
- `progress/ssd-installation/` - Installation tracking data (gitignored)

## Reference Links

- [Talos Machine Configuration](https://www.talos.dev/v1.10/reference/configuration/machine/)
- [MS-01 Storage Expansion Guide](https://blog.pcfe.net/hugo/posts/2024-12-24-minisforum-ms-01-add-storage/)
- [Kubectl Node Maintenance](https://kubernetes.io/docs/tasks/administer-cluster/safely-drain-node/)