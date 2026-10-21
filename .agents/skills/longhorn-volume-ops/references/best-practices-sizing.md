---
name: longhorn-sizing
description: Longhorn volume sizing best practices for anton.
---

# Sizing best practices

Canonical: https://longhorn.io/docs/1.11.1/best-practices/

## Capacity ceiling

Estimate usable capacity from the current schedulable Longhorn disks and replica count. Confirm each node's actual disk inventory and free capacity from Talos and Longhorn status; do not reuse historical node counts or capacity totals. Reserve space for snapshots, rebuilds, and filesystem metadata using the current Longhorn settings.

## Per-volume sizing

- Prefer many small volumes over one giant one — per-volume engine CPU is not free, and rebuilds finish faster on smaller volumes.
- Don't under-size expecting to resize later. Online expand works, but some filesystems need a pod restart to pick up the new size.
- Longhorn PVCs are RWO only. If you need RWX, Longhorn layers an NFS share pod in front of an RWO volume — fine for light shared config, poor for heavy workloads.

## Reserved space

Longhorn's per-disk `storageReserved` field keeps space aside for the host OS. Inspect each disk path and host usage before setting `storageReserved`. Keep any existing reservation unless the disk ownership and operating-system needs are confirmed.
