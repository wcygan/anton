# Kubernetes Operations Golden Rules

## CRITICAL: Never Delete Core Resources Without Confirmation

### Rule #1: NEVER Delete Flux Kustomizations Without Analysis

**What I Did Wrong:**
```bash
# FATAL MISTAKE - NEVER DO THIS
kubectl delete kustomization cluster-apps -n flux-system
```

**Why This Is Catastrophic:**
- Flux Kustomizations manage entire application stacks
- Deleting them triggers **pruning** - Flux removes all managed resources
- Can delete 100+ pods in seconds
- Recovery requires full cluster bootstrap

**Correct Approach:**
```bash
# 1. First, suspend the kustomization
flux suspend kustomization cluster-apps

# 2. Fix the issue (e.g., YAML errors)
vim kubernetes/apps/airflow/airflow/ks.yaml

# 3. Test the fix locally
kustomize build kubernetes/apps/

# 4. Resume the kustomization
flux resume kustomization cluster-apps
```

### Rule #2: Always Use Non-Destructive Debugging First

**Instead of deleting, try these in order:**

1. **Suspend and Resume**
   ```bash
   flux suspend kustomization <name>
   # Make fixes
   flux resume kustomization <name>
   ```

2. **Force Reconciliation**
   ```bash
   flux reconcile kustomization <name> --with-source
   ```

3. **Check Logs First**
   ```bash
   kubectl logs -n flux-system deployment/kustomize-controller
   flux logs --follow
   ```

4. **Delete Only Cached Resources**
   ```bash
   # Safe - only deletes cached helm chart
   kubectl delete helmchart -n flux-system <name>
   ```

### Rule #3: Understand Resource Ownership

**Critical Resources (NEVER delete without extreme caution):**
- `cluster-apps` - Manages ALL applications
- `cluster-meta` - Manages repositories and sources
- `flux-system` - Core GitOps kustomization
- Any namespace-level kustomization

**Safe to Delete/Recreate:**
- Individual HelmReleases
- Cached HelmCharts
- Individual pods (will be recreated)
- ConfigMaps/Secrets (if managed by Flux)

### Rule #4: Test Changes Locally First

**Before applying any fixes:**
```bash
# Test kustomize build
kustomize build kubernetes/apps/

# Validate YAML
kubectl apply --dry-run=client -f <file>

# Check with yamllint
yamllint kubernetes/apps/
```

### Rule #5: Use Git for All Changes

**Never use `kubectl apply` directly for Flux-managed resources:**
```bash
# WRONG
kubectl apply -f my-fix.yaml

# RIGHT
git add my-fix.yaml
git commit -m "fix: correct YAML error"
git push
flux reconcile kustomization cluster-apps
```

## Recovery Procedures

### If You Accidentally Delete a Critical Kustomization:

1. **Immediately recreate it:**
   ```bash
   flux create kustomization cluster-apps \
     --source=GitRepository/flux-system \
     --path="./kubernetes/apps" \
     --prune=true \
     --interval=1h
   ```

2. **Force reconciliation:**
   ```bash
   flux reconcile source git flux-system
   flux reconcile kustomization cluster-apps
   ```

3. **Monitor recovery:**
   ```bash
   watch -n 5 'kubectl get pods -A | wc -l'
   flux get all -A
   ```

### Common Build Errors and Safe Fixes:

1. **Duplicate YAML keys:**
   - Fix: Edit the file, remove duplicates
   - Never: Delete the managing kustomization

2. **Missing namespace:**
   - Fix: Create the namespace
   - Never: Delete the app kustomization

3. **SOPS decryption failure:**
   - Fix: Ensure sops-age secret exists
   - Never: Delete encrypted resources

## Pre-Operation Checklist

Before ANY destructive operation:

- [ ] Is this resource managed by Flux? (check for labels)
- [ ] What will be pruned if I delete this?
- [ ] Can I fix this without deletion?
- [ ] Have I tested the fix locally?
- [ ] Is there a suspend/resume alternative?

## The Golden Rule

> **When in doubt, SUSPEND don't DELETE**

Suspension is always reversible. Deletion often triggers cascading failures that require hours to recover from.