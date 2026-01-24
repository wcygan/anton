---
name: ceph-status
description: Quick Ceph storage health and status. Use when asking about storage, Ceph, disk space, PVCs, or storage health. Keywords: ceph, storage, disk, pvc, rook, osd, pool
---

# Ceph Storage Status

Quick access to Rook-Ceph storage health for the Anton cluster.

## Instructions

### 1. Cluster Health Overview

```bash
# Overall Ceph health
kubectl -n storage exec deploy/rook-ceph-tools -- ceph status

# Quick health check
kubectl -n storage exec deploy/rook-ceph-tools -- ceph health detail
```

### 2. Storage Capacity

```bash
# Cluster storage usage
kubectl -n storage exec deploy/rook-ceph-tools -- ceph df

# OSD usage details
kubectl -n storage exec deploy/rook-ceph-tools -- ceph osd df tree
```

### 3. PVC Status

```bash
# All PVCs and their status
kubectl get pvc -A --sort-by='.metadata.namespace'

# Pending/problem PVCs
kubectl get pvc -A | grep -v Bound
```

### 4. OSD Health

```bash
# OSD status
kubectl -n storage exec deploy/rook-ceph-tools -- ceph osd status

# OSD tree (distribution)
kubectl -n storage exec deploy/rook-ceph-tools -- ceph osd tree
```

### 5. Pool Status

```bash
# Pool list and usage
kubectl -n storage exec deploy/rook-ceph-tools -- ceph osd pool ls detail

# Pool stats
kubectl -n storage exec deploy/rook-ceph-tools -- ceph df detail
```

## Output Format

```
## Storage Status

**Ceph Health**: HEALTH_OK / HEALTH_WARN / HEALTH_ERR
**Cluster**: X OSDs, Y pools
**Usage**: X TB / Y TB (Z%)

### Capacity by Pool
| Pool | Used | Available |
|------|------|-----------|
| ceph-block | X GB | Y GB |

### Issues (if any)
- Warning/Error details

### PVCs
- Total: X
- Bound: Y
- Pending: Z
```

## Quick Commands Reference

| Need | Command |
|------|---------|
| Overall health | `ceph status` |
| Disk space | `ceph df` |
| OSD issues | `ceph osd tree` |
| Slow ops | `ceph health detail` |
| IO stats | `ceph osd perf` |

## When to Escalate

Use `/rook-ceph-storage-specialist` agent for:
- OSD failures
- Pool rebalancing
- Performance tuning
- Recovery operations
