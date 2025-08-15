# Tailscale System Extension Implementation

This guide covers implementing Tailscale as a system extension on Talos Linux nodes to enable infrastructure-level network access via Tailscale, complementing the existing Tailscale Kubernetes Operator.

## Overview

Tailscale system extension provides:
- **Infrastructure-level access**: Direct node connectivity independent of Kubernetes
- **Emergency recovery**: Cluster access when Kubernetes pods are degraded
- **Remote administration**: Manage cluster via Tailscale from anywhere
- **Service exposure**: Kubernetes services accessible over Tailscale network

## Prerequisites

- Tailscale account with admin access for generating auth keys
- Cluster running Talos Linux v1.10.0 or later
- Current system extensions documented (use `talosctl get extensions`)
- Backup of current Talos configurations

## Architecture

**Dual-Layer Setup**:
- **System Extension**: Infrastructure-level Tailscale (this guide)
- **Kubernetes Operator**: Application-level service exposure (separate deployment)

**Network Integration**:
- Subnet routing exposes Kubernetes service CIDR (10.43.0.0/16) over Tailscale
- Direct node access via Tailscale Magic DNS (k8s-1.tailnet.ts.net)
- Coexistence with existing Tailscale K8s operator

## Implementation Process

### Phase 1: Schematic Generation (15 minutes)

1. **Identify Current Extensions**
   ```bash
   talosctl get extensions -n 192.168.1.98
   ```
   Expected output shows current extensions (i915, mei, etc.) and schematic ID.

2. **Generate New Schematic**
   - Visit https://factory.talos.dev/
   - Configure:
     - **Version**: Match your current Talos version (e.g., v1.10.4)
     - **Architecture**: amd64
     - **Platform**: metal
     - **Extensions**: Include ALL current extensions + `siderolabs/tailscale`
   
   Example URL for Intel hardware:
   ```
   https://factory.talos.dev/?arch=amd64&cmdline-set=true&extensions=-&extensions=siderolabs%2Fi915&extensions=siderolabs%2Fmei&extensions=siderolabs%2Ftailscale&platform=metal&target=metal&version=1.10.4
   ```

3. **Record Schematic Information**
   The factory will generate:
   ```yaml
   customization:
       systemExtensions:
           officialExtensions:
               - siderolabs/i915
               - siderolabs/mei
               - siderolabs/tailscale
   ```
   **Critical**: Save the generated schematic ID (e.g., `e60b2867d93adc72270a9a6919deb41755ede46ea45e08a25df37bb5c3919593`)

### Phase 2: Authentication Preparation (10 minutes)

1. **Generate Tailscale Auth Keys**
   - Login to Tailscale admin console → Settings → Keys
   - Create auth key with:
     - **Reusable**: Yes
     - **Ephemeral**: Yes
     - **Tags**: `tag:k8s-node`, `tag:homelab`
     - **Expiration**: 90 days

2. **Create ExtensionServiceConfig Patches**
   Create node-specific patches for Tailscale configuration:

   **talos/patches/k8s-1/tailscale-extension.yaml**:
   ```yaml
   apiVersion: v1alpha1
   kind: ExtensionServiceConfig
   name: tailscale
   environment:
     - TS_AUTHKEY=tskey-auth-your-reusable-key-here
     - TS_HOSTNAME=k8s-1
     - TS_ROUTES=10.43.0.0/16
     - TS_DEST_IP=192.168.1.98
   ```

   **talos/patches/k8s-2/tailscale-extension.yaml**:
   ```yaml
   apiVersion: v1alpha1
   kind: ExtensionServiceConfig
   name: tailscale
   environment:
     - TS_AUTHKEY=tskey-auth-your-reusable-key-here
     - TS_HOSTNAME=k8s-2
     - TS_ROUTES=10.43.0.0/16
     - TS_DEST_IP=192.168.1.99
   ```

   **talos/patches/k8s-3/tailscale-extension.yaml**:
   ```yaml
   apiVersion: v1alpha1
   kind: ExtensionServiceConfig
   name: tailscale
   environment:
     - TS_AUTHKEY=tskey-auth-your-reusable-key-here
     - TS_HOSTNAME=k8s-3
     - TS_ROUTES=10.43.0.0/16
     - TS_DEST_IP=192.168.1.100
   ```

3. **Update Node Patch References**
   Add the ExtensionServiceConfig patches to each node's configuration in `talos/talconfig.yaml`:
   ```yaml
   nodes:
     - hostname: "k8s-1"
       # ... existing config ...
       patches:
         - "@./patches/k8s-1/tailscale-extension.yaml"
   ```

### Phase 3: Configuration Update (5 minutes)

1. **Update Schematic in talconfig.yaml**
   Replace the `talosImageURL` for all nodes:
   ```yaml
   # Before
   talosImageURL: factory.talos.dev/installer/064d2c892ac9a3a7da7fa550dbdd1516908bd9dfe355ad345ff4e9d8f8b34930
   
   # After
   talosImageURL: factory.talos.dev/installer/e60b2867d93adc72270a9a6919deb41755ede46ea45e08a25df37bb5c3919593
   ```

2. **Update Talos Version (if changed)**
   In `talos/talenv.yaml`:
   ```yaml
   talosVersion: v1.10.4  # Match the version used in schematic generation
   ```

3. **Regenerate Configuration**
   ```bash
   task talos:generate-config
   ```

### Phase 4: Sequential Node Deployment (45 minutes)

**Critical**: Update only ONE node at a time to maintain cluster availability.

1. **Backup Current Configuration**
   ```bash
   talosctl get machineconfig -n 192.168.1.98 > backup-k8s-1-config.yaml
   talosctl get machineconfig -n 192.168.1.99 > backup-k8s-2-config.yaml
   talosctl get machineconfig -n 192.168.1.100 > backup-k8s-3-config.yaml
   ```

2. **Verify Cluster Health Baseline**
   ```bash
   kubectl get nodes -o wide
   talosctl health
   ```

3. **Deploy to k8s-1**
   ```bash
   # Apply configuration
   task talos:apply-node IP=192.168.1.98 MODE=auto
   
   # Upgrade with new image
   talosctl upgrade -n 192.168.1.98 --image=factory.talos.dev/installer/e60b2867d93adc72270a9a6919deb41755ede46ea45e08a25df37bb5c3919593:v1.10.4
   ```

4. **Validate k8s-1 Before Proceeding**
   ```bash
   # Wait for node to complete reboot (60-90 seconds)
   sleep 90
   
   # Verify node is Ready
   kubectl get nodes k8s-1 -o wide
   
   # Check Tailscale extension loaded
   talosctl get extensions -n 192.168.1.98 | grep tailscale
   
   # Verify Tailscale connection
   talosctl get extensionserviceconfigs -n 192.168.1.98
   ```

5. **Deploy to k8s-2** (only after k8s-1 validation passes)
   ```bash
   task talos:apply-node IP=192.168.1.99 MODE=auto
   talosctl upgrade -n 192.168.1.99 --image=factory.talos.dev/installer/e60b2867d93adc72270a9a6919deb41755ede46ea45e08a25df37bb5c3919593:v1.10.4
   ```

6. **Validate k8s-2 Before Proceeding**
   ```bash
   sleep 90
   kubectl get nodes k8s-2 -o wide
   talosctl get extensions -n 192.168.1.99 | grep tailscale
   ```

7. **Deploy to k8s-3** (only after k8s-2 validation passes)
   ```bash
   task talos:apply-node IP=192.168.1.100 MODE=auto
   talosctl upgrade -n 192.168.1.100 --image=factory.talos.dev/installer/e60b2867d93adc72270a9a6919deb41755ede46ea45e08a25df37bb5c3919593:v1.10.4
   ```

8. **Final Validation**
   ```bash
   sleep 90
   kubectl get nodes -o wide
   talosctl health
   ```

### Phase 5: Connectivity Testing (15 minutes)

1. **Verify Nodes in Tailscale Admin Console**
   - Check that k8s-1, k8s-2, k8s-3 appear as connected devices
   - Confirm subnet routes (10.43.0.0/16) are advertised and approved

2. **Test Direct Node Access**
   ```bash
   # From external Tailscale device
   ping k8s-1.tailnet-name.ts.net
   ping k8s-2.tailnet-name.ts.net
   ping k8s-3.tailnet-name.ts.net
   
   # Test SSH access (if enabled)
   ssh root@k8s-1.tailnet-name.ts.net
   ```

3. **Test Kubernetes Service Routing**
   ```bash
   # Get a Kubernetes service IP
   kubectl get svc -A | grep ClusterIP
   
   # From external Tailscale device, test service access
   curl http://10.43.x.x:port  # Replace with actual service IP
   ```

4. **Verify Cluster Administration**
   ```bash
   # From external device with kubectl configured
   kubectl get nodes
   kubectl get pods -A
   ```

## Troubleshooting

### Extension Not Loading

**Symptoms**: `talosctl get extensions` doesn't show Tailscale extension

**Resolution**:
```bash
# Check if schematic includes Tailscale
talosctl get extensions -n <node> | grep schematic

# Verify ExtensionServiceConfig applied
talosctl get extensionserviceconfigs -n <node>

# Check extension service logs
talosctl logs service tailscale -n <node>
```

### Tailscale Connection Issues

**Symptoms**: Extension loads but node doesn't appear in Tailscale console

**Resolution**:
```bash
# Check auth key validity
talosctl logs service tailscale -n <node> | grep -i auth

# Verify ExtensionServiceConfig environment variables
talosctl get extensionserviceconfigs tailscale -n <node> -o yaml

# Check firewall rules (Talos should allow by default)
talosctl get addresses -n <node>
```

### Subnet Routing Not Working

**Symptoms**: Direct node access works but Kubernetes services unreachable

**Resolution**:
1. **Approve Routes in Tailscale Admin Console**
   - Go to Machines → Select node → Edit route settings
   - Approve 10.43.0.0/16 subnet route

2. **Enable Route Acceptance on Client**
   ```bash
   # On client device
   tailscale set --accept-routes
   ```

3. **Verify IP Forwarding**
   ```bash
   # Check on node
   talosctl get sysctl -n <node> | grep ip_forward
   ```

### Node Boot Issues

**Symptoms**: Node fails to boot after schematic upgrade

**Resolution**:
```bash
# Boot from original image for recovery
talosctl upgrade -n <node> --image=factory.talos.dev/installer/064d2c892ac9a3a7da7fa550dbdd1516908bd9dfe355ad345ff4e9d8f8b34930:v1.10.0

# Check node console/IPMI for boot errors
# Verify schematic includes all required extensions
```

## Operational Considerations

### Monitoring

Add monitoring for Tailscale connectivity:
```bash
# Check extension status
talosctl get extensions -n <node> | grep tailscale

# Monitor connection health
ping -c 3 k8s-1.tailnet-name.ts.net
```

### Security

1. **Regular Auth Key Rotation**
   - Set 90-day expiration on auth keys
   - Create automation for key rotation
   - Monitor key usage in Tailscale admin console

2. **ACL Configuration**
   Configure Tailscale ACLs to restrict access:
   ```json
   {
     "acls": [
       {
         "action": "accept",
         "src": ["tag:admin"],
         "dst": ["tag:k8s-node:*"]
       }
     ],
     "tagOwners": {
       "tag:k8s-node": ["your-email@domain.com"]
     }
   }
   ```

### Backup and Recovery

1. **Configuration Backup**
   ```bash
   # Save ExtensionServiceConfig patches
   cp -r talos/patches/*/tailscale-extension.yaml /path/to/backup/

   # Document schematic ID for recovery
   echo "e60b2867d93adc72270a9a6919deb41755ede46ea45e08a25df37bb5c3919593" > schematic-id.txt
   ```

2. **Rollback Procedure**
   ```bash
   # Revert to original schematic
   talosctl upgrade -n <node> --image=factory.talos.dev/installer/064d2c892ac9a3a7da7fa550dbdd1516908bd9dfe355ad345ff4e9d8f8b34930:v1.10.0
   
   # Remove ExtensionServiceConfig patches from talconfig.yaml
   # Regenerate and apply configuration
   ```

## Next Steps

After successful implementation:

1. **Update Documentation**
   - Update cluster access procedures to include Tailscale hostnames
   - Document emergency recovery using Tailscale access
   - Create runbooks for common Tailscale operations

2. **Automation Opportunities**
   - Automate auth key rotation
   - Monitor Tailscale connectivity in existing health checks
   - Integrate Tailscale status into cluster monitoring

3. **Consider Additional Features**
   - Exit node configuration for internet routing
   - Tailscale Kubernetes operator for application-level features
   - Cross-site connectivity for multi-cluster setups

## Related Documentation

- [Talos Cluster Upgrades](./cluster-upgrades.md) - General upgrade procedures
- [Talos Troubleshooting](./troubleshooting.md) - Common Talos issues
- [Golden Rules - Talos Infrastructure](../golden-rules/talos-infrastructure.md) - Safety guidelines
- [Tailscale Kubernetes Operator](../milestones/2025-06-12-tailscale-kubernetes-operator-deployment.md) - Application-level integration