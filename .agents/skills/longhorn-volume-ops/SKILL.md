---
name: longhorn-volume-ops
description: Create, resize, clone, and tune per-volume Longhorn PVCs in anton. Use when adding a PVC backed by longhorn, overriding replica count or data locality for a specific workload, resizing an existing Longhorn volume, or cloning a volume from an existing PVC. Does not cover disk/node ops (longhorn-node-ops) or backup/restore (longhorn-backup-dr).
---

# longhorn-volume-ops

Per-volume Longhorn operations in anton.

## Anton defaults

- `longhorn` is the cluster default StorageClass (HelmRelease `persistence.defaultClass: true`).
- 2 replicas, `dataLocality: best-effort`, `staleReplicaTimeout: 2880` minutes.
- Disk counts, capacity, and replica placement vary with hardware and maintenance. Inspect current Talos discovered volumes, Longhorn node disk status, and replica placement before sizing or claiming a node is a scheduling bottleneck.
- Authoritative decision: `docs/docs/decisions/0005-adopt-longhorn-for-block-storage.md`.
- Talos platform gotchas live in [longhorn-node-ops/references/talos.md](../longhorn-node-ops/references/talos.md).

## When to use

- Adding a PVC that should live on Longhorn — usually nothing to do; the default SC covers it.
- Need different replica count or locality for a specific workload → author a per-workload StorageClass.
- Resize an existing Longhorn PVC — online expand is supported.
- Clone from an existing PVC via `dataSource`.

## Recipes

### Default PVC

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: <name>
  namespace: <ns>
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 20Gi
  # storageClassName omitted → uses `longhorn` (cluster default)
```

### 3-replica override via custom StorageClass

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: longhorn-3r
provisioner: driver.longhorn.io
parameters:
  numberOfReplicas: "3"
  dataLocality: best-effort
  staleReplicaTimeout: "2880"
allowVolumeExpansion: true
reclaimPolicy: Delete
volumeBindingMode: Immediate
```

Check the current node and disk inventory plus Longhorn anti-affinity rules before selecting a replica count. A sample StorageClass does not establish that the current cluster can place all replicas.

### Online resize

Edit the PVC's `spec.resources.requests.storage` upward. Longhorn resizes the engine + replicas online for RWO. Filesystem resize runs at next pod restart for some drivers — verify with `kubectl get pvc` and inside-pod `df -h`.

### Clone from existing PVC

```yaml
spec:
  dataSource:
    kind: PersistentVolumeClaim
    name: <source-pvc>
  resources:
    requests:
      storage: 20Gi
```

## References

- [Concepts](references/concepts.md) — architecture overview, data path
- [Terminology](references/terminology.md) — replica, engine, robustness states
- [Sizing best practices](references/best-practices-sizing.md) — capacity planning
- [Data locality tuning](references/tuning-data-locality.md) — when to override
