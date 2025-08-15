# Talos Linux Storage and Disk Management Guide

This guide provides a comprehensive overview of storage and disk management in
Talos Linux, including system partitions, user volumes, Kubernetes storage
integration, and practical examples from our homelab cluster.

## Table of Contents

- [System Disk Layout](#system-disk-layout)
- [Disk Management Commands](#disk-management-commands)
- [User Volumes Configuration](#user-volumes-configuration)
- [Kubernetes Storage Integration](#kubernetes-storage-integration)
- [Storage Best Practices](#storage-best-practices)
- [Homelab Configuration Examples](#homelab-configuration-examples)
- [Troubleshooting](#troubleshooting)

## System Disk Layout

Talos Linux uses a specific partition layout for system disks that ensures
immutability and separation of concerns:

### Default Partitions

When Talos is installed, it creates the following partitions:

1. **EFI Partition** (~105 MB)
   - Mount: `/boot/efi`
   - Filesystem: vfat
   - Purpose: UEFI boot files

2. **BIOS Partition** (~1 MB)
   - Purpose: Legacy BIOS boot support

3. **BOOT Partition** (~1 GB)
   - Filesystem: xfs
   - Purpose: Kernel and initramfs

4. **META Partition** (~1 MB)
   - Filesystem: talosmeta
   - Purpose: Talos metadata storage

5. **STATE Partition** (~105 MB)
   - Filesystem: xfs
   - Purpose: Machine configuration and secrets

6. **EPHEMERAL Partition** (remaining space)
   - Mount: `/var`
   - Filesystem: xfs
   - Purpose: Container runtime data, logs, etcd data

### Example from Our Cluster

```bash
# Disk layout on node 192.168.1.98 (500GB NVMe)
nvme0n1     500 GB    # Main system disk
├─nvme0n1p1 105 MB    # EFI partition
├─nvme0n1p2 1.0 MB    # BIOS partition
├─nvme0n1p3 1.0 GB    # BOOT partition
├─nvme0n1p4 1.0 MB    # META partition
├─nvme0n1p5 105 MB    # STATE partition
└─nvme0n1p6 499 GB    # EPHEMERAL partition
```

## Disk Management Commands

Talos provides several commands for disk and volume management:

### List Available Disks

```bash
# Show all block devices on a node
talosctl get disks -n <node-ip>

# Example output:
# NODE         TYPE   ID        SIZE     TRANSPORT   MODEL         SERIAL
# 192.168.1.98 Disk   nvme0n1   500 GB   nvme        CT500P3SSD8   24304A343650
```

### Discover Volumes

```bash
# Show all discovered volumes including partitions
talosctl get discoveredvolumes -n <node-ip>

# Shows partition details including:
# - Partition ID and type
# - Size and filesystem
# - Label information
```

### Check Mount Status

```bash
# View current mount points and volumes
talosctl get mountstatus -n <node-ip>

# Key mounts:
# - /var (EPHEMERAL partition)
# - /var/lib/etcd (etcd data)
# - /var/lib/kubelet (Kubernetes data)
# - /var/lib/containerd (Container runtime)
```

### System Disk Information

```bash
# Identify the system disk
talosctl get systemdisk -n <node-ip>

# Output shows which disk Talos is using for the system
```

## User Volumes Configuration

Starting with Talos v1.10, user volumes provide flexible disk management through
the `UserVolumeConfig` API.

### Basic User Volume Configuration

```yaml
machine:
  volumes:
    - name: data-volume
      mountpoint: /var/mnt/data
      diskSelector:
        size: ">= 100GB"
        type: nvme
```

### Advanced Disk Selection with CEL

User volumes support CEL (Common Expression Language) for flexible disk
selection:

```yaml
machine:
  volumes:
    - name: cache-volume
      mountpoint: /var/mnt/cache
      diskSelector:
        # Select NVMe disks larger than 200GB
        match: 'disk.type == "nvme" && disk.size >= 214748364800'
```

### Volume Configuration Options

```yaml
machine:
  volumes:
    - name: storage-volume
      mountpoint: /var/mnt/storage
      diskSelector:
        size: ">= 500GB"
      provisioning:
        minSize: 100GB # Minimum volume size
        maxSize: 1TB # Maximum volume size
        grow: true # Allow automatic growth
      filesystem:
        type: xfs # Filesystem type
      encryption:
        enabled: true # Enable disk encryption
```

### Volume Naming Rules

- 1-34 characters long
- ASCII letters, digits, and dashes only
- Must be unique within the node

## Kubernetes Storage Integration

### Storage Classes

Our homelab uses Local Path Provisioner as the default storage class:

```yaml
# Current storage class configuration
Name: local-path
Provisioner: rancher.io/local-path
VolumeBindingMode: WaitForFirstConsumer
ReclaimPolicy: Delete
```

### Persistent Volume Examples

```bash
# List persistent volumes
kubectl get pv

# Example volumes in our cluster:
# - 1Gi for DragonflyDB cache
# - 5Gi for PostgreSQL databases
# - 8Gi for Airflow PostgreSQL
# - 100Gi for Airflow logs
# - 2Gi for Open WebUI
```

### Creating Persistent Volume Claims

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: app-storage
  namespace: default
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: local-path
  resources:
    requests:
      storage: 10Gi
```

### Recommended Storage Solutions

For production workloads, consider these distributed storage solutions:

1. **Longhorn** - Simple, reliable Kubernetes storage with snapshots
2. **Rook/Ceph** - Enterprise-scale distributed storage
3. **OpenEBS Mayastor** - High-performance NVMe storage
4. **Piraeus/LINSTOR** - DRBD-based distributed storage

## Storage Best Practices

### 1. Disk Selection

- Use dedicated disks for storage workloads
- Prefer NVMe for high-performance applications
- Consider disk redundancy for critical data

### 2. Volume Planning

```yaml
# Example: Separate volumes for different workloads
machine:
  volumes:
    - name: database-volume
      mountpoint: /var/mnt/database
      diskSelector:
        type: nvme
        size: ">= 200GB"

    - name: logs-volume
      mountpoint: /var/mnt/logs
      diskSelector:
        type: ssd
        size: ">= 100GB"
```

### 3. Resource Management

- Set appropriate resource limits for storage-intensive pods
- Monitor disk usage and I/O performance
- Use volume expansion policies when needed

### 4. Backup Strategies

- Implement regular backup procedures
- Test restore processes
- Consider off-cluster backup storage

## Homelab Configuration Examples

### Adding Storage to Existing Nodes

When adding new NVMe drives to MS-01 nodes:

1. **Plan the maintenance window**
   ```bash
   # Check cluster health before starting
   kubectl get nodes
   ./scripts/k8s-health-check.ts --verbose
   ```

2. **Drain the node**
   ```bash
   kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data
   ```

3. **Add physical storage** (see [NVMe Addition Guide](nvme-addition.md))

4. **Configure new volumes**
   ```yaml
   # Add to machine configuration
   machine:
     volumes:
       - name: additional-storage
         mountpoint: /var/mnt/storage
         diskSelector:
           serial: "NEW_DRIVE_SERIAL"
   ```

5. **Apply configuration**
   ```bash
   task talos:apply-node IP=<node-ip> MODE=auto
   ```

### Storage for Specific Applications

#### Database Storage

```yaml
# PostgreSQL with dedicated volume
machine:
  volumes:
    - name: postgres-data
      mountpoint: /var/mnt/postgres
      diskSelector:
        size: ">= 100GB"
      filesystem:
        type: xfs
        options:
          - noatime
          - nodiratime
```

#### Container Image Cache

```yaml
# Spegel image cache volume
machine:
  volumes:
    - name: image-cache
      mountpoint: /var/mnt/imagecache
      diskSelector:
        size: ">= 50GB"
```

## Troubleshooting

### Common Issues

1. **Disk Not Detected**
   ```bash
   # Check if disk is visible
   talosctl get disks -n <node-ip>

   # Look for hardware issues in dmesg
   talosctl dmesg -n <node-ip> | grep -i nvme
   ```

2. **Volume Mount Failures**
   ```bash
   # Check mount status
   talosctl get mountstatus -n <node-ip>

   # View Talos logs
   talosctl logs -n <node-ip> | grep -i mount
   ```

3. **Storage Class Issues**
   ```bash
   # Verify storage class
   kubectl describe storageclass local-path

   # Check provisioner pods
   kubectl get pods -n kube-system | grep local-path
   ```

### Performance Monitoring

```bash
# Disk I/O statistics
talosctl dashboard -n <node-ip>

# Kubernetes storage metrics
kubectl top nodes
kubectl describe pv <pv-name>
```

### Wiping Disks

**Warning**: This is destructive!

```bash
# Wipe a specific disk (removes all data)
talosctl wipe disk --nodes <node-ip> --disk /dev/nvme0n1
```

## References

- [Talos Disk Management Guide](https://www.talos.dev/v1.10/talos-guides/configuration/disk-management/)
- [Kubernetes Storage Documentation](https://kubernetes.io/docs/concepts/storage/)
- [Local Path Provisioner](https://github.com/rancher/local-path-provisioner)
- [Talos User Volumes Configuration](https://www.talos.dev/v1.10/reference/configuration/v1alpha1/config/#UserVolumeConfig)
