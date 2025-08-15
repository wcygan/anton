# 1Password + External Secrets Setup Guide

## Overview

This document outlines the current state and required steps to complete the implementation of 1Password + External Secrets Operator for secret management in the Anton homelab cluster.

## Current Status (January 2025)

### ✅ Infrastructure Deployed

The following components are successfully deployed and running:

1. **External Secrets Operator (ESO)**
   - Version: `0.17.0`
   - Namespace: `external-secrets`
   - Components:
     - `external-secrets` (main controller)
     - `external-secrets-cert-controller`
     - `external-secrets-webhook`
   - All 21 CRDs installed
   - Status: Healthy and reconciling

2. **1Password Connect**
   - Version: `1.17.0`
   - Namespace: `external-secrets`
   - Components:
     - `connect-api` container (v1.7.3)
     - `connect-sync` container (v1.7.3)
   - CRD: `onepassworditems.onepassword.com` installed
   - Status: Healthy and running

### ❌ Not Yet Implemented

- No `SecretStore` or `ClusterSecretStore` configured
- No `OnePasswordItem` resources created
- No `ExternalSecret` resources defined
- 0 secrets synced from 1Password to Kubernetes

### 📊 Current Secret Management

**SOPS-encrypted secrets (deprecated):** 6 files
- `/kubernetes/apps/cert-manager/cert-manager/app/secret.sops.yaml`
- `/kubernetes/apps/flux-system/flux-instance/app/secret.sops.yaml`
- `/kubernetes/apps/network/external/cloudflared/secret.sops.yaml`
- `/kubernetes/apps/network/external/external-dns/secret.sops.yaml`
- `/kubernetes/components/common/cluster-secrets.sops.yaml`
- `/kubernetes/components/common/sops-age.sops.yaml`

**Total secrets in cluster:** 117 (excluding default tokens)

## Setup Requirements

### Prerequisites

1. **1Password Account Setup**
   - [ ] Create "Homelab" vault in 1Password
   - [ ] Generate Connect Server credentials
   - [ ] Create service account with vault access

2. **Connect Token Secret**
   - [ ] Store Connect token in cluster (already exists as `onepassword-connect-token`)

## Implementation Steps

### Step 1: Create ClusterSecretStore

Create `kubernetes/apps/external-secrets/onepassword-connect/app/clustersecretstore.yaml`:

```yaml
apiVersion: external-secrets.io/v1
kind: ClusterSecretStore
metadata:
  name: onepassword-connect
spec:
  provider:
    onepassword:
      connectHost: http://onepassword-connect.external-secrets.svc.cluster.local:8080
      vaults:
        Homelab: 1  # Replace with your vault ID
      auth:
        secretRef:
          connectTokenSecretRef:
            name: onepassword-connect-token
            namespace: external-secrets
            key: token
```

### Step 2: Test with Non-Critical Secret

Create a test secret in 1Password and sync it:

```yaml
apiVersion: onepassword.com/v1
kind: OnePasswordItem
metadata:
  name: test-secret
  namespace: default
spec:
  itemPath: "vaults/Homelab/items/test-secret"
```

Verify sync:
```bash
kubectl get secret test-secret -n default
kubectl describe onepassworditem test-secret -n default
```

### Step 3: Migration Plan

#### Phase 1: Low-Risk Secrets
- [ ] Create items in 1Password for non-critical services
- [ ] Deploy OnePasswordItem resources
- [ ] Verify sync and application functionality
- [ ] Remove SOPS versions

#### Phase 2: Critical Infrastructure
Migrate in this order:
1. [ ] External DNS credentials
2. [ ] Cert-Manager API keys
3. [ ] Cloudflare tunnel token
4. [ ] Flux GitHub credentials
5. [ ] Core cluster secrets

#### Phase 3: Cleanup
- [ ] Remove all `*.sops.yaml` files
- [ ] Remove `age.key` from repository
- [ ] Update documentation

## Migration Templates

### For Simple Key-Value Secrets

```yaml
apiVersion: onepassword.com/v1
kind: OnePasswordItem
metadata:
  name: <secret-name>
  namespace: <namespace>
spec:
  itemPath: "vaults/Homelab/items/<item-name>"
```

### For Complex Secrets with Multiple Keys

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: <secret-name>
  namespace: <namespace>
spec:
  secretStoreRef:
    name: onepassword-connect
    kind: ClusterSecretStore
  target:
    name: <secret-name>
    creationPolicy: Owner
  data:
    - secretKey: api-key
      remoteRef:
        key: <item-name>
        property: api_key
    - secretKey: api-secret
      remoteRef:
        key: <item-name>
        property: api_secret
```

## Monitoring and Validation

### Check Sync Status

```bash
# View all OnePasswordItems
kubectl get onepassworditem -A

# View all ExternalSecrets
kubectl get externalsecret -A

# Check sync status
kubectl describe onepassworditem <name> -n <namespace>

# View events
kubectl get events -n external-secrets --field-selector reason=SecretSynced
```

### Troubleshooting

**Common Issues:**

1. **Sync failures**
   - Check 1Password Connect logs: `kubectl logs -n external-secrets deployment/onepassword-connect`
   - Verify vault permissions
   - Ensure item path is correct

2. **Connection errors**
   - Verify ClusterSecretStore configuration
   - Check network connectivity to Connect server
   - Validate Connect token

3. **Missing secrets**
   - Ensure 1Password item exists
   - Check field names match
   - Verify namespace is correct

## Security Considerations

1. **Access Control**
   - 1Password Connect only has access to specified vaults
   - Use RBAC to limit which namespaces can create OnePasswordItems
   - Regular audit of synced secrets

2. **High Availability**
   - 1Password Connect runs as a single replica
   - Consider backup access methods during outages
   - Monitor sync status and alerts

3. **Secret Rotation**
   - Update secrets in 1Password UI
   - Sync happens automatically (default: 1 minute)
   - Applications should handle secret rotation gracefully

## Benefits of Migration

1. **Centralized Management**: All secrets in 1Password UI
2. **Better Audit Trail**: Who accessed what and when
3. **Easier Rotation**: Update in one place, syncs everywhere
4. **Team Collaboration**: Share vault access with team members
5. **No Keys in Repo**: Remove age.key and SOPS complexity

## Timeline Estimate

- **Week 1**: Setup and test with non-critical secrets
- **Week 2**: Migrate first batch of production secrets
- **Week 3**: Complete migration of remaining secrets
- **Week 4**: Cleanup and documentation

## Success Criteria

- [ ] All SOPS secrets migrated to 1Password
- [ ] No `*.sops.yaml` files in repository
- [ ] All applications using 1Password-synced secrets
- [ ] Monitoring and alerting configured
- [ ] Team trained on new process
- [ ] Documentation updated

## Next Actions

1. **Immediate**: Verify 1Password vault setup and access
2. **This Week**: Create ClusterSecretStore and test sync
3. **Next Sprint**: Begin phased migration of secrets

## References

- [External Secrets 1Password Provider](https://external-secrets.io/latest/provider/1password-secrets-automation/)
- [1Password Connect Documentation](https://developer.1password.com/docs/connect/)
- [1Password Kubernetes Operator](https://github.com/1Password/onepassword-operator)
- Internal docs: `/kubernetes/apps/external-secrets/README.md` (if exists)