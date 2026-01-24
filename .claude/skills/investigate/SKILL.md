---
name: investigate
description: Investigate cluster incidents and issues in isolation. Use for deep debugging, incident response, or when you need focused investigation without polluting main context.
context: fork
agent: Explore
disable-model-invocation: true
argument-hint: <issue-description>
allowed-tools: Read, Grep, Glob, Bash(kubectl:*), Bash(flux:*), Bash(talosctl:*), Bash(helm:*)
---

# Incident Investigation

Runs a focused investigation in an isolated context to avoid polluting the main conversation.

## Investigation Framework

### 1. Initial Triage

Quickly assess the scope and severity:

```bash
# Cluster-wide issues
kubectl get nodes
kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded | head -20

# Recent events
kubectl get events -A --sort-by='.lastTimestamp' | tail -30

# Flux status
flux get all -A --status-selector ready=false
```

### 2. Narrow Down

Based on symptoms, focus investigation:

**Pod Issues:**
```bash
kubectl describe pod <pod> -n <namespace>
kubectl logs <pod> -n <namespace> --previous
kubectl get events -n <namespace> --field-selector involvedObject.name=<pod>
```

**Deployment Issues:**
```bash
kubectl rollout status deployment/<name> -n <namespace>
kubectl describe deployment <name> -n <namespace>
```

**Flux/GitOps Issues:**
```bash
flux describe helmrelease <name> -n <namespace>
flux describe kustomization <name> -n flux-system
kubectl logs -n flux-system deployment/helm-controller --tail=100
```

**Storage Issues:**
```bash
kubectl get pvc -A | grep -v Bound
kubectl describe pvc <name> -n <namespace>
kubectl -n storage exec deploy/rook-ceph-tools -- ceph health detail
```

**Network Issues:**
```bash
kubectl exec -n kube-system ds/cilium -- cilium status
kubectl get svc -A | grep -i <service>
kubectl get endpoints -n <namespace>
```

### 3. Trace Dependencies

```bash
# Find what depends on a resource
flux trace --api-version apps/v1 --kind Deployment --name <name> -n <namespace>

# Check Kustomization dependencies
flux get kustomization -A | grep <name>
```

### 4. Timeline Reconstruction

```bash
# Events in chronological order
kubectl get events -A --sort-by='.metadata.creationTimestamp'

# Recent changes
git log --oneline --since="2 hours ago" -- kubernetes/
```

## Output Requirements

Provide a structured incident report:

```
## Incident Summary

**Issue**: One-line description
**Severity**: Critical / Warning / Info
**Affected**: Components/namespaces impacted
**Started**: Approximate time

## Root Cause

[Analysis of what went wrong]

## Evidence

- Log excerpt 1
- Event details
- Configuration issue

## Resolution

### Immediate Fix
[Commands to resolve now]

### Permanent Fix
[What to change in Git]

## Prevention

[How to prevent recurrence]
```

## Investigation Tips

1. Start broad, narrow down systematically
2. Check events first - they often reveal the cause
3. Look for cascade failures (one thing breaking others)
4. Compare working vs non-working configurations
5. Check recent git commits for related changes

## Handoff

When investigation is complete, the summary will be returned to the main conversation for action.
