# NVMe Slot Migration in Talos Linux

This document provides detailed procedures for moving NVMe drives between
physical slots in Talos Linux nodes, including proper cluster rejoin procedures
and data integrity verification.

## Table of Contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Understanding Disk Identification](#understanding-disk-identification)
- [Pre-Migration Planning](#pre-migration-planning)
- [Migration Procedures](#migration-procedures)
  - [Scenario A: Moving Data Disks](#scenario-a-moving-data-disks)
  - [Scenario B: Moving System Disks](#scenario-b-moving-system-disks)
- [Cluster Rejoin Process](#cluster-rejoin-process)
- [Validation and Testing](#validation-and-testing)
- [Troubleshooting](#troubleshooting)
- [Best Practices](#best-practices)
- [References](#references)

## Overview

Moving NVMe drives between slots may be necessary for:

- Installing faster NVMe drives in preferred slots (closer to CPU/cooling)
- Reorganizing storage for optimal PCIe lane distribution
- Troubleshooting hardware issues
- Upgrading to larger capacity drives

**Key Principle**: Talos Linux uses disk selectors (primarily serial numbers)
rather than device paths, making it resilient to physical slot changes. However,
proper procedures must be followed to maintain cluster integrity.

## Prerequisites

Before starting any NVMe slot migration:

1. **Cluster Health**:
   ```bash
   # Verify all nodes are healthy
   kubectl get nodes
   ./scripts/k8s-health-check.ts --verbose

   # Check etcd cluster status (critical for control planes)
   kubectl -n kube-system get pods -l component=etcd
   ```

2. **Hardware Inventory**:
   ```bash
   # Document current disk configuration
   NODE_IP="192.168.1.98"
   talosctl get disks -n ${NODE_IP} -o yaml > disk-inventory-before.yaml

   # Save current mount points
   talosctl get mountstatus -n ${NODE_IP} > mount-status-before.txt
   ```

3. **Configuration Backup**:
   ```bash
   # Backup Talos configuration
   cp -r talos/clusterconfig talos/clusterconfig.backup-$(date +%Y%m%d)

   # Export node configuration
   talosctl get machineconfig -n ${NODE_IP} -o yaml > node-config-backup.yaml
   ```

## Understanding Disk Identification

### How Talos Identifies Disks

Talos uses selectors in order of specificity:

1. **Serial Number** (Most Reliable):
   ```yaml
   diskSelector:
     serial: "SAMSUNG_MZVL21T0HCLR_S641NX0T123456"
   ```

2. **Size and Type**:
   ```yaml
   diskSelector:
     size: ">= 1TB"
     type: "nvme"
   ```

3. **Model**:
   ```yaml
   diskSelector:
     model: "Samsung SSD 980 PRO 1TB"
   ```

4. **Bus Path** (Slot-Specific - Avoid):
   ```yaml
   diskSelector:
     busPath: "0000:03:00.0" # Changes with slot!
   ```

### Device Path Changes

When moving NVMe between slots, device paths will change:

- Slot 1: `/dev/nvme0n1`
- Slot 2: `/dev/nvme1n1`
- Slot 3: `/dev/nvme2n1`

This is why using serial numbers is critical.

## Pre-Migration Planning

### 1. Identify Disk Roles

```bash
# Check system disk
talosctl get config -n ${NODE_IP} -o yaml | yq '.machine.install.disk'

# List user volumes
talosctl get config -n ${NODE_IP} -o yaml | yq '.machine.volumes[]'

# Check Kubernetes PVs using local storage
kubectl get pv -o wide | grep ${NODE_NAME}
```

### 2. Plan Slot Assignment

Create a migration plan:

```yaml
# migration-plan.yaml
node: k8s-1
current_layout:
  slot_1: "System Disk - Samsung 980 Pro 1TB (Serial: XXX)"
  slot_2: "Data Disk - WD Black 2TB (Serial: YYY)"
  slot_3: "Empty"

target_layout:
  slot_1: "Fast Cache - Samsung 990 Pro 2TB (Serial: NEW)"
  slot_2: "System Disk - Samsung 980 Pro 1TB (Serial: XXX)"
  slot_3: "Data Disk - WD Black 2TB (Serial: YYY)"
```

### 3. Update Configuration Files

Prepare configuration changes before hardware work:

```yaml
# patches/k8s-1/storage.yaml
machine:
  volumes:
    # Existing volumes with serial selectors remain unchanged
    - name: data-storage
      mountpoint: /var/mnt/data
      diskSelector:
        serial: "WD_BLACK_SERIAL_YYY" # Slot-independent

    # New fast cache in slot 1
    - name: fast-cache
      mountpoint: /var/mnt/cache
      diskSelector:
        serial: "SAMSUNG_990_PRO_NEW"
```

## Migration Procedures

### Scenario A: Moving Data Disks

For non-system disks (additional storage):

#### Step 1: Drain and Prepare Node

```bash
NODE_NAME="k8s-1"
NODE_IP="192.168.1.98"

# Use maintenance script
./scripts/node-maintenance.ts -n ${NODE_NAME} -a drain

# Verify workloads evacuated
kubectl get pods --all-namespaces --field-selector spec.nodeName=${NODE_NAME}
```

#### Step 2: Unmount User Volumes

```bash
# Check current mounts
talosctl -n ${NODE_IP} mounts | grep /var/mnt

# If needed, stop services using the volumes
# Talos will handle this during shutdown
```

#### Step 3: Shutdown Node

```bash
# Graceful shutdown
talosctl shutdown --nodes ${NODE_IP}

# Wait for complete shutdown (monitor via IPMI/physical)
```

#### Step 4: Perform Hardware Changes

1. Power off completely
2. Disconnect power cable
3. Open chassis following anti-static procedures
4. Document current NVMe positions (photos help)
5. Remove NVMe drives carefully
6. Install in new slots per migration plan
7. Install any new drives
8. Close chassis and reconnect power

#### Step 5: Power On and Verify

```bash
# Power on node and wait for Talos to boot
# Monitor via console if available

# Once pingable, check disk detection
talosctl get disks -n ${NODE_IP}

# Verify serials match expected configuration
talosctl get disks -n ${NODE_IP} -o yaml | yq '.spec.serial'
```

#### Step 6: Apply Configuration Updates

```bash
# Regenerate config if needed
task talos:generate-config

# Apply configuration
task talos:apply-node IP=${NODE_IP} MODE=auto

# Verify mounts
talosctl -n ${NODE_IP} mounts | grep /var/mnt
```

### Scenario B: Moving System Disks

Moving system disks requires more care as Talos installation is tied to the
disk.

#### Step 1: Full Preparation

```bash
# In addition to standard prep, ensure you have:
# 1. Talos installation media ready
# 2. Current node configuration backed up
# 3. etcd snapshot if control plane node

# Take etcd snapshot
kubectl exec -n kube-system etcd-${NODE_NAME} -- \
  etcdctl snapshot save /tmp/etcd-backup.db \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key
```

#### Step 2: Update Configuration for New System Disk

```yaml
# talconfig.yaml
nodes:
  - hostname: "k8s-1"
    ipAddress: "192.168.1.98"
    installDiskSelector:
      serial: "NEW_SYSTEM_DISK_SERIAL" # Update this
    patches:
      - "@./patches/k8s-1/storage.yaml"
      - "@./patches/k8s-1/old-system-as-data.yaml"

# patches/k8s-1/old-system-as-data.yaml
machine:
  volumes:
    - name: old-system
      mountpoint: /var/mnt/old-system
      diskSelector:
        serial: "OLD_SYSTEM_DISK_SERIAL"
```

#### Step 3: Wipe and Reinstall

```bash
# After hardware changes and boot
# Wipe the node (this will destroy all data!)
talosctl reset --nodes ${NODE_IP} --graceful=false

# Reinstall Talos with new configuration
# This may require booting from installation media
# and running initial bootstrap commands
```

## Cluster Rejoin Process

### For Data Disk Moves (Node Rejoins Automatically)

1. **Verify Node Status**:
   ```bash
   # Watch node rejoin
   kubectl get nodes -w

   # Check node conditions
   kubectl describe node ${NODE_NAME}
   ```

2. **Restore Scheduling**:
   ```bash
   # Uncordon the node
   ./scripts/node-maintenance.ts -n ${NODE_NAME} -a restore

   # Or manually
   kubectl uncordon ${NODE_NAME}
   ```

3. **Verify Pod Scheduling**:
   ```bash
   # Check pods returning to node
   kubectl get pods --all-namespaces --field-selector spec.nodeName=${NODE_NAME}

   # Monitor pod status
   watch kubectl get pods -A -o wide | grep ${NODE_NAME}
   ```

### For System Disk Moves (Manual Rejoin Required)

1. **Bootstrap Node** (if first control plane):
   ```bash
   talosctl bootstrap --nodes ${NODE_IP}
   ```

2. **Apply Machine Configuration**:
   ```bash
   # Apply the saved configuration
   talosctl apply-config --nodes ${NODE_IP} \
     --file talos/clusterconfig/anton-${NODE_NAME}.yaml
   ```

3. **Verify Control Plane Components**:
   ```bash
   # Check etcd membership
   kubectl -n kube-system exec -it etcd-${NODE_NAME} -- \
     etcdctl member list

   # Verify API server
   talosctl -n ${NODE_IP} services | grep kube-apiserver
   ```

4. **Restore etcd Member** (if needed):
   ```bash
   # Remove old member
   MEMBER_ID=$(kubectl -n kube-system exec -it etcd-${NODE_NAME} -- \
     etcdctl member list | grep ${NODE_NAME} | cut -d',' -f1)

   kubectl -n kube-system exec -it etcd-<healthy-node> -- \
     etcdctl member remove ${MEMBER_ID}

   # Add new member
   kubectl -n kube-system exec -it etcd-<healthy-node> -- \
     etcdctl member add ${NODE_NAME} \
     --peer-urls=https://${NODE_IP}:2380
   ```

## Validation and Testing

### Comprehensive Post-Migration Validation

```bash
#!/usr/bin/env -S deno run --allow-all
# validate-nvme-migration.ts

import $ from "jsr:@david/dax@0.42.0";
import { colors } from "jsr:@cliffy/ansi@1.0.0-rc.7/colors";
import { Table } from "jsr:@cliffy/table@1.0.0-rc.7";

const nodeIP = Deno.args[0];
const nodeName = Deno.args[1];

if (!nodeIP || !nodeName) {
  console.error("Usage: ./validate-nvme-migration.ts <node-ip> <node-name>");
  Deno.exit(1);
}

console.log(colors.blue(`🔍 Validating NVMe migration for ${nodeName} (${nodeIP})\n`));

// Check 1: Disk Detection
console.log(colors.yellow("1. Disk Detection:"));
const disks = await $`talosctl get disks -n ${nodeIP} -o json`.json();
const diskTable = new Table()
  .header(["Device", "Serial", "Size", "Model"])
  .body(
    disks.items.map(d => [
      d.spec.dev_path,
      d.spec.serial,
      d.spec.size,
      d.spec.model
    ])
  );
diskTable.render();

// Check 2: Mount Points
console.log(colors.yellow("\n2. Mount Points:"));
const mounts = await $`talosctl get mountstatus -n ${nodeIP} -o json`.json();
const mountTable = new Table()
  .header(["Source", "Target", "Filesystem"])
  .body(
    mounts.items.map(m => [
      m.spec.source,
      m.spec.target,
      m.spec.filesystem
    ])
  );
mountTable.render();

// Check 3: Kubernetes Node
console.log(colors.yellow("\n3. Kubernetes Node Status:"));
const nodeStatus = await $`kubectl get node ${nodeName} -o json`.json();
const ready = nodeStatus.status.conditions.find(c => c.type === "Ready");
console.log(`Status: ${ready.status === "True" ? colors.green("Ready") : colors.red("NotReady")}`);
console.log(`Version: ${nodeStatus.status.nodeInfo.kubeletVersion}`);

// Check 4: Critical Pods
console.log(colors.yellow("\n4. Critical Pods:"));
const pods = await $`kubectl get pods -A --field-selector spec.nodeName=${nodeName} -o json`.json();
const criticalPods = pods.items.filter(p => 
  p.metadata.namespace === "kube-system" && 
  (p.metadata.name.includes("etcd") || 
   p.metadata.name.includes("kube-apiserver") ||
   p.metadata.name.includes("kube-controller") ||
   p.metadata.name.includes("kube-scheduler"))
);

criticalPods.forEach(pod => {
  const ready = pod.status.conditions?.find(c => c.type === "Ready");
  const status = ready?.status === "True" ? colors.green("Running") : colors.red("Not Ready");
  console.log(`  ${pod.metadata.name}: ${status}`);
});

// Check 5: Storage Classes and PVs
console.log(colors.yellow("\n5. Storage Validation:"));
const pvs = await $`kubectl get pv -o json`.json();
const nodePVs = pvs.items.filter(pv => 
  pv.spec.nodeAffinity?.required?.nodeSelectorTerms?.[0]?.matchExpressions?.some(
    expr => expr.key === "kubernetes.io/hostname" && expr.values.includes(nodeName)
  )
);
console.log(`Local PVs on node: ${nodePVs.length}`);

// Summary
console.log(colors.blue("\n📋 Migration Summary:"));
console.log(`✅ Disks detected: ${disks.items.length}`);
console.log(`✅ Mounts active: ${mounts.items.length}`);
console.log(`✅ Node status: ${ready.status === "True" ? "Ready" : "Not Ready"}`);
console.log(`✅ Critical pods: ${criticalPods.length}`);
console.log(`✅ Local PVs: ${nodePVs.length}`);
```

### Performance Testing

After migration, test disk performance:

```bash
# Test write speed
talosctl -n ${NODE_IP} write /var/mnt/cache/test.dat \
  --size 1G --direct --pattern random

# Test read speed  
talosctl -n ${NODE_IP} read /var/mnt/cache/test.dat \
  --direct --benchmark

# Cleanup
talosctl -n ${NODE_IP} rm /var/mnt/cache/test.dat
```

## Troubleshooting

### Issue: Disk Not Detected After Move

```bash
# Check dmesg for NVMe errors
talosctl dmesg -n ${NODE_IP} | grep -i nvme

# Verify PCIe detection
talosctl -n ${NODE_IP} read /sys/bus/pci/devices/*/class | grep 0108

# May need to rescan PCIe bus
talosctl -n ${NODE_IP} write /sys/bus/pci/rescan "1"
```

### Issue: Mount Failed

```bash
# Check filesystem
talosctl -n ${NODE_IP} execute -- blkid | grep ${SERIAL}

# Verify partition table
talosctl -n ${NODE_IP} execute -- fdisk -l /dev/nvmeXn1

# Check for filesystem errors
talosctl -n ${NODE_IP} execute -- xfs_repair -n /dev/nvmeXn1p1
```

### Issue: Node Won't Rejoin Cluster

```bash
# Check Talos services
talosctl -n ${NODE_IP} services

# Verify etcd connectivity
talosctl -n ${NODE_IP} etcd members

# Check certificates
talosctl -n ${NODE_IP} get certificates

# Force rejoin
talosctl -n ${NODE_IP} kubeconfig --force
```

### Issue: Different Serial Reported

Some NVMe controllers report different serials in different slots:

```yaml
# Use multiple selectors as fallback
diskSelector:
  # Try serial first
  serial: "PRIMARY_SERIAL"
  # Fallback to size + model
  size: ">= 1TB"
  model: "Samsung SSD 980 PRO"
```

## Best Practices

### 1. Documentation

Maintain a hardware inventory:

```yaml
# hardware-inventory.yaml
cluster: anton
nodes:
  k8s-1:
    ip: 192.168.1.98
    hardware:
      cpu: Intel i9-13900H
      ram: 96GB DDR5
      nvme_slots:
        slot_1:
          position: "M.2_1 (CPU Direct)"
          device: "Samsung 990 Pro 2TB"
          serial: "S6Y1NX0T123456"
          purpose: "High-speed cache"
        slot_2:
          position: "M.2_2 (PCH)"
          device: "Samsung 980 Pro 1TB"
          serial: "S5H9NX0N654321"
          purpose: "System disk"
        slot_3:
          position: "M.2_3 (PCH)"
          device: "WD Black SN850X 2TB"
          serial: "WD_22001A0_789012"
          purpose: "Bulk storage"
```

### 2. Testing Procedures

Always test in this order:

1. Dry-run maintenance mode first
2. Test on non-critical node
3. Validate all functionality
4. Document any issues
5. Apply to remaining nodes

### 3. Timing Considerations

- **Simple data disk move**: 30-45 minutes per node
- **System disk migration**: 60-90 minutes per node
- **Always allow buffer time** for unexpected issues
- **Don't rush**: Hardware work requires care

### 4. Recovery Planning

Before any migration:

1. Have rollback plan ready
2. Keep original disk configuration documented
3. Ensure you can reinstall if needed
4. Have out-of-band access (IPMI/console)

## References

- [Talos Disk Management](https://www.talos.dev/v1.5/talos-guides/install/bare-metal-platforms/disk-management/)
- [Kubernetes Node Maintenance](https://kubernetes.io/docs/tasks/administer-cluster/safely-drain-node/)
- [MS-01 Hardware Guide](https://blog.pcfe.net/hugo/posts/2024-12-24-minisforum-ms-01-add-storage/)
- [Local Path Provisioner](https://github.com/rancher/local-path-provisioner)
