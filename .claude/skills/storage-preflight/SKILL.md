---
name: storage-preflight
description: Check storage and CSI health before deployments. Use when deploying apps, creating PVCs, adding workloads that need persistent storage, or when user mentions helm, deploy, or install with storage requirements.
user-invocable: false
---

# Storage Preflight Check

Automatically validates storage subsystem health before deploying workloads that require persistent storage.

## When This Activates

- User is deploying a new app with PVCs
- User mentions adding storage to a workload
- User is installing a Helm chart that typically needs storage
- User creates or modifies PersistentVolumeClaims

## Preflight Checks

### 1. CSI Driver Registration

```bash
# Verify CSI drivers are registered
kubectl get csidrivers 2>/dev/null | grep -E 'ceph|rbd|cephfs'
```

Expected: `storage.rbd.csi.ceph.com` and `storage.cephfs.csi.ceph.com` present.

### 2. CSI Nodeplugin Health

```bash
# Check nodeplugin pods are running (not crash-looping)
kubectl get pods -n storage -l app=csi-rbdplugin -o wide 2>/dev/null
kubectl get pods -n storage -l app=csi-cephfsplugin -o wide 2>/dev/null

# Check for high restart counts (>10 suggests instability)
kubectl get pods -n storage -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.containerStatuses[0].restartCount}{"\n"}{end}' 2>/dev/null | awk '$2 > 10'
```

### 3. Ceph Cluster Health

```bash
# Quick Ceph health check
kubectl -n storage exec deploy/rook-ceph-tools -- ceph health 2>/dev/null
```

Must be `HEALTH_OK` or `HEALTH_WARN` (not `HEALTH_ERR`).

### 4. Storage Class Availability

```bash
# Verify default storage class exists
kubectl get storageclass | grep -E 'ceph-block|ceph-filesystem'
```

### 5. Pending PVCs (indicates existing issues)

```bash
# Check for stuck PVCs
kubectl get pvc -A --field-selector=status.phase=Pending 2>/dev/null
```

Any pending PVCs suggest storage provisioning issues.

## Output Format

If all checks pass:
```
✅ Storage preflight passed - safe to deploy
```

If issues found:
```
⚠️ Storage preflight warnings:

**Issue**: [description]
**Impact**: [what will happen if you proceed]
**Fix**: [how to resolve]

Recommend fixing storage issues before deploying.
```

## Blocking Issues (STOP deployment)

- CSI drivers not registered
- Ceph HEALTH_ERR
- CSI nodeplugins in CrashLoopBackOff
- Multiple pending PVCs

## Warning Issues (proceed with caution)

- High restart counts on CSI pods
- Ceph HEALTH_WARN
- Single pending PVC (might be unrelated)

## Skip Conditions

Don't run this check if:
- Deployment explicitly has no PVCs/storage
- User is deploying to a namespace that never uses Ceph
- User explicitly says "skip storage check"
