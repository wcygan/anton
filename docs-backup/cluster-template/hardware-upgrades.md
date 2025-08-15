# Hardware Upgrades with Cluster-Template

This guide covers hardware upgrades for Talos Linux clusters built using the
[onedr0p/cluster-template](https://github.com/onedr0p/cluster-template). It
provides a systematic approach to safely upgrading hardware components while
maintaining cluster availability.

## Table of Contents

- [Overview](#overview)
- [Pre-Upgrade Checklist](#pre-upgrade-checklist)
- [Configuration Management](#configuration-management)
- [Hardware Upgrade Process](#hardware-upgrade-process)
- [Post-Upgrade Configuration](#post-upgrade-configuration)
- [Automation Scripts](#automation-scripts)
- [Rollback Procedures](#rollback-procedures)
- [Examples](#examples)

## Overview

The cluster-template uses `talhelper` to manage Talos configurations
declaratively. This approach simplifies hardware upgrades by:

- Generating node-specific configurations from `talconfig.yaml`
- Managing patches for hardware-specific settings
- Automating configuration application through task commands

### Key Components

1. **talconfig.yaml** - Main configuration file defining cluster and node specs
2. **talenv.yaml** - Version management for Talos and Kubernetes
3. **patches/** - Modular configuration patches
4. **Taskfile** - Automated tasks for common operations

## Pre-Upgrade Checklist

Before starting any hardware upgrade:

### 1. Verify Cluster Health

```bash
# Check all nodes are ready
kubectl get nodes

# Verify etcd cluster health (for 3-node clusters)
kubectl -n kube-system get pods -l component=etcd

# Run comprehensive health check
./scripts/k8s-health-check.ts --verbose

# Check Flux status
flux check
flux get ks -A
```

### 2. Backup Critical Data

```bash
# Export current Talos configuration
talosctl config info
cp -r talos/clusterconfig talos/clusterconfig.backup

# Document current hardware serials (important!)
talosctl get disks -n <node-ip> | tee hardware-inventory.txt
```

### 3. Review Configuration Files

Ensure your `talconfig.yaml` contains accurate hardware information:

```yaml
nodes:
  - hostname: "k8s-1"
    ipAddress: "192.168.1.98"
    installDiskSelector:
      serial: "24304A343650" # Current disk serial
    networkInterfaces:
      - deviceSelector:
          hardwareAddr: "58:47:ca:79:7c:a2" # Current NIC MAC
```

## Configuration Management

### Understanding talhelper Structure

The cluster-template uses a layered configuration approach:

```
talos/
├── talconfig.yaml         # Main configuration
├── talenv.yaml           # Version definitions
├── patches/              # Modular patches
│   ├── global/          # Applied to all nodes
│   ├── controller/      # Control plane specific
│   └── <hostname>/      # Node-specific patches
└── clusterconfig/       # Generated configurations
```

### Hardware-Specific Configuration

#### Disk Selection

For storage upgrades, update the `installDiskSelector`:

```yaml
# By serial number (most specific)
installDiskSelector:
  serial: "NEW_DISK_SERIAL"

# By size (useful for uniform hardware)
installDiskSelector:
  size: ">= 500GB"
  type: "nvme"

# By model
installDiskSelector:
  model: "Samsung SSD 980 PRO"
```

#### Network Interface Selection

For network card upgrades:

```yaml
networkInterfaces:
  - deviceSelector:
      # By MAC address (most specific)
      hardwareAddr: "aa:bb:cc:dd:ee:ff"
      # Or by driver
      driver: "igb"
      # Or by bus path
      busPath: "0000:03:00.0"
```

#### Adding User Volumes

For additional storage devices:

```yaml
# Create a patch file: patches/<hostname>/storage.yaml
machine:
  volumes:
    - name: data-storage
      mountpoint: /var/mnt/data
      diskSelector:
        serial: "ADDITIONAL_DISK_SERIAL"
```

## Hardware Upgrade Process

### Step 1: Prepare Node for Maintenance

```bash
# Set variables
NODE_NAME="k8s-1"
NODE_IP="192.168.1.98"

# Cordon the node (prevent new pods)
kubectl cordon ${NODE_NAME}

# Drain workloads
kubectl drain ${NODE_NAME} \
  --ignore-daemonsets \
  --delete-emptydir-data \
  --force \
  --timeout=300s

# Verify node is drained
kubectl get pods --all-namespaces --field-selector spec.nodeName=${NODE_NAME}
```

### Step 2: Update Configuration

#### For Disk Upgrades

1. Get new disk information:

```bash
# After hardware installation, boot node and check
talosctl get disks -n ${NODE_IP}
```

2. Update `talconfig.yaml`:

```yaml
nodes:
  - hostname: "k8s-1"
    installDiskSelector:
      serial: "NEW_DISK_SERIAL" # Update this
```

#### For Network Card Upgrades

1. Get new interface information:

```bash
talosctl get links -n ${NODE_IP}
```

2. Update network configuration:

```yaml
networkInterfaces:
  - deviceSelector:
      hardwareAddr: "NEW_MAC_ADDRESS" # Update this
```

### Step 3: Regenerate and Apply Configuration

```bash
# Regenerate Talos configs with new hardware info
task talos:generate-config

# Review generated config
diff talos/clusterconfig/anton-${NODE_NAME}.yaml talos/clusterconfig.backup/

# Apply configuration to node
task talos:apply-node IP=${NODE_IP} MODE=auto

# For major hardware changes, may need staged mode
task talos:apply-node IP=${NODE_IP} MODE=staged
talosctl reboot -n ${NODE_IP}
```

### Step 4: Verify Node Recovery

```bash
# Watch node rejoin cluster
kubectl get nodes -w

# Check Talos services
talosctl services -n ${NODE_IP}

# Verify etcd member
kubectl -n kube-system get pods -l component=etcd --field-selector spec.nodeName=${NODE_NAME}

# Uncordon node
kubectl uncordon ${NODE_NAME}
```

## Post-Upgrade Configuration

### Adding Storage Volumes

After adding new disks, configure them as user volumes:

1. Create a node-specific patch:

```bash
mkdir -p talos/patches/${NODE_NAME}
cat > talos/patches/${NODE_NAME}/storage.yaml <<EOF
machine:
  volumes:
    - name: fast-storage
      mountpoint: /var/mnt/fast
      diskSelector:
        serial: "NVME_SERIAL_HERE"
      filesystem:
        type: xfs
        options:
          - noatime
          - nodiratime
EOF
```

2. Update `talconfig.yaml` to include the patch:

```yaml
nodes:
  - hostname: "k8s-1"
    patches:
      - "@./patches/k8s-1/storage.yaml"
```

3. Apply the changes:

```bash
task talos:generate-config
task talos:apply-node IP=${NODE_IP}
```

### Network Performance Tuning

For upgraded network interfaces, apply performance patches:

```yaml
# patches/global/machine-network.yaml
machine:
  network:
    extraHostEntries:
      - ip: 192.168.1.101
        aliases:
          - kubernetes.local
  sysctls:
    net.core.rmem_max: "134217728"
    net.core.wmem_max: "134217728"
    net.ipv4.tcp_rmem: "4096 87380 134217728"
    net.ipv4.tcp_wmem: "4096 65536 134217728"
```

## Automation Scripts

### Health Check Script

Create a comprehensive health check for post-upgrade validation:

```bash
#!/usr/bin/env bash
# scripts/post-upgrade-check.sh

set -euo pipefail

NODE_IP="${1:-}"
if [[ -z "${NODE_IP}" ]]; then
    echo "Usage: $0 <node-ip>"
    exit 1
fi

echo "=== Checking Talos Node ${NODE_IP} ==="

# Check Talos version
echo -n "Talos Version: "
talosctl version --nodes ${NODE_IP} --short

# Check disk configuration
echo -e "\n=== Disk Configuration ==="
talosctl get disks -n ${NODE_IP}

# Check mount points
echo -e "\n=== Mount Points ==="
talosctl get mountstatus -n ${NODE_IP}

# Check network interfaces
echo -e "\n=== Network Interfaces ==="
talosctl get links -n ${NODE_IP}

# Check Kubernetes node
echo -e "\n=== Kubernetes Node Status ==="
NODE_NAME=$(talosctl get hostname -n ${NODE_IP} -o json | jq -r '.spec.hostname')
kubectl get node ${NODE_NAME} -o wide

# Check critical pods
echo -e "\n=== Critical Pods on Node ==="
kubectl get pods --all-namespaces --field-selector spec.nodeName=${NODE_NAME} \
    | grep -E "(etcd|kube-apiserver|kube-controller|kube-scheduler|cilium)"
```

### Batch Upgrade Script

For upgrading multiple nodes:

```bash
#!/usr/bin/env bash
# scripts/rolling-hardware-upgrade.sh

NODES=("192.168.1.98" "192.168.1.99" "192.168.1.100")

for NODE_IP in "${NODES[@]}"; do
    echo "=== Starting upgrade for node ${NODE_IP} ==="
    
    # Your upgrade process here
    kubectl drain ...
    
    read -p "Hardware upgraded for ${NODE_IP}? Press enter to continue..."
    
    task talos:apply-node IP=${NODE_IP}
    
    # Wait for node recovery
    sleep 60
    
    ./scripts/post-upgrade-check.sh ${NODE_IP}
    
    read -p "Continue to next node? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
done
```

## Rollback Procedures

If issues occur during hardware upgrades:

### 1. Configuration Rollback

```bash
# Restore previous configuration
cp -r talos/clusterconfig.backup/* talos/clusterconfig/

# Apply old configuration
talosctl apply-config \
  --nodes ${NODE_IP} \
  --file talos/clusterconfig/anton-${NODE_NAME}.yaml
```

### 2. Hardware Rollback

If new hardware causes issues:

1. Power down the node
2. Replace with original hardware
3. Boot the node
4. Apply original configuration

### 3. Emergency Recovery

For critical failures:

```bash
# Reset node to maintenance mode
talosctl reset --nodes ${NODE_IP} \
  --system-labels-to-wipe STATE \
  --system-labels-to-wipe EPHEMERAL

# Rejoin cluster
task talos:apply-node IP=${NODE_IP} MODE=auto
```

## Examples

### Example 1: Adding NVMe Storage

```yaml
# talconfig.yaml update
nodes:
  - hostname: "k8s-1"
    ipAddress: "192.168.1.98"
    installDiskSelector:
      serial: "24304A343650" # Keep system disk
    patches:
      - "@./patches/k8s-1/nvme-storage.yaml"

# patches/k8s-1/nvme-storage.yaml
machine:
  volumes:
    - name: fast-cache
      mountpoint: /var/mnt/cache
      diskSelector:
        serial: "SAMSUNG_NVME_S5H9NX0N123456"
      filesystem:
        type: xfs
```

### Example 2: Network Card Upgrade

```yaml
# Update for 10GbE upgrade
networkInterfaces:
  - deviceSelector:
      hardwareAddr: "aa:bb:cc:dd:ee:ff" # New 10GbE NIC
    addresses:
      - "192.168.1.98/24"
    routes:
      - network: "0.0.0.0/0"
        gateway: "192.168.1.254"
    mtu: 9000 # Enable jumbo frames
```

### Example 3: Memory/CPU Scaling

While CPU/memory don't require Talos config changes, update resource
allocations:

```yaml
# patches/global/machine-kubelet.yaml
machine:
  kubelet:
    extraConfig:
      systemReserved:
        cpu: "2"
        memory: "4Gi"
      kubeReserved:
        cpu: "1"
        memory: "2Gi"
```

## Best Practices

1. **Always upgrade one node at a time** to maintain quorum
2. **Test configuration changes** in a non-production environment first
3. **Document hardware serials** before and after upgrades
4. **Use version control** for all configuration changes
5. **Monitor cluster health** throughout the upgrade process
6. **Keep backups** of working configurations
7. **Plan for rollback** before starting any upgrade

## References

- [Talos Configuration Patching](https://www.talos.dev/v1.10/talos-guides/configuration/patching/)
- [talhelper Documentation](https://github.com/budimanjojo/talhelper)
- [Cluster-Template Repository](https://github.com/onedr0p/cluster-template)
- [Kubernetes Node Maintenance](https://kubernetes.io/docs/tasks/administer-cluster/safely-drain-node/)
