# Upgrade Talos and Kubernetes

This guide outlines the process for upgrading Talos OS and Kubernetes versions
for your cluster.

**Key Principles:**

- **One Node at a Time for OS Upgrades:** Always upgrade the Talos OS on one
  node at a time. Wait for the node to successfully reboot, rejoin the cluster,
  and report as `Ready` before proceeding to the next. This maintains cluster
  stability, especially for control plane nodes.
- **Two-Phase Upgrade:** The process involves first upgrading the Talos OS on
  all nodes, and then upgrading the Kubernetes version across the cluster.
- **Configuration Regeneration:** After changing versions in
  `talos/talenv.yaml`, always regenerate the Talos machine configurations.
- **Staging vs. Upgrading:** `apply-node` stages changes without reboot;
  `upgrade-node` initiates the OS upgrade and reboot.

## Phase 1: Upgrade Talos OS

1. **Update Talos Version in `talos/talenv.yaml`:** Modify the `talosVersion` to
   your target version. For example, to upgrade to Talos v1.10.0:
   ```diff
   # renovate: datasource=docker depName=ghcr.io/siderolabs/installer
   - talosVersion: v1.9.1
   + talosVersion: v1.10.0
   # renovate: datasource=docker depName=ghcr.io/siderolabs/kubelet
   kubernetesVersion: v1.32.0
   ```

2. **Regenerate Talos Configuration:** This updates the machine configuration
   files based on the new Talos version.
   ```bash
   task talos:generate-config
   ```

3. **Apply Configuration to Each Node:** This step stages the configuration
   changes on each node but does _not_ perform the OS upgrade or reboot them.
   ```bash
   task talos:apply-node IP=192.168.1.98 MODE=auto
   task talos:apply-node IP=192.168.1.99 MODE=auto
   task talos:apply-node IP=192.168.1.100 MODE=auto
   ```
   You will see "Applied configuration without a reboot" for each.

   **Note:** `MODE=auto` applies the configuration without reboot. To apply and
   reboot immediately, use `MODE=reboot`:
   ```bash
   task talos:apply-node IP=192.168.1.98 MODE=reboot
   ```

   In general, I recommend using `MODE=auto` for all nodes.

4. **Upgrade Talos OS on Each Node (Sequentially):** This command initiates the
   actual OS upgrade. The node will download the new Talos image, install it,
   and reboot. Monitor each node's progress (e.g., using `talosctl dashboard` or
   `kubectl get nodes -w`).

   - Upgrade the first node:
     ```bash
     task talos:upgrade-node IP=192.168.1.98
     ```
     Wait for it to complete and be `Ready`.

   - Upgrade the second node:
     ```bash
     task talos:upgrade-node IP=192.168.1.99
     ```
     Wait for it to complete and be `Ready`.

   - Upgrade the third node:
     ```bash
     task talos:upgrade-node IP=192.168.1.100
     ```
     Wait for it to complete and be `Ready`.

## Phase 2: Upgrade Kubernetes Version

Once all nodes are successfully running the new Talos OS version:

1. **Update Kubernetes Version in `talos/talenv.yaml`:** Modify the
   `kubernetesVersion` to your target version. For example, to upgrade to
   Kubernetes v1.33.0 (ensure this version is compatible with your Talos OS
   version by checking the
   [Talos support matrix](https://www.talos.dev/v1.10/introduction/support-matrix/)):
   ```diff
   # renovate: datasource=docker depName=ghcr.io/siderolabs/installer
   talosVersion: v1.10.0 # Should reflect the version from Phase 1
   # renovate: datasource=docker depName=ghcr.io/siderolabs/kubelet
   - kubernetesVersion: v1.32.0 # Or your current version
   + kubernetesVersion: v1.33.0
   ```

2. **Regenerate Talos Configuration:** This updates machine configurations to
   prepare for the Kubernetes upgrade.
   ```bash
   task talos:generate-config
   ```

3. **Perform Kubernetes Upgrade:** This command orchestrates the Kubernetes
   upgrade across the cluster.
   ```bash
   task talos:upgrade-k8s
   ```
   Monitor the upgrade progress. This process is designed to be non-disruptive
   to workloads.

## Monitoring

You can monitor the state of your nodes and the cluster using:

```bash
# For a live dashboard of all nodes
talosctl dashboard --nodes 192.168.1.98,192.168.1.99,192.168.1.100

# Or if your talosconfig is set up for the cluster endpoint
talosctl dashboard

# To watch Kubernetes node status
kubectl get nodes -w
```

### Verification: Kubernetes Version

After the cluster upgrade completes, verify the Kubernetes version on each node:

```bash
kubectl version --short
kubectl get nodes -o wide
```
