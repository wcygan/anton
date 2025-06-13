# Tailscale Integration with Talos Linux

This document describes the implementation of Tailscale as a system extension on Talos Linux nodes to enable secure remote `talosctl` access via Tailscale network.

## Overview

### Objectives
- Enable remote `talosctl` management from any Tailscale-connected device
- Implement Tailscale at the system level (not just Kubernetes)
- Maintain security through proper certificate management and encrypted secrets
- Provide infrastructure-level networking for cluster administration

### Architecture Choice
We implemented Tailscale as a **system extension** rather than using the Kubernetes operator because:
- System-level access enables `talosctl` commands outside of Kubernetes
- Infrastructure networking that survives cluster restarts
- Direct node-to-node connectivity for administrative tasks
- Separation of infrastructure networking from application networking

## Implementation Overview

### Core Components
1. **Talos Factory Schematic**: Custom image with Tailscale extension
2. **Certificate SANs**: TLS certificates including Tailscale IPs
3. **ExtensionServiceConfig**: Tailscale configuration via SOPS-encrypted patches
4. **Auth Key Management**: Secure storage and deployment of Tailscale auth keys

### Key Files Modified
- `talos/talconfig.yaml`: Added Tailscale IPs to certificate SANs
- `talos/talenv.yaml`: Updated to Talos v1.10.4
- `talos/patches/k8s-*/tailscale-extension.sops.yaml`: SOPS-encrypted Tailscale configurations

## Step-by-Step Implementation

### 1. Create Factory Schematic

Generate a custom Talos image with the Tailscale extension:

**Factory URL**: https://factory.talos.dev/?arch=amd64&cmdline-set=true&extensions=siderolabs%2Fi915&extensions=siderolabs%2Fmei&extensions=siderolabs%2Ftailscale&platform=metal&target=metal&version=1.10.4

**Resulting Schematic ID**: `e60b2867d93adc72270a9a6919deb41755ede46ea45e08a25df37bb5c3919593`

### 2. Update Talos Configuration

#### Update `talenv.yaml`
```yaml
talosVersion: v1.10.4
kubernetesVersion: v1.33.1
```

#### Update `talconfig.yaml`
Add Tailscale IPs to certificate Subject Alternative Names:

```yaml
endpoint: https://192.168.1.101:6443
additionalApiServerCertSans: &sans
  - "127.0.0.1"
  - "192.168.1.101"
  # Tailscale IPs for remote talosctl access
  - "100.106.239.22"  # k8s-1 Tailscale IP
additionalMachineCertSans: *sans
```

#### Update Node Images
```yaml
nodes:
  - hostname: "k8s-1"
    # ... other config ...
    talosImageURL: factory.talos.dev/installer/e60b2867d93adc72270a9a6919deb41755ede46ea45e08a25df37bb5c3919593
    patches:
      - "@./patches/k8s-1/tailscale-extension.sops.yaml"
```

### 3. Create ExtensionServiceConfig

Create per-node Tailscale configuration patches. Example structure:

```yaml
apiVersion: v1alpha1
kind: ExtensionServiceConfig
name: tailscale
environment:
  - TS_AUTHKEY=[SOPS-ENCRYPTED-AUTH-KEY]
  - TS_HOSTNAME=k8s-1
  - TS_ROUTES=10.43.0.0/16
  - TS_STATE_DIR=/var/lib/tailscale
  - TS_ACCEPT_DNS=true
  - TS_AUTH_ONCE=false
  - TS_EXTRA_ARGS=--accept-routes --advertise-exit-node=false
```

#### Key Environment Variables
- `TS_AUTHKEY`: Non-ephemeral auth key for persistent nodes
- `TS_HOSTNAME`: Node identifier in Tailscale network
- `TS_ROUTES`: Advertise Kubernetes service subnet (optional)
- `TS_STATE_DIR`: Persistent state directory
- `TS_ACCEPT_DNS`: Enable Tailscale DNS
- `TS_AUTH_ONCE=false`: Allow re-authentication and apply TS_EXTRA_ARGS
- `TS_EXTRA_ARGS`: Additional Tailscale configuration flags

### 4. Secure Auth Key Management

#### Generate Tailscale Auth Key
1. Go to Tailscale admin console
2. Create new auth key with:
   - **Reusable**: Yes (for multiple node restarts)
   - **Ephemeral**: No (for persistent nodes)
   - **Preauthorized**: Yes
   - **Tags**: Add `tag:k8s-node` for organization

#### SOPS Encryption
```bash
# Create unencrypted config file
cat > talos/patches/k8s-1/tailscale-extension.sops.yaml << EOF
[configuration content]
EOF

# Encrypt with SOPS
sops -e -i talos/patches/k8s-1/tailscale-extension.sops.yaml
```

### 5. Deployment Process

#### Generate Updated Configurations
```bash
# Generate new machine configs with updated certificates
task talos:generate-config
```

#### Apply to First Node
```bash
# Apply updated configuration
talosctl apply-config -n 192.168.1.98 -f clusterconfig/anton-k8s-1.yaml

# Apply ExtensionServiceConfig patch
talosctl patch mc --patch @talos/patches/k8s-1/tailscale-extension.sops.yaml -n 192.168.1.98
```

#### Verify Installation
```bash
# Check extension status
talosctl -n 192.168.1.98 get ExtensionStatus

# Monitor Tailscale logs
talosctl -n 192.168.1.98 logs ext-tailscale --tail 20

# Verify Tailscale connectivity
ping 100.106.239.22
tailscale status
```

## Configuration Details

### Certificate Management
The critical insight was adding Tailscale IPs to the TLS certificate SANs. Without this:
- `talosctl` commands over Tailscale fail with certificate validation errors
- The certificate only includes local network IPs by default

**Verification**:
```bash
# Check certificate SANs
echo | openssl s_client -connect 100.106.239.22:50000 -servername 100.106.239.22 2>/dev/null | openssl x509 -noout -text | grep -A5 "Subject Alternative Name"
```

### Tailscale Configuration Insights

#### TS_AUTH_ONCE Behavior
- `TS_AUTH_ONCE=true`: Preserves state across restarts but ignores `TS_EXTRA_ARGS`
- `TS_AUTH_ONCE=false`: Allows re-authentication and applies all configuration

#### Non-Ephemeral Nodes
Research showed that for infrastructure nodes, non-ephemeral auth keys are preferred over ephemeral ones, despite ephemeral being common for containerized workloads.

## Troubleshooting

### Common Issues

#### 1. Service Not Starting
```bash
# Check extension status
talosctl -n <node> get ExtensionStatus tailscale -o yaml

# View logs for errors
talosctl -n <node> logs ext-tailscale
```

#### 2. Certificate Validation Errors
Ensure Tailscale IP is in certificate SANs:
```bash
# Verify certificate includes Tailscale IP
openssl s_client -connect <tailscale-ip>:50000 -servername <tailscale-ip> 2>/dev/null | openssl x509 -noout -text | grep "IP Address"
```

#### 3. Service Restart After Config Changes
ExtensionServiceConfig changes may require manual restart:
```bash
# Reapply configuration
talosctl patch mc --patch @talos/patches/k8s-*/tailscale-extension.sops.yaml -n <node>
```

#### 4. Network Connectivity
```bash
# Test basic connectivity
ping <tailscale-ip>

# Test Talos API port
nc -v -z -w 5 <tailscale-ip> 50000

# Check Tailscale status
tailscale status
```

### Debug Commands

#### Extension Status
```bash
# List all extensions
talosctl -n <node> get ExtensionStatus

# Detailed extension info
talosctl -n <node> get ExtensionStatus <id> -o yaml
```

#### Tailscale Logs
```bash
# Recent logs
talosctl -n <node> logs ext-tailscale --tail 50

# Follow logs
talosctl -n <node> logs ext-tailscale -f
```

#### Network Verification
```bash
# Check machine config
talosctl -n <node> get MachineConfig

# Verify certificate SANs
talosctl -n <node> get MachineConfig v1alpha1 -o yaml | grep -A10 certSANs
```

## Current Implementation Status

### Completed (k8s-1)
- ✅ Talos v1.10.4 with Tailscale extension installed
- ✅ Certificate SANs updated to include Tailscale IP (100.106.239.22)
- ✅ ExtensionServiceConfig deployed with proper configuration
- ✅ Tailscale service running and connected to network
- ✅ Network connectivity verified (ping and port 50000 accessible)

### In Progress
- 🔄 Investigating `talosctl` connection timeout via Tailscale
- 🟡 Rolling out to k8s-2 and k8s-3 with updated configurations

### Next Steps
1. **Debug Connection Timeout**: Investigate why `talosctl` commands timeout despite network connectivity
2. **Complete Rollout**: Apply configurations to remaining nodes (k8s-2, k8s-3)
3. **Add Future Node IPs**: Update certificate SANs for k8s-2 and k8s-3 Tailscale IPs
4. **Documentation**: Update milestone documentation with final results

## Security Considerations

### Best Practices Implemented
- **SOPS Encryption**: All auth keys encrypted before committing to Git
- **Non-Ephemeral Keys**: Reusable auth keys for infrastructure stability
- **Tagged Devices**: `tag:k8s-node` for ACL management
- **Certificate Validation**: Proper TLS certificate SANs for secure connections

### Security Notes
- Auth keys are stored encrypted and never committed in plaintext
- Tailscale IPs are safe to include in public configurations
- Certificate SANs only enable validation, not access
- Access control managed through Tailscale ACLs and device authorization

## References

### Documentation Used
- [Tailscale System Extension GitHub](https://github.com/siderolabs/extensions/tree/main/network/tailscale)
- [Talos Linux Factory](https://factory.talos.dev/)
- [Tailscale Containerboot Documentation](https://tailscale.com/kb/1282/docker)
- Research findings on Tailscale + Talos Linux usage patterns

### Key Discoveries
- **Certificate SANs Critical**: Main blocker for remote `talosctl` access
- **TS_AUTH_ONCE Behavior**: Must be `false` to apply `TS_EXTRA_ARGS`
- **Extension Restart Behavior**: Config changes may require manual service restart
- **SOPS Integration**: Automatic decryption during `talhelper genconfig`

This implementation provides the foundation for secure, remote Talos cluster management via Tailscale while maintaining proper security practices and infrastructure separation.