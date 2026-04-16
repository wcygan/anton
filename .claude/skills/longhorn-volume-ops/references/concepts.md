---
name: longhorn-concepts
description: Longhorn architecture concepts as they apply to anton.
---

# Longhorn concepts

Canonical: https://longhorn.io/docs/1.11.1/concepts/

## Key components

- **longhorn-manager** — DaemonSet on every Longhorn-schedulable node. Watches Longhorn CRs, orchestrates volume lifecycle.
- **longhorn-engine** — per-volume user-space controller. One engine process per attached volume, runs on the node where the volume is mounted.
- **instance-manager** — DaemonSet that hosts engine and replica processes in a single long-lived pod per node.
- **longhorn-driver** — the CSI driver.
- **replica** — one copy of volume data on one disk. Replicas are sparse files on an ext4/xfs filesystem.

## Data path

1. Workload pod writes to a `/dev/longhorn/<volname>` block device, exposed as a Kubernetes PV.
2. Block writes go to the local engine process.
3. Engine synchronously fans out to N replicas over the cluster network (iSCSI, in-process).
4. Replicas persist to disk as sparse files under `/var/mnt/longhorn-{1,2}/replicas/` on anton.

In anton this cross-node hop is 2.5 GbE per ADR 0005. `dataLocality: best-effort` keeps at least one replica local to the workload when possible, which removes the network hop from the hot read path.

## v1 vs v2 data engine

- Anton uses the **v1 data engine** (default in 1.11.1) — mature, stable.
- v2 (SPDK-based, 1.8+) is not enabled. Would require NVMe-only nodes and a different kernel story on Talos; revisit only if we outgrow v1 perf.
