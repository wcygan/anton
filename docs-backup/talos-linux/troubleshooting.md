# Talos Linux Troubleshooting Guide

This guide covers common troubleshooting scenarios when working with Talos Linux clusters.

## Table of Contents

- [Configuration Changes and Node Reboots](#configuration-changes-and-node-reboots)
- [Kubernetes API Access Issues](#kubernetes-api-access-issues)
- [Node Health Verification](#node-health-verification)
- [Storage and Disk Management](#storage-and-disk-management)
- [Common Commands Reference](#common-commands-reference)

## Configuration Changes and Node Reboots

When applying configuration changes that require a reboot (like storage modifications), nodes will restart and temporarily disconnect from the cluster.

### Symptoms
- `kubectl` commands timeout with errors like:
  ```
  Unable to connect to the server: dial tcp <IP>:443: i/o timeout
  ```
- Nodes show as `NotReady` or unreachable

### Resolution Process

1. **Wait for nodes to complete reboot** (typically 30-60 seconds)
   ```bash
   sleep 30
   ```

2. **Verify nodes are back online via talosctl**
   ```bash
   talosctl -n <node-ip> get members
   ```

3. **Check etcd cluster health**
   ```bash
   talosctl -n <node-ip> etcd members
   ```

4. **Regenerate kubeconfig if needed**
   ```bash
   talosctl -n <node-ip> kubeconfig --force
   ```

## Kubernetes API Access Issues

After node reboots or configuration changes, you may lose access to the Kubernetes API even though the nodes are healthy.

### Troubleshooting Steps

1. **Verify talosctl connectivity first**
   ```bash
   # Check if you can reach nodes via Talos API
   talosctl -n 192.168.1.98,192.168.1.99,192.168.1.100 get members
   ```

2. **Check etcd cluster status**
   ```bash
   # Ensure all etcd members are present
   talosctl -n <any-node-ip> etcd members
   ```

3. **Force kubeconfig regeneration**
   ```bash
   # This updates your local kubeconfig with current cluster info
   talosctl -n <any-node-ip> kubeconfig --force
   ```

4. **Verify kubectl access**
   ```bash
   kubectl get nodes
   ```

### Common Issues

- **Stale kubeconfig**: The cluster endpoint or certificates may have changed
- **VIP not ready**: If using a virtual IP, it may take time to failover
- **Network connectivity**: Ensure no firewall rules are blocking access

## Node Health Verification

When troubleshooting node issues, use these commands to gather information:

### Basic Health Checks

```bash
# Check all nodes at once (note: health command doesn't support multiple nodes)
talosctl -n <node-ip> health --control-plane-nodes 192.168.1.98,192.168.1.99,192.168.1.100

# Get node status individually
for node in 192.168.1.98 192.168.1.99 192.168.1.100; do
  echo "=== Node $node ==="
  talosctl -n $node get members
done
```

### Detailed Node Information

```bash
# Check system services
talosctl -n <node-ip> services

# View recent logs
talosctl -n <node-ip> dmesg

# Check container runtime
talosctl -n <node-ip> containers
```

## Storage and Disk Management

### Verifying Disk Configuration

After applying storage patches, verify the changes took effect:

1. **List all disks**
   ```bash
   talosctl -n <node-ip> get disks
   ```

2. **Check discovered volumes**
   ```bash
   talosctl -n <node-ip> get discoveredvolumes
   ```

3. **Verify mount points**
   ```bash
   talosctl -n <node-ip> read /proc/mounts | grep nvme
   ```

### Example: Removing Disk Mounts

When preparing disks for Ceph or other storage solutions:

```bash
# Check current mounts
for node in 192.168.1.98 192.168.1.99 192.168.1.100; do
  echo "=== Node $node ==="
  talosctl -n $node read /proc/mounts | grep -E "nvme[01]n1" || echo "No mounts for nvme0n1/nvme1n1"
done
```

## Common Commands Reference

### Configuration Management

```bash
# Generate new configs
task talos:generate-config

# Apply config to specific node
task talos:apply-node IP=192.168.1.98

# Apply with auto mode (handles reboots)
task talos:apply-node IP=192.168.1.98 MODE=auto
```

### Cluster Operations

```bash
# Force reconciliation after changes
task reconcile

# Upgrade Talos on a node
task talos:upgrade-node IP=192.168.1.98

# Upgrade Kubernetes version
task talos:upgrade-k8s
```

### Debugging Commands

```bash
# Get all resources in flux-system namespace
kubectl -n flux-system get all

# Watch node status in real-time
kubectl get nodes -w

# Check recent events
kubectl get events -A --sort-by='.lastTimestamp'
```

## Troubleshooting Workflow

When encountering issues after configuration changes:

1. **Verify Talos API access** - Can you reach nodes via talosctl?
2. **Check node membership** - Are all nodes visible in the cluster?
3. **Verify etcd health** - Is the etcd cluster formed with all members?
4. **Regenerate kubeconfig** - Update local access credentials
5. **Test kubectl access** - Confirm Kubernetes API is accessible
6. **Verify specific changes** - Did your configuration changes apply correctly?

## Tips

- Always use `--force` when regenerating kubeconfig after major changes
- Wait at least 30-60 seconds after node reboots before troubleshooting
- Use `talosctl` for node-level debugging before trying `kubectl`
- Check multiple nodes when debugging - issues may be node-specific
- The warning about server/client version mismatch is usually harmless