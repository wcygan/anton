# Milestone: Tailscale System Extension Remote Access

**Date**: 2025-06-13  
**Category**: Infrastructure  
**Status**: Completed

## Summary

Successfully implemented Tailscale as a system extension on Talos Linux nodes to enable secure remote `talosctl` access via Tailscale network. This provides infrastructure-level networking that enables cluster administration from any Tailscale-connected device without exposing cluster management interfaces to the public internet.

## Goals

- [x] Deploy Tailscale as system extension on Talos Linux nodes
- [x] Configure TLS certificates to include Tailscale IPs for remote access
- [x] Implement secure auth key management with SOPS encryption
- [x] Enable remote `talosctl` commands via Tailscale network
- [x] Document complete implementation process and troubleshooting

## Implementation Details

### Components Deployed
- Talos Linux v1.10.4 with Tailscale system extension
- Custom Factory schematic: `e60b2867d93adc72270a9a6919deb41755ede46ea45e08a25df37bb5c3919593`
- Tailscale extension v1.84.0
- SOPS encryption for secure configuration management

### Configuration Changes
- Updated `talconfig.yaml` to include Tailscale IPs in certificate SANs
- Created per-node `ExtensionServiceConfig` patches with SOPS encryption
- Modified Talos image URL to use factory schematic with Tailscale extension
- Configured Tailscale with non-ephemeral auth keys for persistent nodes
- Set `TS_AUTH_ONCE=false` to enable proper re-authentication and `TS_EXTRA_ARGS` application

### Key Technical Insights
- **Certificate SANs Critical**: TLS certificates must include Tailscale IPs for remote `talosctl` access
- **TS_AUTH_ONCE Behavior**: Must be `false` to apply `TS_EXTRA_ARGS` and allow re-authentication
- **Non-Ephemeral Preferred**: Infrastructure nodes benefit from persistent Tailscale presence
- **SOPS Integration**: Automatic decryption during `talhelper genconfig` workflow

## Validation

### Tests Performed
- Remote `talosctl time` via Tailscale IP: ✅ Success
- Remote `talosctl version` via Tailscale IP: ✅ Success  
- TLS certificate validation: ✅ Tailscale IP (100.106.239.22) in SANs
- Network connectivity: ✅ Ping and port 50000 accessible via Tailscale
- Service restart resilience: ✅ ExtensionServiceConfig reapplication successful
- SOPS encryption/decryption: ✅ Secure auth key management verified

### Metrics
- k8s-1 Tailscale IP: `100.106.239.22`
- Certificate SANs: `[127.0.0.1, 192.168.1.101, 100.106.239.22]`
- Tailscale extension version: `1.84.0`
- Network latency via Tailscale: ~4-23ms ping times
- Remote command success rate: 100% for simple commands (time, version)

## Lessons Learned

### What Went Well
- **Certificate SAN approach**: Adding Tailscale IPs to machine certificate SANs solved remote access
- **SOPS workflow**: Automatic encryption/decryption integrated seamlessly with talhelper
- **System extension stability**: Tailscale runs reliably at system level, survives reboots
- **Security model**: Tagged devices and encrypted auth keys provide proper access control
- **Documentation approach**: Comprehensive docs captured all implementation details

### Challenges
- **Initial certificate issues**: Required research to understand TLS certificate validation requirements
- **TS_AUTH_ONCE confusion**: Behavior with `TS_EXTRA_ARGS` required experimentation to understand
- **Service restart behavior**: ExtensionServiceConfig changes sometimes require manual restart
- **Large command timeouts**: Data-heavy `talosctl` commands timeout over Tailscale tunnel
- **Node upgrade coordination**: Sequential upgrades needed to maintain cluster availability

### Resolutions
- **Certificate SANs**: Updated `talconfig.yaml` to include Tailscale IPs in certificate generation
- **TS_AUTH_ONCE=false**: Allows proper re-authentication and TS_EXTRA_ARGS application
- **Manual restart procedure**: Documented `talosctl patch mc` workflow for service restart
- **Timeout workaround**: Simple commands work; use direct IP for complex operations
- **Rollout strategy**: One node at a time with verification between steps

## Next Steps

- **Investigate timeout issue**: Research packet fragmentation/MTU issues with gRPC over Tailscale
- **Complete rollout**: Deploy to k8s-2 and k8s-3 with updated certificate configurations
- **Add node IPs**: Update certificate SANs for additional nodes' Tailscale IPs
- **Automation**: Consider automating certificate updates when new nodes join Tailscale
- **Monitoring**: Add health checks for Tailscale connectivity and extension status

## References

- [Tailscale System Extension Implementation Guide](../talos-linux/tailscale-integration.md)
- [Tailscale System Extension GitHub](https://github.com/siderolabs/extensions/tree/main/network/tailscale)
- [Talos Factory Schematic](https://factory.talos.dev/?arch=amd64&cmdline-set=true&extensions=siderolabs%2Fi915&extensions=siderolabs%2Fmei&extensions=siderolabs%2Ftailscale&platform=metal&target=metal&version=1.10.4)
- [Original Milestone Specification](2025-06-11-tailscale-system-extension-implementation.md)
- [Tailscale Containerboot Documentation](https://tailscale.com/kb/1282/docker)

## Configuration Artifacts

### Factory Schematic
```
Image: factory.talos.dev/installer/e60b2867d93adc72270a9a6919deb41755ede46ea45e08a25df37bb5c3919593:v1.10.4
Extensions: siderolabs/i915, siderolabs/mei, siderolabs/tailscale
```

### Certificate SANs Configuration
```yaml
additionalApiServerCertSans: &sans
  - "127.0.0.1"
  - "192.168.1.101"
  - "100.106.239.22"  # k8s-1 Tailscale IP
additionalMachineCertSans: *sans
```

### ExtensionServiceConfig Pattern
```yaml
apiVersion: v1alpha1
kind: ExtensionServiceConfig
name: tailscale
environment:
  - TS_AUTHKEY=[SOPS-ENCRYPTED]
  - TS_HOSTNAME=k8s-1
  - TS_ROUTES=10.43.0.0/16
  - TS_STATE_DIR=/var/lib/tailscale
  - TS_ACCEPT_DNS=true
  - TS_AUTH_ONCE=false
  - TS_EXTRA_ARGS=--accept-routes --advertise-exit-node=false
```

This milestone represents a successful implementation of secure, remote infrastructure management capabilities that significantly enhance operational flexibility while maintaining security best practices.