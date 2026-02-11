---
name: create-secret
description: Create 1Password-backed External Secret for the cluster. Use when adding secrets, credentials, API keys, or sensitive configuration.
disable-model-invocation: true
argument-hint: <secret-name> <namespace>
allowed-tools: Read, Write, Grep, Glob, Bash(kubectl:*), Bash(op:*)
---

# Create External Secret

Creates a 1Password-backed ExternalSecret for the Anton cluster.

## Instructions

### 1. Gather Information

Required:
- **Secret name**: kebab-case (e.g., `app-credentials`)
- **Namespace**: Target namespace
- **1Password item**: Item name in 1Password vault

### 2. Verify 1Password Item Exists

```bash
# Check if 1Password CLI is available and item exists
op item get "<item-name>" --vault "anton" --format json 2>/dev/null | jq -r '.title' || echo "Item not found or op CLI unavailable"
```

### 3. Check Existing Secrets Setup

```bash
# Verify External Secrets Operator is running
kubectl get pods -n external-secrets -l app.kubernetes.io/name=external-secrets

# Check ClusterSecretStore
kubectl get clustersecretstore onepassword-connect -o jsonpath='{.status.conditions[0].status}'
```

### 4. Create ExternalSecret

**Key points from CLAUDE.md:**
- Use `apiVersion: external-secrets.io/v1` (NOT v1beta1)
- Field names are case-sensitive
- Reference the `onepassword-connect` ClusterSecretStore

### 5. Template

```yaml
---
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: {{SECRET_NAME}}
  namespace: {{NAMESPACE}}
spec:
  secretStoreRef:
    kind: ClusterSecretStore
    name: onepassword-connect
  target:
    name: {{SECRET_NAME}}
    creationPolicy: Owner
  data:
    - secretKey: {{K8S_SECRET_KEY}}
      remoteRef:
        key: {{1PASSWORD_ITEM_NAME}}/{{1PASSWORD_FIELD_NAME}}
```

### 6. Common Patterns

**Single credential:**
```yaml
data:
  - secretKey: password
    remoteRef:
      key: "my-app-credentials/password"
```

**Multiple fields:**
```yaml
data:
  - secretKey: username
    remoteRef:
      key: "my-app-credentials/username"
  - secretKey: password
    remoteRef:
      key: "my-app-credentials/password"
```

**Entire item as JSON:**
```yaml
dataFrom:
  - extract:
      key: "my-app-credentials"
```

### 7. Validate After Creation

```bash
# Check ExternalSecret status
kubectl get externalsecret {{SECRET_NAME}} -n {{NAMESPACE}}

# Verify Secret was created
kubectl get secret {{SECRET_NAME}} -n {{NAMESPACE}}

# Check for sync errors
kubectl describe externalsecret {{SECRET_NAME}} -n {{NAMESPACE}} | grep -A5 "Status:"
```

## Output

1. Created ExternalSecret manifest path
2. Verification commands
3. Troubleshooting tips if sync fails

## Example Usage

```
/create-secret grafana-admin-password monitoring
```
