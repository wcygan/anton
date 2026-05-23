---
name: longhorn-terminology
description: Longhorn terminology cheat-sheet.
---

# Longhorn terminology

Canonical: https://longhorn.io/docs/1.11.1/terminology/

## Per-volume

- **Replica** — one copy of volume data on one disk on one node.
- **Healthy replica count** — replicas in `RW` mode. Longhorn rebuilds until this matches `numberOfReplicas`.
- **Stale replica** — a replica whose engine lost contact for longer than `staleReplicaTimeout` (anton: 2880 min = 48 h). Stale replicas are garbage-collected.
- **Engine** — the per-volume synchronous controller.
- **Robustness states** — `healthy` (all replicas RW), `degraded` (lost replicas, rebuilding), `faulted` (no healthy replicas — volume is down).

## Per-volume config

- **Data locality**:
  - `disabled` — no preference.
  - `best-effort` — keep at least one replica local to the attached engine when possible (anton default).
  - `strict-local` — volume only schedulable where a local replica exists. Breaks anti-affinity; avoid on anton.
- **Disk tag / node tag** — label-style filters for replica placement. Not currently used in anton.

## Cluster-wide

- **Backup target** — external object store or NFS for off-cluster volume backups. **Not yet configured** in anton (see `longhorn-backup-dr`).
- **Recurring job** — Longhorn CR that schedules snapshots / backups / filesystem-trim on a cron.
- **Instance manager** — one per node, hosts engine + replica processes.
- **Orphan** — a replica directory on disk with no owning Longhorn CR (e.g. after a hard node loss). Longhorn detects and reports orphans; cleanup is manual or auto-configured.
