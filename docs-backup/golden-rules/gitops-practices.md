# GitOps Golden Rules

## Rule #1: All Changes Through Git

**NEVER apply changes directly to the cluster for Flux-managed resources.**

### Wrong Way:
```bash
# DON'T DO THIS
kubectl apply -f my-manifest.yaml
kubectl edit deployment my-app
kubectl patch helmrelease my-app --type=merge -p '{"spec":{"values":{...}}}'
```

### Right Way:
```bash
# Make changes in Git
vim kubernetes/apps/my-app/deployment.yaml
git add .
git commit -m "fix: update deployment image"
git push

# Let Flux sync
flux reconcile kustomization cluster-apps
```

## Rule #2: Respect the Sync Window

**Don't make cluster changes during active reconciliation.**

### Check Sync Status First:
```bash
# Check if reconciliation is in progress
flux get all -A | grep -v "True"

# Wait for current sync to complete
watch flux get ks -A
```

## Rule #3: Fix Build Errors in Git

**When you encounter build errors, fix them in the repository.**

### Common Build Errors:

1. **YAML Syntax Errors**
   ```bash
   # Validate locally
   yamllint kubernetes/apps/
   
   # Test kustomize build
   kustomize build kubernetes/apps/namespace/app/
   ```

2. **Duplicate Keys** (like our incident)
   ```yaml
   # WRONG - duplicate targetNamespace
   spec:
     targetNamespace: airflow
     # ... other fields ...
     targetNamespace: airflow  # DUPLICATE!
   ```

3. **Missing Dependencies**
   ```yaml
   # Check dependsOn references exist
   dependsOn:
     - name: external-secrets
       namespace: external-secrets  # Must match actual namespace
   ```

## Rule #4: Version Everything

**Pin versions for predictable deployments.**

### HelmRelease Versions:
```yaml
spec:
  chart:
    spec:
      version: "1.2.3"  # Always pin versions
      # NOT version: "*" or version: "^1.0.0"
```

### Image Tags:
```yaml
spec:
  containers:
  - image: nginx:1.21.6  # Pin to specific version
    # NOT image: nginx:latest
```

## Rule #5: Use Proper Dependencies

**Declare dependencies to ensure correct deployment order.**

### Kustomization Dependencies:
```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
spec:
  dependsOn:
    - name: cert-manager
      namespace: cert-manager  # Use actual namespace, not flux-system
```

## Rule #6: Handle Secrets Properly

**Never commit unencrypted secrets.**

### Using SOPS:
```bash
# Encrypt before committing
sops -e secret.yaml > secret.sops.yaml
git add secret.sops.yaml
# NEVER: git add secret.yaml
```

### Using External Secrets:
```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: app-secret
spec:
  secretStoreRef:
    name: onepassword-connect
    kind: ClusterSecretStore
```

## Rule #7: Monitor Flux Health

**Regularly check Flux components and sync status.**

### Health Checks:
```bash
# Overall health
flux check

# Sync status
flux get all -A

# Recent events
flux events

# Controller logs
flux logs --follow
```

## Rule #8: Backup Before Major Changes

**Create restore points before significant modifications.**

### Quick Backup:
```bash
# Export current state
kubectl get helmrelease -A -o yaml > backup-helmreleases.yaml
kubectl get kustomization -A -o yaml > backup-kustomizations.yaml

# Git tag for rollback
git tag -a "before-major-change" -m "Backup before X modification"
git push --tags
```

## Rule #9: Use Flux Alerts

**Set up alerts for failed reconciliations.**

### Example Alert:
```yaml
apiVersion: notification.toolkit.fluxcd.io/v1
kind: Alert
metadata:
  name: flux-system
  namespace: flux-system
spec:
  eventSeverity: error
  eventSources:
    - kind: Kustomization
      name: '*'
    - kind: HelmRelease
      name: '*'
  providerRef:
    name: discord  # or slack, webhook, etc.
```

## Rule #10: Document Flux Customizations

**Document any non-standard Flux configurations.**

### In CLAUDE.md or README:
```markdown
## Flux Customizations

- Using FluxInstance/Operator instead of flux bootstrap
- Custom SOPS age key location: `./age.key`
- Webhook enabled for push-based sync
- Resource limits set on controllers
```

## Recovery from GitOps Mistakes

### If You Applied Direct Changes:
```bash
# 1. Export current state
kubectl get <resource> -o yaml > current-state.yaml

# 2. Commit to Git
cp current-state.yaml kubernetes/apps/...
git add . && git commit -m "fix: sync manual changes"
git push

# 3. Force sync
flux reconcile kustomization cluster-apps --with-source
```

### If Sync Is Stuck:
```bash
# 1. Check what's failing
flux get all -A | grep False

# 2. Suspend problematic resource
flux suspend hr <name> -n <namespace>

# 3. Fix in Git, push, then resume
flux resume hr <name> -n <namespace>
```

## Remember

> **GitOps means Git is the source of truth. The cluster should reflect Git, not the other way around.**