---
description: Quick GitOps health check - Flux sync status and recent errors
---

Provide a quick health overview of the Flux GitOps system in the cluster.

**Run these checks in parallel:**

1. **Git source status:**
   ```bash
   kubectl get gitrepository -A -o wide
   ```

2. **Kustomization status (failures only first, then all):**
   ```bash
   kubectl get kustomizations -A -o wide | grep -v "True"
   kubectl get kustomizations -A -o wide
   ```

3. **HelmRelease status (failures only first, then all):**
   ```bash
   kubectl get helmreleases -A -o wide | grep -v "True"
   kubectl get helmreleases -A -o wide
   ```

4. **OCI/Helm repository status:**
   ```bash
   kubectl get ocirepositories -A -o wide | head -20
   kubectl get helmrepositories -A -o wide
   ```

5. **Recent Flux events (errors/warnings):**
   ```bash
   kubectl get events -n flux-system --sort-by='.lastTimestamp' | tail -15
   ```

6. **Flux controllers health:**
   ```bash
   kubectl get pods -n flux-system
   ```

**Output format:**

### Flux Health Summary

| Component | Status | Details |
|-----------|--------|---------|
| Git Source | ✅/❌ | Last sync time, revision |
| Kustomizations | X/Y healthy | List any failures |
| HelmReleases | X/Y healthy | List any failures |
| Controllers | ✅/❌ | Pod status |

### Issues Found

For each issue:
- **Resource:** namespace/name
- **Status:** Current state
- **Message:** Error or warning message
- **Suggestion:** How to investigate/fix

### Quick Actions

Based on findings, suggest:
- `kubectl describe ks -n {ns} {name}` for failed Kustomizations
- `kubectl describe hr -n {ns} {name}` for failed HelmReleases
- `kubectl logs -n flux-system deploy/source-controller` for source issues
- Force reconcile: `kubectl annotate gitrepository flux-system -n flux-system reconcile.fluxcd.io/requestedAt="$(date +%s)" --overwrite`

### Recent Activity

Show last 5 successful reconciliations with timestamps to confirm GitOps is actively syncing.

**If everything healthy:**
```
✅ Flux is healthy
- Git: synced to {revision} at {time}
- Kustomizations: {X}/{X} ready
- HelmReleases: {Y}/{Y} ready
- Last reconcile: {timestamp}
```

**Common issues to flag:**

| Issue | Indicator | Fix |
|-------|-----------|-----|
| Git auth failure | GitRepository not ready | Check deploy key |
| Chart not found | HelmRelease failed | Verify OCI URL/tag |
| Values error | HelmRelease failed | Check YAML syntax |
| Dependency missing | Kustomization waiting | Check dependsOn chain |
| Rate limited | Source fetch failed | Wait or check API limits |
| SOPS decrypt fail | Kustomization failed | Check age key, SOPS config |
