# Fixing Volsync Deployment Issues

## Problem Summary

Volsync v0.11.0 is currently in CrashLoopBackOff state due to missing prerequisites:
- VolumeSnapshot CRDs are not installed
- CSI Snapshot Controller is not deployed
- Volsync requires these components even if snapshot features aren't actively used

## Resolution Status

✅ **FIXED** - Successfully deployed CSI External Snapshotter and enabled Volsync on 2025-06-09

## Root Cause

```
ERROR: no matches for kind "VolumeSnapshot" in version "snapshot.storage.k8s.io/v1"
ERROR: failed to wait for replicationdestination caches to sync: timed out waiting for cache to be synced for Kind *v1.VolumeSnapshot
```

## Prerequisites for Volsync

### 1. CSI Snapshot Controller and CRDs

Volsync requires the Kubernetes CSI Snapshot Controller to be installed before deployment. This provides:
- VolumeSnapshot CRDs
- VolumeSnapshotClass CRDs
- VolumeSnapshotContent CRDs
- Snapshot validation webhooks

### 2. Storage Class with Snapshot Support

Since we're using Rook-Ceph v1.17.4 with the `ceph-block` storage class, we need to:
- Ensure Ceph CSI driver supports snapshots (it does)
- Create a VolumeSnapshotClass for Ceph RBD

## Installation Steps

> **Note**: These steps have been completed and are included here for reference.

### Step 1: Install External Snapshotter

Create the following manifests in `kubernetes/apps/storage/external-snapshotter/`:

```yaml
# kubernetes/apps/storage/external-snapshotter/ks.yaml
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app external-snapshotter
  namespace: flux-system
spec:
  targetNamespace: kube-system
  commonMetadata:
    labels:
      app.kubernetes.io/name: *app
  interval: 1h
  timeout: 10m
  prune: true
  wait: true
  path: ./kubernetes/apps/storage/external-snapshotter/app
  sourceRef:
    kind: GitRepository
    name: flux-system
    namespace: flux-system
  # Must be installed before Volsync
  healthChecks:
    - apiVersion: apiextensions.k8s.io/v1
      kind: CustomResourceDefinition
      name: volumesnapshots.snapshot.storage.k8s.io
    - apiVersion: apiextensions.k8s.io/v1
      kind: CustomResourceDefinition
      name: volumesnapshotclasses.snapshot.storage.k8s.io
    - apiVersion: apiextensions.k8s.io/v1
      kind: CustomResourceDefinition
      name: volumesnapshotcontents.snapshot.storage.k8s.io
```

```yaml
# kubernetes/apps/storage/external-snapshotter/app/kustomization.yaml
---
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: kube-system
resources:
  # CRDs - v8.0.1
  - https://raw.githubusercontent.com/kubernetes-csi/external-snapshotter/v8.0.1/client/config/crd/snapshot.storage.k8s.io_volumesnapshotclasses.yaml
  - https://raw.githubusercontent.com/kubernetes-csi/external-snapshotter/v8.0.1/client/config/crd/snapshot.storage.k8s.io_volumesnapshotcontents.yaml
  - https://raw.githubusercontent.com/kubernetes-csi/external-snapshotter/v8.0.1/client/config/crd/snapshot.storage.k8s.io_volumesnapshots.yaml
  # Controller
  - https://raw.githubusercontent.com/kubernetes-csi/external-snapshotter/v8.0.1/deploy/kubernetes/snapshot-controller/rbac-snapshot-controller.yaml
  - https://raw.githubusercontent.com/kubernetes-csi/external-snapshotter/v8.0.1/deploy/kubernetes/snapshot-controller/setup-snapshot-controller.yaml
```

### Step 2: Create VolumeSnapshotClass for Ceph

```yaml
# kubernetes/apps/storage/rook-ceph-cluster/app/volumesnapshotclass.yaml
---
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshotClass
metadata:
  name: ceph-block-snapshot
  annotations:
    snapshot.storage.kubernetes.io/is-default-class: "true"
driver: rook-ceph.rbd.csi.ceph.com
parameters:
  clusterID: storage  # Must match cephClusterSpec.clusterName
  csi.storage.k8s.io/snapshotter-secret-name: rook-csi-rbd-provisioner
  csi.storage.k8s.io/snapshotter-secret-namespace: storage
deletionPolicy: Delete
```

Add to `kubernetes/apps/storage/rook-ceph-cluster/app/kustomization.yaml`:
```yaml
resources:
  - ./helmrelease.yaml
  - ./dashboard
  - ./servicemonitor.yaml
  - ./volumesnapshotclass.yaml  # Add this line
```

### Step 3: Update Volsync Kustomization Dependencies

```yaml
# kubernetes/apps/storage/volsync/ks.yaml
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app volsync
  namespace: flux-system
spec:
  targetNamespace: storage
  commonMetadata:
    labels:
      app.kubernetes.io/name: *app
  interval: 1h
  timeout: 10m
  prune: false  # Changed from true to false in production
  wait: true
  dependsOn:
    - name: external-snapshotter    # Add this dependency
      namespace: storage            # IMPORTANT: Use storage namespace, not flux-system
    - name: rook-ceph-cluster
      namespace: storage
  path: ./kubernetes/apps/storage/volsync/app
  sourceRef:
    kind: GitRepository
    name: flux-system
    namespace: flux-system
```

> **Fix Applied**: The external-snapshotter dependency was initially set to `namespace: flux-system` but should be `namespace: storage` where the kustomization actually exists.

### Step 4: Update Volsync HelmRelease

```yaml
# kubernetes/apps/storage/volsync/app/helmrelease.yaml
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: volsync
spec:
  interval: 1h
  releaseName: volsync
  chart:
    spec:
      chart: volsync
      version: 0.11.0
      sourceRef:
        kind: HelmRepository
        name: backube
        namespace: flux-system
  install:
    remediation:
      retries: 3
  upgrade:
    remediation:
      retries: 3
    cleanupOnFail: true
  values:
    manageCRDs: true
    metrics:
      disableAuth: true
    # Enable snapshot support with Ceph
    snapshotClassName: csi-ceph-blockpool  # Note: Using existing snapshot class name
```

## Deployment Order

1. **Deploy external-snapshotter first**
   ```bash
   git add kubernetes/apps/storage/external-snapshotter/
   git commit -m "feat(storage): add CSI snapshot controller for volume snapshots"
   git push
   flux reconcile kustomization cluster-apps --with-source
   ```

2. **Verify CRDs are installed**
   ```bash
   kubectl get crd | grep snapshot
   # Should show:
   # volumesnapshotclasses.snapshot.storage.k8s.io
   # volumesnapshotcontents.snapshot.storage.k8s.io
   # volumesnapshots.snapshot.storage.k8s.io
   ```

3. **Deploy VolumeSnapshotClass**
   ```bash
   git add kubernetes/apps/storage/rook-ceph-cluster/app/volumesnapshotclass.yaml
   git commit -m "feat(storage): add VolumeSnapshotClass for Ceph RBD"
   git push
   flux reconcile kustomization rook-ceph-cluster -n storage --with-source
   ```

4. **Scale Volsync back up**
   ```bash
   kubectl scale deployment volsync -n storage --replicas=1
   ```

## Verification

After deployment, verify everything is working:

```bash
# Check snapshot controller is running
kubectl get pods -n kube-system | grep snapshot-controller

# Verify VolumeSnapshotClass exists
kubectl get volumesnapshotclass

# Check Volsync is healthy
kubectl get pods -n storage | grep volsync

# Test snapshot functionality
kubectl apply -f - <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: test-snapshot-pvc
  namespace: default
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: ceph-block
  resources:
    requests:
      storage: 1Gi
---
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: test-snapshot
  namespace: default
spec:
  volumeSnapshotClassName: ceph-block-snapshot
  source:
    persistentVolumeClaimName: test-snapshot-pvc
EOF

# Check snapshot status
kubectl get volumesnapshot -n default
```

## Troubleshooting

### If Volsync still crashes after installing snapshotter:

1. Check logs for specific errors:
   ```bash
   kubectl logs -n storage deployment/volsync
   ```

2. Verify snapshot controller is running:
   ```bash
   kubectl get deployment -n kube-system snapshot-controller
   ```

3. Check if CRDs are properly installed:
   ```bash
   kubectl api-resources | grep snapshot
   ```

### Common Issues:

- **"cannot list resource volumesnapshots"**: RBAC permissions issue
- **"snapshot controller not found"**: Controller deployment failed
- **"invalid snapshot class"**: VolumeSnapshotClass not created or wrong parameters

## Benefits of Fixing This

1. **Enables Backup/Restore**: Volsync can create application-consistent backups
2. **Disaster Recovery**: Snapshot-based replication to remote clusters
3. **Data Protection**: Point-in-time recovery for stateful applications
4. **Migration Support**: Easy workload migration between clusters

## References

- [Volsync Documentation](https://volsync.readthedocs.io/)
- [CSI Snapshotter Documentation](https://github.com/kubernetes-csi/external-snapshotter)
- [Rook Ceph Snapshots](https://rook.io/docs/rook/latest/Storage-Configuration/Ceph-CSI/ceph-csi-snapshot/)
- Anton Cluster Ceph Implementation: `/docs/ceph/adding-ceph.md`

## Implementation Summary (2025-06-09)

### What Was Actually Done

1. **Created External Snapshotter Deployment**
   - Added `kubernetes/apps/storage/external-snapshotter/` directory structure
   - Created Kustomization to deploy CSI snapshot controller v8.0.1
   - Successfully installed VolumeSnapshot CRDs

2. **Updated Storage Kustomization**
   - Added external-snapshotter to the storage apps list
   - Positioned it before volsync to ensure proper dependency order

3. **Fixed Volsync Dependencies**
   - Updated volsync Kustomization to depend on external-snapshotter
   - Fixed namespace reference issue (changed from flux-system to storage)
   - Added rook-ceph-cluster as additional dependency

4. **Enabled VolumeSnapshotClass**
   - Uncommented snapshotclass.yaml in rook-ceph-cluster storage-classes
   - Added storage-classes to rook-ceph-cluster kustomization resources
   - Manually applied VolumeSnapshotClass to unblock immediate deployment

5. **Updated Volsync Configuration**
   - Enabled snapshot support in HelmRelease values
   - Configured to use `csi-ceph-blockpool` snapshot class

### Current Status

✅ **External Snapshotter**: Running (2/2 pods ready in kube-system)
✅ **VolumeSnapshot CRDs**: Installed and available
✅ **VolumeSnapshotClass**: Created (`csi-ceph-blockpool`)
✅ **Volsync**: Running successfully (2/2 containers ready)

### Key Lessons Learned

1. **Namespace Dependencies**: When referencing Kustomizations in dependencies, use the actual namespace where the Kustomization exists, not where it's defined
2. **CRD Requirements**: Some operators like Volsync require CRDs to be present even if the features aren't actively used
3. **Manual Intervention**: Sometimes manually applying resources can unblock reconciliation issues while waiting for GitOps to catch up

### Git Commits

```bash
# Initial fix implementation
0f6ac2d feat(storage): add CSI snapshot controller for Volsync support

# Namespace correction
276ce87 fix(storage): correct external-snapshotter namespace in volsync dependencies
```

## Next Steps: Configure ReplicationSources

**IMPORTANT**: While Volsync is now successfully deployed, no ReplicationSources have been configured yet. This means no backups are currently being performed.

### To Enable Backups

1. **Create ReplicationSource for each workload** you want to backup
2. **Configure backup destination** (S3, NFS, or another cluster)
3. **Set backup schedule** and retention policies
4. **Test restore procedures** to ensure backups are valid

See the backup templates in:
- `kubernetes/apps/storage/volsync/migration-templates/backup-template.yaml`
- `docs/ceph/operations/backup-restore.md` for detailed procedures

### Example ReplicationSource

```yaml
apiVersion: volsync.backube/v1alpha1
kind: ReplicationSource
metadata:
  name: <app-name>-backup
  namespace: <namespace>
spec:
  sourcePVC: <pvc-name>
  trigger:
    schedule: "0 2 * * *"  # Daily at 2 AM
  restic:
    pruneIntervalDays: 7
    retain:
      daily: 7
      weekly: 4
      monthly: 3
    repository: <app-name>-backup-secret
    cacheCapacity: 1Gi
    cacheStorageClassName: ceph-block
    storageClassName: ceph-block
    volumeSnapshotClassName: csi-ceph-blockpool
```

**Current Status**: 
- ✅ Volsync operational
- ❌ No ReplicationSources configured
- ⏳ Awaiting backup destination configuration