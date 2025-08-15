# Talos Infrastructure Golden Rules

## The Golden Rule

**Never apply untested machine configs to all nodes simultaneously.** Talos is immutable - a bad config means nodes won't boot. Always test on a single node first, verify it comes back, then proceed.

## Critical Rules

### 1. Always Test Machine Config on Single Node First

**WRONG:**
```bash
# Applying to all nodes at once
talosctl apply-config --nodes 192.168.1.98,192.168.1.99,192.168.1.100 \
  --file controlplane.yaml
# If config is bad, entire cluster is down!
```

**RIGHT:**
```bash
# Test on single node first
talosctl apply-config --nodes 192.168.1.98 --file controlplane.yaml

# Wait and verify node comes back
talosctl health --nodes 192.168.1.98

# Check kubelet is healthy
talosctl service kubelet --nodes 192.168.1.98

# Only then apply to other nodes
for node in 192.168.1.99 192.168.1.100; do
  talosctl apply-config --nodes $node --file controlplane.yaml
  sleep 300  # Wait between nodes
  talosctl health --nodes $node
done
```

**Why:** Bad machine configs can prevent nodes from booting. Testing on one node limits blast radius.

### 2. Never Upgrade Talos and Kubernetes Simultaneously

**WRONG:**
```bash
# Upgrading both at once
talosctl upgrade --nodes 192.168.1.98 \
  --image ghcr.io/siderolabs/installer:v1.6.0 \
  --preserve
  
# Immediately upgrading k8s
talosctl upgrade-k8s --to 1.29.0
```

**RIGHT:**
```bash
# Step 1: Upgrade Talos on all nodes
for node in 192.168.1.98 192.168.1.99 192.168.1.100; do
  echo "Upgrading Talos on $node"
  talosctl upgrade --nodes $node \
    --image ghcr.io/siderolabs/installer:v1.6.0 \
    --preserve
  
  # Wait for node to be ready
  kubectl wait --for=condition=Ready node/k8s-${node##*.} --timeout=10m
done

# Step 2: Verify cluster health
talosctl health --nodes 192.168.1.98,192.168.1.99,192.168.1.100

# Step 3: Only then upgrade Kubernetes
talosctl upgrade-k8s --to 1.29.0
```

**Why:** Simultaneous upgrades compound failure modes. Sequential upgrades allow easier rollback.

### 3. Always Backup etcd Before Infrastructure Changes

**WRONG:**
```bash
# Making changes without etcd backup
talosctl edit machineconfig --nodes 192.168.1.98
# What if this corrupts etcd?
```

**RIGHT:**
```bash
# Take etcd snapshot first
talosctl etcd snapshot db.snapshot --nodes 192.168.1.98

# Verify snapshot
talosctl etcd status --nodes 192.168.1.98

# Keep snapshot safe
aws s3 cp db.snapshot s3://backups/etcd/$(date +%Y%m%d-%H%M%S)-db.snapshot

# Now safe to make changes
talosctl edit machineconfig --nodes 192.168.1.98
```

**Why:** etcd contains all cluster state. Without backup, cluster recovery may be impossible.

### 4. Never Modify Kernel Args Without Understanding Impact

**WRONG:**
```yaml
# Adding random kernel parameters
machine:
  kernel:
    args:
      - transparent_hugepage=always  # Performance impact?
      - mitigations=off             # Security impact?
```

**RIGHT:**
```yaml
# Document and test kernel parameters
machine:
  kernel:
    args:
      # Enable serial console for debugging
      - console=ttyS0,115200n8
      # Increase inotify limits for large deployments
      - fs.inotify.max_user_instances=8192
      - fs.inotify.max_user_watches=524288
      # Document why each parameter is needed
```

**Test in dev first:**
```bash
# Apply to test node
talosctl apply-config --nodes test-node --file test-config.yaml

# Verify parameter applied
talosctl read /proc/cmdline --nodes test-node

# Run workload tests
kubectl apply -f stress-test.yaml
```

**Why:** Kernel parameters affect system stability, security, and performance. Wrong values can crash nodes.

### 5. Always Preserve Machine Config Customizations During Upgrades

**WRONG:**
```bash
# Generating fresh config without preserving customizations
talosctl gen config cluster https://cluster.local:6443 \
  --output-dir=./new-config
# Lost all customizations!
```

**RIGHT:**
```bash
# 1. Export current config
talosctl read /system/state/config.yaml --nodes 192.168.1.98 > current-config.yaml

# 2. Generate new config with version
talosctl gen config cluster https://cluster.local:6443 \
  --output-dir=./new-config \
  --with-secrets secrets.yaml

# 3. Merge customizations
yq eval-all 'select(fileIndex == 0) * select(fileIndex == 1)' \
  new-config/controlplane.yaml current-config.yaml > merged-config.yaml

# 4. Validate before applying
talosctl validate --config merged-config.yaml --mode cloud
```

**Why:** Losing customizations can break networking, storage, or extensions.

## Talos Configuration Patterns

### Network Configuration

```yaml
# Stable network configuration
machine:
  network:
    hostname: k8s-1
    interfaces:
      - interface: eth0
        dhcp: false
        addresses:
          - 192.168.1.98/24
        routes:
          - network: 0.0.0.0/0
            gateway: 192.168.1.1
        vip:
          ip: 192.168.1.97  # Shared VIP for HA
    nameservers:
      - 1.1.1.1
      - 8.8.8.8
    # Disable IPv6 if not used
    kubespan:
      enabled: false
```

### Storage Configuration

```yaml
# Disk configuration for Ceph
machine:
  disks:
    - device: /dev/nvme0n1
      partitions:
        - mountpoint: /var/mnt/nvme0
          size: 0  # Use entire disk
  
  kubelet:
    extraMounts:
      - destination: /var/mnt/nvme0
        type: bind
        source: /var/mnt/nvme0
        options:
          - bind
          - rshared
          - rw
```

### Extension Configuration

```yaml
# System extensions
machine:
  install:
    extensions:
      - image: ghcr.io/siderolabs/intel-ucode:20240531
      - image: ghcr.io/siderolabs/iscsi-tools:v0.1.4
      - image: ghcr.io/siderolabs/util-linux-tools:2.40.2
  
  # Extension services
  files:
    - content: |
        [plugins]
          [plugins."io.containerd.grpc.v1.cri".containerd.runtimes.nvidia]
            runtime_type = "io.containerd.runc.v2"
            [plugins."io.containerd.grpc.v1.cri".containerd.runtimes.nvidia.options]
              SystemdCgroup = true
              Runtime = "/usr/bin/nvidia-container-runtime"
      permissions: 0o644
      path: /etc/containerd/conf.d/nvidia.toml
      op: create
```

### Security Hardening

```yaml
# Security settings
machine:
  sysctls:
    # Network security
    net.ipv4.conf.all.rp_filter: "1"
    net.ipv4.conf.default.rp_filter: "1"
    net.ipv4.ip_forward: "1"
    net.ipv6.conf.all.forwarding: "1"
    
    # File system security
    fs.protected_hardlinks: "1"
    fs.protected_symlinks: "1"
    
    # Kernel security
    kernel.kptr_restrict: "2"
    kernel.dmesg_restrict: "1"
  
  # API server audit
  features:
    rbac: true
    auditLog: true
```

## Maintenance Procedures

### Rolling Reboot

```bash
#!/bin/bash
# Safe rolling reboot of Talos nodes

NODES=(192.168.1.98 192.168.1.99 192.168.1.100)

for node in "${NODES[@]}"; do
  echo "Cordoning node $node"
  kubectl cordon k8s-${node##*.}
  
  echo "Draining node $node"
  kubectl drain k8s-${node##*.} \
    --ignore-daemonsets \
    --delete-emptydir-data \
    --force \
    --timeout=300s
  
  echo "Rebooting node $node"
  talosctl reboot --nodes $node
  
  echo "Waiting for node to be ready"
  until talosctl health --nodes $node 2>/dev/null; do
    sleep 10
  done
  
  kubectl wait --for=condition=Ready \
    node/k8s-${node##*.} \
    --timeout=10m
  
  echo "Uncordoning node $node"
  kubectl uncordon k8s-${node##*.}
  
  echo "Waiting 5 minutes before next node"
  sleep 300
done
```

### Config Validation

```bash
# Comprehensive config validation
validate_talos_config() {
  local config=$1
  
  # Syntax validation
  talosctl validate --config $config --mode cloud || return 1
  
  # Check for required customizations
  yq e '.machine.network.hostname' $config || {
    echo "ERROR: Missing hostname"
    return 1
  }
  
  # Verify extensions compatibility
  for ext in $(yq e '.machine.install.extensions[].image' $config); do
    echo "Checking extension: $ext"
    crane manifest $ext || {
      echo "ERROR: Extension not found: $ext"
      return 1
    }
  done
  
  return 0
}
```

## Recovery Procedures

### Node Won't Boot

```bash
# 1. Connect via console (if available)
# Look for config errors in boot log

# 2. Boot into maintenance mode
# Hold down 'e' during boot, add 'talos.environment=maintenance'

# 3. From another node, reset the bad node
talosctl reset --nodes 192.168.1.98 \
  --graceful=false \
  --system-labels-to-wipe STATE \
  --system-labels-to-wipe EPHEMERAL

# 4. Reapply known good config
talosctl apply-config --nodes 192.168.1.98 \
  --file last-known-good.yaml \
  --insecure
```

### etcd Recovery

```bash
# Single member failure
talosctl etcd remove-member bad-node --nodes good-node

# Re-add member
talosctl etcd join --nodes bad-node --endpoints good-node

# Full etcd restore
talosctl bootstrap --nodes 192.168.1.98 \
  --recover-from=./etcd-backup.snapshot
```

## Pre-Operation Checklist

- [ ] Current configs backed up
- [ ] etcd snapshot taken
- [ ] Test node identified for changes
- [ ] Console access verified (if available)
- [ ] Rollback procedure documented
- [ ] Maintenance window scheduled
- [ ] Team notified of changes
- [ ] Health checks scripted

## Incidents

### 2024-06-01: Cluster-Wide Config Failure
- **What happened:** Applied bad network config to all nodes
- **Impact:** Complete cluster outage for 4 hours
- **Root cause:** No single-node testing
- **Lesson:** Always test on one node first

### 2024-08-15: Lost Customizations During Upgrade
- **What happened:** Generated fresh configs for upgrade
- **Impact:** Lost storage mounts, pods couldn't access data
- **Root cause:** Didn't preserve disk customizations
- **Lesson:** Always merge customizations

### 2024-10-20: Kernel Panic from Bad Parameter
- **What happened:** Added incompatible kernel parameter
- **Impact:** Node boot loops
- **Root cause:** No testing of kernel parameters
- **Lesson:** Test all kernel changes in dev