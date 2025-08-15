# Cluster Template Documentation

This directory contains documentation specific to the cluster template bootstrap process, troubleshooting guides, and operational procedures for the Anton homelab cluster.

## Overview

The Anton homelab cluster is based on the [onedr0p/cluster-template](https://github.com/onedr0p/cluster-template) and implements a production-grade Kubernetes cluster running on Talos Linux with Flux GitOps.

## Documentation Index

### Bootstrap Process
- **[Successful Bootstrap Checklist](./successful-bootstrap-checklist.md)** - Comprehensive verification steps for cluster bootstrap
- **[Bootstrap Troubleshooting](./bootstrap-troubleshooting.md)** - Real-world troubleshooting case study and resolution

### Key Learning Documents

#### Bootstrap Troubleshooting Case Study
Documents the resolution of a critical bootstrap failure caused by external-dns v0.17.0 CRD incompatibility. Key takeaways:

- **Issue**: Renovate auto-update broke external-dns CRD URL (v0.16.1 → v0.17.0)
- **Root Cause**: Upstream project removed CRD manifest file in newer version
- **Resolution**: Reverted to working v0.16.1 CRD URL with documentation
- **Prevention**: Better validation and testing of dependency updates

#### Successful Bootstrap Verification
Provides step-by-step verification process based on successful deployment:

- Pre-bootstrap node state validation
- Namespace and secret deployment verification  
- CRD and Helm release confirmation
- Post-bootstrap infrastructure health checks
- GitOps readiness confirmation

## Architecture Overview

### Technology Stack
- **OS**: Talos Linux (immutable, API-driven)
- **Orchestration**: Kubernetes v1.33.1
- **GitOps**: Flux v2.5.1 with hierarchical Kustomizations
- **CNI**: Cilium in kube-proxy replacement mode
- **DNS**: CoreDNS with custom configuration
- **Certificates**: cert-manager for automated TLS
- **Registry**: Spegel for container image caching

### Cluster Configuration
- **Nodes**: 3x MS-01 mini PCs (k8s-1, k8s-2, k8s-3)
- **Role**: All nodes configured as control-plane (highly available)
- **Networking**: Cilium mesh with pod-to-pod encryption
- **Storage**: Local path provisioner with plans for Rook-Ceph

## Bootstrap Process Summary

The bootstrap process follows a specific sequence designed for reliability:

1. **Talos Installation**: `task bootstrap:talos`
   - Deploys Talos Linux configuration
   - Establishes Kubernetes control plane
   - Nodes remain `NotReady` (expected without CNI)

2. **Core Services Deployment**: `task bootstrap:apps`
   - Creates required namespaces
   - Applies SOPS-encrypted secrets
   - Installs Custom Resource Definitions (CRDs)
   - Deploys Helm releases for core infrastructure

3. **Infrastructure Activation**:
   - Cilium CNI enables pod networking
   - Nodes transition to `Ready` state
   - Flux begins GitOps synchronization

## Critical Success Factors

### Working Configuration
The current deployment represents a known-good configuration with:
- Tested CRD URLs and versions
- Validated Helm chart combinations
- Proven infrastructure component compatibility

### Key Dependencies
- **External-DNS CRDs**: Currently pinned to v0.16.1 due to v0.17.0 incompatibility
- **Prometheus Operator**: v0.83.0 CRDs working correctly
- **Flux**: v0.20.0 operator and instance deployment

### GitOps Readiness
- All infrastructure deployed via declarative configuration
- Flux controllers ready to sync Git repository state
- Automated reconciliation of desired vs actual state

## Operational Guidelines

### Monitoring Bootstrap Health
Use the provided verification checklist to ensure each phase completes successfully:
- Node readiness progression
- Pod deployment and health status
- Service availability and networking
- GitOps controller functionality

### Troubleshooting Approach
1. **Identify the failing component** using kubectl and logs
2. **Check recent changes** in Git history and Renovate updates
3. **Validate upstream dependencies** for breaking changes
4. **Apply targeted fixes** rather than broad workarounds
5. **Document solutions** for future reference

### Maintenance Practices
- Monitor Renovate PRs for potential breaking changes
- Test updates in non-production environments first
- Maintain documentation of working configurations
- Keep troubleshooting guides updated with real issues

## Integration with Homelab

This cluster template forms the foundation for the broader Anton homelab infrastructure:

- **GitOps Management**: All applications deployed via Flux
- **Monitoring Stack**: Prometheus, Grafana, and alerting
- **Storage Layer**: Rook-Ceph for persistent workloads  
- **Networking**: Cilium with Cloudflare tunnel integration
- **Security**: cert-manager and external-secrets-operator

## Contributing

When updating this documentation:
1. Base content on real operational experience
2. Include specific commands and expected outputs
3. Document both successful and failure scenarios
4. Maintain troubleshooting guides with actual solutions
5. Keep checklists current with infrastructure changes

## Related Documentation

- **[Main Project README](../../README.md)** - Complete setup instructions
- **[CLAUDE.md](../../CLAUDE.md)** - Project-specific development guidelines
- **[Talos Documentation](../talos-linux/)** - OS-specific operations
- **[Flux Documentation](../flux/)** - GitOps workflows and troubleshooting
- **[Golden Rules](../golden-rules/)** - Critical operational guidelines

---

*Last Updated: 2025-06-13 - Based on successful bootstrap of Anton cluster v1.33.1*