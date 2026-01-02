---
description: Manage Talos configuration, troubleshoot nodes, plan upgrades, and apply best practices
---

Help with Talos Linux configuration, troubleshooting, extensions, and cluster management.

**Determine user intent by asking if not clear:**

1. **Health Check** - Diagnose node/cluster issues
2. **Configuration Change** - Modify talconfig.yaml or patches
3. **Extension Management** - Add/update system extensions
4. **Upgrade Planning** - Plan Talos or Kubernetes upgrade
5. **Best Practice Audit** - Review configuration against production recommendations

---

## 1. Health Check & Troubleshooting

**Diagnostic commands (run in parallel):**

```bash
# Cluster-wide health (requires single node + control plane list)
talosctl health -n 192.168.1.98 --control-plane-nodes 192.168.1.98,192.168.1.99,192.168.1.100

# Per-node diagnostics
talosctl -n {IP} version
talosctl -n {IP} dmesg | tail -100
talosctl -n {IP} services
talosctl -n {IP} get members
talosctl -n {IP} get machinestatus

# Etcd health (control plane only)
talosctl -n {IP} etcd members
talosctl -n {IP} etcd status

# Disk and mount status
talosctl -n {IP} get mounts
talosctl -n {IP} get disks

# Network diagnostics
talosctl -n {IP} get addresses
talosctl -n {IP} get routes
talosctl -n {IP} get links
```

**Common issues and fixes:**

| Symptom | Diagnostic | Fix |
|---------|------------|-----|
| Node not responding | `talosctl -n {IP} dmesg` | Check network, reboot via console |
| Etcd unhealthy | `talosctl -n {IP} etcd status` | Check disk space, member quorum |
| Services failing | `talosctl -n {IP} services` | Check logs: `talosctl -n {IP} logs {service}` |
| Disk full | `talosctl -n {IP} get disks` | Clean up, check ephemeral partition |
| Network unreachable | `talosctl -n {IP} get addresses` | Verify VIP, check interface config |
| Kubelet not starting | `talosctl -n {IP} logs kubelet` | Check CNI, node taints |

**Log access:**
```bash
# System logs
talosctl -n {IP} dmesg --follow

# Service-specific logs
talosctl -n {IP} logs machined
talosctl -n {IP} logs kubelet
talosctl -n {IP} logs etcd
talosctl -n {IP} logs containerd

# Kernel messages
talosctl -n {IP} dmesg | grep -i error
```

**Interactive Dashboard:**

The Talos dashboard provides a real-time TUI for monitoring nodes:

```bash
# Launch dashboard for all nodes (default from talosconfig)
talosctl dashboard

# Launch for specific node(s)
talosctl dashboard -n 192.168.1.98
talosctl dashboard -n 192.168.1.98,192.168.1.99,192.168.1.100

# Custom update interval (default 3s)
talosctl dashboard -d 1s
```

**Dashboard screens:**
- **Summary** - Node overview: version, uptime, CPU/memory, processes
- **Monitor** - Real-time resource graphs and metrics
- **Network** - Interface status, IPs, traffic statistics
- **Processes** - Running processes with resource usage (like `top`)
- **Logs** - Live kernel/service logs (like `dmesg --follow`)

**Keyboard shortcuts:**

| Key | Action |
|-----|--------|
| `h` / `←` | Switch to previous node |
| `l` / `→` | Switch to next node |
| `j` / `↓` | Scroll down |
| `k` / `↑` | Scroll up |
| `Ctrl+d` | Scroll half page down |
| `Ctrl+u` | Scroll half page up |
| `Ctrl+f` | Scroll full page down |
| `Ctrl+b` | Scroll full page up |
| `q` | Quit dashboard |

**Quick access for this cluster:**
```bash
# All 3 control plane nodes
talosctl dashboard -n 192.168.1.98,192.168.1.99,192.168.1.100
```

---

## 2. Configuration Changes

**Project structure:**
```
talos/
├── talconfig.yaml          # Main config (nodes, network, versions)
├── talenv.yaml             # Version overrides (talosVersion, kubernetesVersion)
└── patches/
    ├── global/             # Applied to all nodes
    │   ├── machine-files.yaml
    │   ├── machine-kubelet.yaml
    │   ├── machine-network.yaml
    │   ├── machine-sysctls.yaml
    │   └── machine-time.yaml
    └── controller/         # Applied to control plane only
        └── cluster.yaml
```

**Workflow for config changes:**

1. **Edit the appropriate file:**
   - Node IPs, hostnames, disks → `talconfig.yaml`
   - Talos/K8s versions → `talenv.yaml` (if exists) or `talconfig.yaml`
   - System settings → `patches/global/*.yaml`
   - API server, etcd, scheduler → `patches/controller/cluster.yaml`

2. **Regenerate configs:**
   ```bash
   task talos:generate-config
   ```

3. **Review changes:**
   ```bash
   git diff talos/clusterconfig/
   ```

4. **Apply to node(s):**
   ```bash
   # Single node
   task talos:apply-node IP=192.168.1.98 MODE=auto

   # MODE options:
   # - auto: Automatically determine if reboot needed
   # - staged: Stage config, apply on next reboot
   # - no-reboot: Apply without reboot (limited changes only)
   ```

5. **Verify:**
   ```bash
   talosctl -n {IP} get machineconfig
   talosctl -n {IP} dmesg | tail -20
   ```

**Common configuration patterns:**

```yaml
# patches/global/machine-kubelet.yaml - Kubelet settings
machine:
  kubelet:
    extraConfig:
      serializeImagePulls: false
    nodeIP:
      validSubnets:
        - 192.168.1.0/24

# patches/controller/cluster.yaml - Control plane settings
cluster:
  allowSchedulingOnControlPlanes: true
  apiServer:
    extraArgs:
      enable-aggregator-routing: true
  coreDNS:
    disabled: true  # Using Cilium DNS
  proxy:
    disabled: true  # Using Cilium proxy replacement
```

---

## 3. System Extensions

**Current schematic (from talconfig.yaml):**
- Image URL format: `factory.talos.dev/installer/{SCHEMATIC_ID}`
- Current ID: `97bf8e92fc6bba0f03928b859c08295d7615737b29db06a97be51dc63004e403`

**Adding extensions:**

1. **Go to Image Factory:** https://factory.talos.dev

2. **Select Talos version** (match your `talosVersion`)

3. **Choose extensions:**
   - `siderolabs/iscsi-tools` - iSCSI storage support
   - `siderolabs/util-linux-tools` - Additional utilities
   - `siderolabs/qemu-guest-agent` - VM guest tools
   - `siderolabs/intel-ucode` - Intel microcode updates
   - `siderolabs/amd-ucode` - AMD microcode updates
   - `siderolabs/i915` - Intel GPU driver
   - `siderolabs/nvidia-container-toolkit` - NVIDIA GPU support
   - `siderolabs/tailscale` - Tailscale VPN
   - `siderolabs/zfs` - ZFS filesystem support

4. **Get new schematic ID** from Image Factory

5. **Update talconfig.yaml:**
   ```yaml
   nodes:
     - hostname: "k8s-1"
       talosImageURL: factory.talos.dev/installer/{NEW_SCHEMATIC_ID}
   ```

6. **Upgrade node to apply:**
   ```bash
   task talos:upgrade-node IP=192.168.1.98
   ```

**Verify installed extensions:**
```bash
talosctl -n {IP} get extensions
talosctl -n {IP} image list
```

---

## 4. Upgrade Planning

**Pre-upgrade checklist:**

- [ ] Check current versions: `talosctl -n {IP} version`
- [ ] Review release notes for breaking changes
- [ ] Verify etcd quorum: `talosctl -n {IP} etcd status`
- [ ] Check node health: `talosctl health`
- [ ] Backup etcd (optional): `talosctl -n {IP} etcd snapshot db.snapshot`
- [ ] Ensure cluster has capacity for rolling upgrade

**Kubernetes upgrade:**

1. **Update version in talenv.yaml (or talconfig.yaml):**
   ```yaml
   kubernetesVersion: "1.32.0"  # New version
   ```

2. **Run upgrade:**
   ```bash
   task talos:upgrade-k8s
   ```

3. **Verify:**
   ```bash
   kubectl get nodes
   kubectl version
   ```

**Talos upgrade:**

1. **Update version in talenv.yaml (or talconfig.yaml):**
   ```yaml
   talosVersion: "v1.9.0"  # New version
   ```

2. **Upgrade each node (one at a time):**
   ```bash
   # Control plane nodes first
   task talos:upgrade-node IP=192.168.1.98
   # Wait for Ready
   kubectl get nodes -w

   task talos:upgrade-node IP=192.168.1.99
   # Wait for Ready

   task talos:upgrade-node IP=192.168.1.100
   # Wait for Ready
   ```

3. **Verify:**
   ```bash
   talosctl -n 192.168.1.98 version
   ```

**Version compatibility matrix:**

| Talos Version | Supported K8s Versions |
|---------------|------------------------|
| v1.11.x | 1.32.x - 1.33.x |
| v1.10.x | 1.31.x - 1.32.x |
| v1.9.x | 1.31.x - 1.32.x |

**Current cluster versions:**
- Talos: v1.11.3
- talosctl (local): v1.9.3

---

## 5. Production Best Practices Audit

**Check these settings:**

| Category | Recommendation | Verify |
|----------|----------------|--------|
| **HA Control Plane** | 3+ control plane nodes | `talosctl get members` |
| **Etcd** | Advertised subnets configured | Check `cluster.etcd.advertisedSubnets` |
| **Metrics** | Bind addresses exposed | `0.0.0.0` for controller-manager, scheduler |
| **Time Sync** | NTP servers configured | Check `machine.time.servers` |
| **Network** | VIP for API endpoint | Check `vip.ip` in network config |
| **Disk Selection** | Deterministic selector | Use serial/wwid, not /dev/sdX |
| **Kubelet** | Node IP subnet restricted | Check `kubelet.nodeIP.validSubnets` |
| **Security** | RBAC enabled | Default in Talos |

**Security hardening (this cluster):**
- ✅ API server admission control configured
- ✅ Aggregation layer routing enabled
- ✅ kube-proxy disabled (Cilium replacement)
- ✅ CoreDNS disabled (Cilium DNS)
- ✅ Static network config (no DHCP)

**Recommended additions:**

```yaml
# Rotate server certificates automatically
machine:
  kubelet:
    extraConfig:
      serverTLSBootstrap: true

# Pod security standards
cluster:
  apiServer:
    admissionControl:
      - name: PodSecurity
        configuration:
          enforce: baseline
          audit: restricted
```

---

## Quick Reference

| Task | Command |
|------|---------|
| Interactive dashboard | `talosctl dashboard` |
| Check cluster health | `talosctl health -n 192.168.1.98 --control-plane-nodes 192.168.1.98,192.168.1.99,192.168.1.100` |
| View node config | `talosctl -n {IP} get machineconfig` |
| View dmesg | `talosctl -n {IP} dmesg` |
| Check services | `talosctl -n {IP} services` |
| Check etcd | `talosctl -n {IP} etcd status` |
| Regenerate configs | `task talos:generate-config` |
| Apply config | `task talos:apply-node IP={IP} MODE=auto` |
| Upgrade node | `task talos:upgrade-node IP={IP}` |
| Upgrade K8s | `task talos:upgrade-k8s` |
| Reset cluster | `task talos:reset` ⚠️ DESTRUCTIVE |

**This cluster's nodes:**
- k8s-1: 192.168.1.98 (control plane, etcd leader)
- k8s-2: 192.168.1.99 (control plane)
- k8s-3: 192.168.1.100 (control plane)
- VIP: 192.168.1.101 (API endpoint)

---

**Output format:**

Based on user's request, provide:
1. **Current state** - What's configured/running now
2. **Analysis** - Issues found or recommendations
3. **Action plan** - Specific commands to run
4. **Verification** - How to confirm success
