# 1Password Connect Setup Guide

This guide covers the complete setup of 1Password Connect with External Secrets Operator for secret management in Kubernetes.

## Architecture Overview

1Password Connect provides a REST API bridge between your 1Password vaults and Kubernetes:

```
1Password Vault → 1Password Connect Server → External Secrets Operator → Kubernetes Secrets
```

## Prerequisites

- **External Secrets Operator v0.17.0+** (uses v1 API only, v1beta1 is removed)
- **1Password Account** with ability to create Connect servers
- **1Password Connect credentials** (credentials.json file, NOT just API token)
- **Helm 3.x** and **kubectl** installed locally

## How 1Password Integrates with External Secrets

### 1. Authentication Flow

1Password Connect requires two types of credentials:
- **Credentials File** (`1password-credentials.json`): Contains encrypted server authentication data
- **Access Token**: JWT token for API authentication

External Secrets Operator connects to 1Password Connect using:
```yaml
spec:
  provider:
    onepassword:
      connectHost: http://onepassword-connect.external-secrets.svc.cluster.local:8080
      vaults:
        <vault-name>: 1  # Maps vault name to ID
      auth:
        secretRef:
          connectTokenSecretRef:
            name: onepassword-connect-token
            namespace: external-secrets
            key: token
```

### 2. Secret Synchronization

External Secrets creates a pull-based sync:
1. ExternalSecret resources define what secrets to fetch
2. ESO polls 1Password Connect at defined intervals
3. Retrieved data is stored as native Kubernetes secrets
4. Secrets are automatically updated when source changes

## Setup Instructions

### Step 1: Generate 1Password Connect Credentials

1. Log into your 1Password account
2. Navigate to **Integrations** → **Secrets Automation**
3. Create a new Connect server
4. Download:
   - `1password-credentials.json` (server credentials)
   - Access token (save as text file)

### Step 2: Deploy 1Password Connect

Use the provided setup script:

```bash
./scripts/setup-1password-connect.ts \
  --credentials ~/Downloads/1password-credentials.json \
  --token ~/Downloads/1password-api-token.txt
```

Or deploy manually:

```bash
# Create namespace
kubectl create namespace external-secrets

# Add Helm repository
helm repo add 1password https://1password.github.io/connect-helm-charts
helm repo update

# Deploy with credentials
helm install connect 1password/connect \
  --namespace external-secrets \
  --set-file connect.credentials=1password-credentials.json \
  --set connect.serviceType=ClusterIP
```

### Step 3: Create ClusterSecretStore

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
        <your-vault-name>: 1  # Replace with your vault name
      auth:
        secretRef:
          connectTokenSecretRef:
            name: onepassword-connect-token
            namespace: external-secrets
            key: token
```

### Step 4: Create ExternalSecret Resources

Example ExternalSecret that syncs from 1Password:

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: app-secrets
  namespace: default
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: onepassword-connect
    kind: ClusterSecretStore
  target:
    name: app-secrets
    creationPolicy: Owner
  data:
    # Map each field individually
    - secretKey: database-url
      remoteRef:
        key: app-config        # Item name in 1Password
        property: database_url # Field name within the item
    - secretKey: api-key
      remoteRef:
        key: app-config
        property: api_key
```

## Common Patterns

### 1. Syncing All Fields from an Item

```yaml
spec:
  dataFrom:
    - extract:
        key: <item-name>
```

### 2. Syncing Specific Fields

```yaml
spec:
  data:
    - secretKey: <k8s-secret-key>
      remoteRef:
        key: <1password-item-name>
        property: <1password-field-name>
```

### 3. Using Different Vaults

Update ClusterSecretStore to include multiple vaults:

```yaml
spec:
  provider:
    onepassword:
      vaults:
        production: 1
        staging: 2
        development: 3
```

## Troubleshooting

### Common Issues

#### 1. "illegal base64 data" Error

**Cause**: Credentials file not properly base64 encoded for Helm  
**Solution**: Use the setup script or ensure proper encoding:
```bash
base64 -w 0 < 1password-credentials.json > credentials.b64
```

#### 2. ExternalSecret Shows "SecretSynced" but No Secret Created

**Cause**: Usually indicates authentication success but item not found  
**Debug Steps**:
```bash
# Check ExternalSecret status
kubectl describe externalsecret <name> -n <namespace>

# Check 1Password Connect logs
kubectl logs -n external-secrets deployment/onepassword-connect
```

#### 3. "ValidationFailed" on ClusterSecretStore

**Cause**: Connection or authentication issue  
**Check**:
- Vault name matches exactly (case-sensitive)
- Token secret exists and contains valid token
- Connect server is running and healthy

#### 4. Field Not Found Errors

**Cause**: Property name mismatch  
**Solution**: 
- Field names in 1Password are case-sensitive
- Custom fields use their label as property name
- Use 1Password CLI to verify field names:
  ```bash
  op item get <item-name> --vault <vault-name> --format json
  ```

### Debugging Commands

```bash
# Check 1Password Connect health
kubectl get pods -n external-secrets
kubectl logs -n external-secrets deployment/onepassword-connect

# Verify ClusterSecretStore
kubectl get clustersecretstore onepassword-connect
kubectl describe clustersecretstore onepassword-connect

# Check ExternalSecret sync status
kubectl get externalsecret -A
kubectl describe externalsecret <name> -n <namespace>

# Force resync
kubectl annotate externalsecret <name> -n <namespace> \
  force-sync=$(date +%s) --overwrite
```

## Important Notes

### API Version Requirements

**Always use v1 API** for External Secrets resources:
```yaml
apiVersion: external-secrets.io/v1  # NOT v1beta1
```

### Security Considerations

1. **Credentials Protection**: The 1password-credentials.json contains sensitive data
2. **Network Policies**: Consider restricting access to 1Password Connect
3. **RBAC**: Limit which namespaces can use the ClusterSecretStore
4. **Audit Logging**: 1Password provides audit logs for all access

### GitOps Considerations

The 1Password Connect credentials cannot be stored in Git. Options:
1. Use the setup script for initial deployment
2. Bootstrap credentials manually, manage everything else via GitOps
3. Store encrypted credentials using SOPS (for the credentials only)

## Migration from Other Secret Solutions

### From SOPS

1. Create equivalent items in 1Password
2. Deploy ExternalSecret resources
3. Update application references
4. Remove SOPS-encrypted files

### From Kubernetes Secrets

1. Extract existing secret data
2. Create 1Password items
3. Replace direct secrets with ExternalSecret resources

## Best Practices

1. **Use Specific Field Mapping**: Explicit field mapping is more maintainable than extract all
2. **Set Appropriate Refresh Intervals**: Balance between freshness and API usage
3. **Implement Secret Rotation**: Update secrets in 1Password, they auto-sync
4. **Monitor Sync Status**: Set up alerts for failed syncs
5. **Test in Non-Production First**: Verify field mappings before production use

## References

- [External Secrets 1Password Provider](https://external-secrets.io/latest/provider/1password-secrets-automation/)
- [1Password Connect Documentation](https://developer.1password.com/docs/connect/)
- [1Password Connect Helm Chart](https://github.com/1Password/connect-helm-charts)

## Testing the Setup Script

The setup script supports full lifecycle management of 1Password Connect. To verify your installation or test upgrades:

```bash
# Test uninstall/reinstall cycle
deno task 1p:uninstall
deno task 1p:install

# The script will:
# - Cleanly remove all 1Password Connect resources
# - Redeploy using credentials from ~/Downloads/ (or custom paths)
# - Recreate the ClusterSecretStore
# - Verify connectivity

# After reinstall, existing ExternalSecrets will automatically resync
```

This uninstall/reinstall cycle is useful for:
- Testing the setup script functionality
- Upgrading to new versions of 1Password Connect
- Troubleshooting connection issues
- Disaster recovery scenarios