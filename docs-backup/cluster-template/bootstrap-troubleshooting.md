# Cluster Bootstrap Troubleshooting

This document outlines the successful resolution of a cluster bootstrap issue encountered during the initial setup of the Anton homelab cluster.

## Issue Summary

During the initial cluster bootstrap process, the `task bootstrap:apps` command failed with a CRD (Custom Resource Definition) download error for external-dns v0.17.0.

## Problem Details

### Error Message
```
2025-06-13T02:55:59Z ERROR Failed to apply CRDs crd="https://raw.githubusercontent.com/kubernetes-sigs/external-dns/refs/tags/v0.17.0/docs/sources/crd/crd-manifest.yaml"
task: Failed to run task "bootstrap:apps": exit status 1
```

### Root Cause Analysis

1. **Renovate Auto-Update**: The issue was introduced by a Renovate bot commit (`2fc0128`) that automatically updated external-dns from v0.16.1 to v0.17.0
2. **Missing CRD File**: Investigation revealed that the external-dns project removed the `crd-manifest.yaml` file in v0.17.0
3. **Broken URL**: The bootstrap script was trying to fetch a non-existent file, causing the bootstrap process to fail

### Investigation Process

1. **Git History Review**: 
   ```bash
   git log --oneline --follow scripts/bootstrap-apps.sh
   git show 2fc0128  # The problematic Renovate commit
   ```

2. **URL Validation**: 
   - v0.17.0 URL returned 404: `https://raw.githubusercontent.com/kubernetes-sigs/external-dns/refs/tags/v0.17.0/docs/sources/crd/crd-manifest.yaml`
   - v0.16.1 URL worked correctly: `https://raw.githubusercontent.com/kubernetes-sigs/external-dns/refs/tags/v0.16.1/docs/sources/crd/crd-manifest.yaml`

3. **Repository Structure Analysis**: 
   - Confirmed that external-dns v0.17.0 only contains example CRD files
   - The main CRD manifest was removed from the repository

## Resolution

### Solution Applied
Reverted the external-dns CRD URL to the working v0.16.1 version while maintaining the project structure and adding explanatory comments.

### Code Changes
**File**: `scripts/bootstrap-apps.sh`

**Before** (broken):
```bash
local -r crds=(
    # renovate: datasource=github-releases depName=prometheus-operator/prometheus-operator
    https://github.com/prometheus-operator/prometheus-operator/releases/download/v0.83.0/stripped-down-crds.yaml
    # renovate: datasource=github-releases depName=kubernetes-sigs/external-dns
    https://raw.githubusercontent.com/kubernetes-sigs/external-dns/refs/tags/v0.17.0/docs/sources/crd/crd-manifest.yaml
)
```

**After** (fixed):
```bash
local -r crds=(
    # renovate: datasource=github-releases depName=prometheus-operator/prometheus-operator
    https://github.com/prometheus-operator/prometheus-operator/releases/download/v0.83.0/stripped-down-crds.yaml
    # renovate: datasource=github-releases depName=kubernetes-sigs/external-dns
    # NOTE: Using v0.16.1 because v0.17.0 removed the CRD manifest file
    https://raw.githubusercontent.com/kubernetes-sigs/external-dns/refs/tags/v0.16.1/docs/sources/crd/crd-manifest.yaml
)
```

## Successful Bootstrap Results

### Infrastructure Deployed
After applying the fix, the bootstrap process completed successfully and deployed:

1. **Cilium CNI**: Container Network Interface enabling pod networking
   - 3 Cilium agents (one per node)
   - 1 Cilium operator
   - All nodes transitioned from `NotReady` to `Ready` state

2. **CoreDNS**: Cluster DNS service
   - 2 CoreDNS pods for high availability

3. **Cert-Manager**: Certificate management
   - cert-manager controller
   - cert-manager-cainjector
   - cert-manager-webhook

4. **Spegel**: Registry mirror
   - 3 Spegel pods (one per node) for container image caching

5. **Flux GitOps**: 
   - flux-operator for managing Flux lifecycle
   - flux-instance with core controllers (pending startup)

### Final Cluster State
```
NAME    STATUS   ROLES           AGE   VERSION
k8s-1   Ready    control-plane   20m   v1.33.1
k8s-2   Ready    control-plane   20m   v1.33.1
k8s-3   Ready    control-plane   20m   v1.33.1
```

All critical infrastructure pods running successfully in `kube-system`, `cert-manager`, and `flux-system` namespaces.

## Lessons Learned

1. **Renovate Monitoring**: While Renovate automation is valuable, breaking changes in upstream projects can cause deployment failures
2. **CRD Dependencies**: Not all projects maintain stable CRD manifest locations across versions
3. **Bootstrap Validation**: The bootstrap process should validate URL accessibility before attempting downloads
4. **Version Pinning Strategy**: Consider pinning critical infrastructure components to known-working versions

## Prevention Strategies

1. **Pre-Update Testing**: Test Renovate PRs in development environment before merging
2. **URL Validation**: Add URL existence checks to bootstrap scripts
3. **Fallback Mechanisms**: Implement fallback to previous working versions for critical dependencies
4. **Documentation**: Maintain clear documentation of working versions and their requirements

## Related Documentation

- [Talos Bootstrap Process](../talos-linux/bootstrap-guide.md)
- [Flux GitOps Setup](../flux/initial-configuration.md)
- [External-DNS Configuration](../network/external-dns-setup.md)

## Timeline

- **Initial Issue**: 2025-06-13 02:55:59Z - Bootstrap failed with CRD error
- **Investigation**: 2025-06-13 02:56:00Z - 03:00:00Z - Root cause analysis
- **Resolution**: 2025-06-13 03:00:52Z - Applied fix and successful bootstrap
- **Completion**: 2025-06-13 03:03:01Z - All infrastructure deployed and operational