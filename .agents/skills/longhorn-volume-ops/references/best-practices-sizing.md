---
name: longhorn-sizing
description: Longhorn volume sizing best practices for anton.
---

# Sizing best practices

Canonical: https://longhorn.io/docs/1.11.1/best-practices/

## Capacity ceiling

- Raw: 5× WD_BLACK SN7100 1 TB ≈ 4.55 TiB across the cluster.
- At `defaultReplicaCount: 2` on a 2+1+2 topology, usable ≈ 2.29 TiB. k8s-2's single disk is the bottleneck for spread — until its second NVMe returns, any 2-replica volume will skew toward k8s-1 + k8s-3.
- Reserve 20% headroom per disk for snapshots, rebuild overhead, and filesystem metadata. Longhorn defaults (`storageOverProvisioningPercentage: 100`, `storageMinimalAvailablePercentage: 25`) cover this out of the box.

## Per-volume sizing

- Prefer many small volumes over one giant one — per-volume engine CPU is not free, and rebuilds finish faster on smaller volumes.
- Don't under-size expecting to resize later. Online expand works, but some filesystems need a pod restart to pick up the new size.
- Longhorn PVCs are RWO only. If you need RWX, Longhorn layers an NFS share pod in front of an RWO volume — fine for light shared config, poor for heavy workloads.

## Reserved space

Longhorn's per-disk `storageReserved` field keeps space aside for the host OS. In anton the Longhorn disks are dedicated 1 TB NVMes with nothing else on them, so `storageReserved: 0` is correct. Don't change this unless a disk starts sharing with non-Longhorn data.
