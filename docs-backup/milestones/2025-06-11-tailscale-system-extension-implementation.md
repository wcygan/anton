# Milestone: Tailscale System Extension Implementation

**Date**: 2025-06-11  
**Category**: Infrastructure  
**Status**: Planning

## Summary

Plan to implement Tailscale as a system extension on Talos Linux nodes to enable direct node-level access via Tailscale network. This complements the existing Tailscale Kubernetes Operator by providing infrastructure-level connectivity for cluster administration and recovery scenarios.

## Goals

- [ ] Create custom Talos installer with Tailscale system extension using Image Factory
- [ ] Configure Tailscale authentication and subnet routing for Kubernetes services
- [ ] Enable direct node access via Tailscale hostnames (k8s-1, k8s-2, k8s-3)
- [ ] Validate dual Tailscale setup (system extension + Kubernetes operator)
- [ ] Document new access patterns and emergency recovery procedures

## Implementation Details

### Components to Deploy
- Tailscale System Extension (siderolabs/tailscale:latest)
- Custom Talos installer with schematic ID: `4a0d65c669d46663f377e7161e50cfd570c401f26fd9e7bda34a0216b6f1922b`
- ExtensionServiceConfig for each node with authentication and routing

### Configuration Changes
- **Talos Image Factory**: Generate custom installer URL with Tailscale extension
- **talconfig.yaml**: Update `talosImageURL` for all nodes to new schematic
- **Extension Service Config**: Create patches for each node with:
  - `TS_AUTHKEY`: Tailscale authentication key
  - `TS_HOSTNAME`: Node-specific hostnames (k8s-1, k8s-2, k8s-3)
  - `TS_ROUTES=10.43.0.0/16`: Expose Kubernetes service subnet
  - `TS_DEST_IP`: Node IP addresses for routing
- **Node patches**: Add ExtensionServiceConfig to each node's patch directory

### Implementation Phases
1. **Image Factory Setup** (30 min): Generate custom installer with Tailscale extension
2. **Configuration Preparation** (20 min): Create auth keys and ExtensionServiceConfig patches
3. **Sequential Node Updates** (45 min): Apply new configurations one node at a time
4. **Validation & Testing** (30 min): Verify connectivity and subnet routing
5. **Documentation** (15 min): Update access patterns and recovery procedures

## Validation

### Tests to Perform
- Verify extension installation: `talosctl get extensionserviceconfigs`
- Test direct node access via Tailscale hostnames
- Validate Kubernetes service subnet routing (10.43.0.0/16)
- Confirm cluster administration via Tailscale network
- Test emergency recovery scenarios

### Success Metrics
- All 3 nodes accessible via Tailscale hostnames
- Kubernetes services reachable over Tailscale subnet routes
- Cluster administration possible from remote Tailscale clients
- No disruption to existing Tailscale Kubernetes Operator functionality

## Architecture Benefits

### What This Enables
- **Infrastructure Resilience**: Direct node access for emergency scenarios
- **Remote Administration**: Manage cluster via Tailscale from anywhere
- **Service Exposure**: Kubernetes services accessible over Tailscale network
- **Dual Coverage**: System-level + application-level Tailscale integration
- **Recovery Scenarios**: Cluster access even if Kubernetes pods are degraded

### Risk Mitigation
- **Sequential Rollout**: One node at a time to maintain cluster availability
- **Configuration Backup**: Preserve current configs before changes
- **Rollback Strategy**: Can revert to original installer images if needed
- **Validation Gates**: Ensure each node is healthy before proceeding to next

## Implementation Prerequisites

- Tailscale admin console access for generating auth keys
- Cluster availability during sequential node configuration updates
- Backup of current Talos configurations
- Understanding of both system extension and Kubernetes operator approaches

## References

- [Tailscale System Extension](https://github.com/siderolabs/extensions/tree/main/network/tailscale)
- [Talos System Extensions Guide](https://www.talos.dev/v1.10/talos-guides/configuration/system-extensions/)
- [Talos Image Factory](https://factory.talos.dev)
- [Josh Noll's Tailscale + Talos Guide](https://joshrnoll.com/creating-a-kubernetes-cluster-with-talos-linux-on-tailscale/)
- [Existing Tailscale K8s Operator Milestone](./2025-06-12-tailscale-kubernetes-operator-deployment.md)
- Generated Schematic (Need to verify it is compatible with, and an incremental change to, the current Talos configuration): `factory.talos.dev/installer/4a0d65c669d46663f377e7161e50cfd570c401f26fd9e7bda34a0216b6f1922b`