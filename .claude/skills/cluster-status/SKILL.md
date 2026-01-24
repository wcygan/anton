---
name: cluster-status
description: Quick cluster health overview and status check. Use when user asks about cluster health, status, "how's the cluster", "is everything ok", or wants a quick summary of cluster state. Keywords: health, status, overview, check, how is, what's wrong
---

# Cluster Status

Provides a quick overview of Anton cluster health.

## Instructions

When activated, gather and present cluster status concisely:

### 1. Quick Health Check

```bash
# Node status
kubectl get nodes -o wide

# Flux health summary
flux get all -A --status-selector ready=false 2>/dev/null | head -20

# Pod issues
kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded 2>/dev/null | head -15
```

### 2. Key Metrics

```bash
# Resource usage
kubectl top nodes 2>/dev/null || echo "Metrics unavailable"

# Recent warnings
kubectl get events -A --field-selector type=Warning --sort-by='.lastTimestamp' 2>/dev/null | tail -10
```

### 3. Storage Quick Check

```bash
# Ceph health (one-liner)
kubectl -n storage exec deploy/rook-ceph-tools -- ceph health 2>/dev/null || echo "Ceph tools unavailable"
```

## Output Format

Present a concise summary:

```
## Cluster Status

**Nodes**: X/3 Ready
**Flux**: X issues (or "All healthy")
**Pods**: X not running
**Storage**: HEALTH_OK/HEALTH_WARN

### Issues (if any)
- Issue 1
- Issue 2
```

Keep response under 20 lines unless problems require detail.

## When NOT to Use

- For deep debugging → use `/flux-debug` or specialist agents
- For storage details → use `/ceph-status`
- For deployment issues → use `/flux-debug`
