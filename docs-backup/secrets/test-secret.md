# Test Secret Setup Guide

This guide walks through setting up a basic test secret using 1Password + External Secrets Operator to validate the integration is working correctly.

## Prerequisites

- 1Password account with ability to create vaults
- External Secrets Operator v0.17.0+ running in cluster
- 1Password Connect deployed and healthy

## Step 1: Verify Current Setup

Check that External Secrets infrastructure is running:

```bash
# Check ESO deployment
kubectl get deployment -n external-secrets external-secrets
kubectl get deployment -n external-secrets onepassword-connect

# Check if connect token secret exists
kubectl get secret -n external-secrets onepassword-connect-token
```

## Step 2: 1Password Vault Setup

### 2.1 Create or Access Homelab Vault

1. **Login to 1Password** in your browser
2. **Navigate to your vaults** or create a new one called "Homelab"
3. **Note the vault name** - we'll use "Homelab" in this guide

### 2.2 Create Test Item

1. **Click "New Item"** in the Homelab vault
2. **Choose "Secure Note"** (or "Password" if you prefer)
3. **Fill in the details**:
   - **Title**: `test-secret`
   - **Add custom fields**:
     - Field name: `username`, Value: `test-user`
     - Field name: `password`, Value: `super-secret-password`
     - Field name: `api-key`, Value: `test-api-key-12345`
4. **Save the item**

### 2.3 Get Vault ID

You'll need the vault ID for the ClusterSecretStore configuration:

1. **In 1Password web interface**, go to your Homelab vault
2. **Look at the URL** - it will be something like: `https://my.1password.com/vaults/abcd1234efgh5678/allitems`
3. **Copy the vault ID** (the part between `/vaults/` and `/allitems`)
4. **Alternative**: Use vault name "Homelab" directly (we'll show both methods)

## Step 3: Create ClusterSecretStore

Create the ClusterSecretStore to connect to 1Password:

```yaml
# kubernetes/apps/external-secrets/onepassword-connect/app/clustersecretstore.yaml
apiVersion: external-secrets.io/v1
kind: ClusterSecretStore
metadata:
  name: onepassword-connect
spec:
  provider:
    onepassword:
      connectHost: http://onepassword-connect.external-secrets.svc.cluster.local:8080
      vaults:
        Homelab: 1  # Use vault name or replace with actual vault ID
      auth:
        secretRef:
          connectTokenSecretRef:
            name: onepassword-connect-token
            namespace: external-secrets
            key: token
```

## Step 4: Create Test Secret Resource

Create the test secret in the default namespace:

```yaml
# kubernetes/apps/default/test-secret/ks.yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app test-secret
  namespace: flux-system
spec:
  targetNamespace: default
  commonMetadata:
    labels:
      app.kubernetes.io/name: *app
  interval: 15m
  timeout: 5m
  prune: true
  wait: true
  path: ./kubernetes/apps/default/test-secret/app
  sourceRef:
    kind: GitRepository
    name: flux-system
    namespace: flux-system
  dependsOn:
    - name: external-secrets
      namespace: external-secrets
```

```yaml
# kubernetes/apps/default/test-secret/app/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - onepassworditem.yaml
```

```yaml
# kubernetes/apps/default/test-secret/app/onepassworditem.yaml
apiVersion: onepassword.com/v1
kind: OnePasswordItem
metadata:
  name: test-secret
  namespace: default
spec:
  itemPath: "vaults/Homelab/items/test-secret"
```

## Step 5: Deploy and Verify

### 5.1 Add to Default Namespace Kustomization

Update the default namespace kustomization to include our test secret:

```yaml
# kubernetes/apps/default/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: default
components:
  - ../../components/common
resources:
  - ./echo/ks.yaml
  - ./echo-2/ks.yaml
  - ./test-secret/ks.yaml  # Add this line
```

### 5.2 Commit and Deploy

```bash
# Commit changes
git add kubernetes/apps/default/test-secret/
git add kubernetes/apps/default/kustomization.yaml
git commit -m "feat: add test secret for 1Password integration testing"
git push

# Force reconciliation
flux reconcile source git flux-system
flux reconcile kustomization cluster-apps
```

### 5.3 Monitor Deployment

```bash
# Watch the kustomization
flux get kustomization -A | grep test-secret

# Check OnePasswordItem status
kubectl get onepassworditem -n default test-secret
kubectl describe onepassworditem -n default test-secret

# Check if secret was created
kubectl get secret -n default test-secret
```

## Step 6: Verify Secret Contents

```bash
# View secret data (base64 encoded)
kubectl get secret -n default test-secret -o yaml

# Decode specific fields
kubectl get secret -n default test-secret -o jsonpath='{.data.username}' | base64 -d && echo
kubectl get secret -n default test-secret -o jsonpath='{.data.password}' | base64 -d && echo
kubectl get secret -n default test-secret -o jsonpath='{.data.api-key}' | base64 -d && echo
```

## Step 7: Test with a Pod

Create a simple test pod that uses the secret:

```yaml
# test-pod.yaml (temporary file)
apiVersion: v1
kind: Pod
metadata:
  name: test-secret-pod
  namespace: default
spec:
  containers:
  - name: test
    image: busybox
    command: ["/bin/sh"]
    args: ["-c", "while true; do echo 'Username:' $USERNAME; echo 'API Key:' $API_KEY; sleep 30; done"]
    env:
    - name: USERNAME
      valueFrom:
        secretKeyRef:
          name: test-secret
          key: username
    - name: API_KEY
      valueFrom:
        secretKeyRef:
          name: test-secret
          key: api-key
  restartPolicy: Never
```

```bash
# Apply test pod
kubectl apply -f test-pod.yaml

# Check logs
kubectl logs -n default test-secret-pod

# Clean up
kubectl delete pod -n default test-secret-pod
rm test-pod.yaml
```

## Troubleshooting

### Common Issues

1. **OnePasswordItem not syncing**:
   ```bash
   # Check 1Password Connect logs
   kubectl logs -n external-secrets deployment/onepassword-connect
   
   # Check ESO logs
   kubectl logs -n external-secrets deployment/external-secrets
   ```

2. **ClusterSecretStore not ready**:
   ```bash
   kubectl describe clustersecretstore onepassword-connect
   ```

3. **Wrong vault ID or item path**:
   - Verify vault name/ID in 1Password
   - Ensure item name matches exactly (case-sensitive)
   - Check item path format: `vaults/VaultName/items/ItemName`

4. **Connect token issues**:
   ```bash
   # Verify token secret exists and has correct key
   kubectl get secret -n external-secrets onepassword-connect-token -o yaml
   ```

### Validation Commands

```bash
# Check all External Secrets resources
kubectl get secretstore,clustersecretstore,externalsecret,onepassworditem -A

# Check events for issues
kubectl get events -n default --sort-by='.lastTimestamp'
kubectl get events -n external-secrets --sort-by='.lastTimestamp'

# Force reconciliation
kubectl annotate onepassworditem -n default test-secret op.1password.io/sync="$(date)"
```

## Success Criteria

✅ ClusterSecretStore shows as Ready
✅ OnePasswordItem shows as Ready with successful sync
✅ Kubernetes Secret created in default namespace
✅ Secret contains expected data from 1Password
✅ Test pod can access secret values as environment variables

## Cleanup (Optional)

To remove the test secret:

```bash
# Delete from Git
git rm -r kubernetes/apps/default/test-secret/
# Remove line from kubernetes/apps/default/kustomization.yaml
git commit -m "chore: remove test secret"
git push

# Force reconciliation to clean up
flux reconcile kustomization cluster-apps
```

The OnePasswordItem and Secret will be automatically removed by Flux's prune functionality.