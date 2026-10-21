---
status: Accepted
date: 2026-10-20
deciders: ['@wcygan']
affects: storage
intent: concrete-need
supersedes: ['0043']
superseded-by: null
retrospective: false
slug: /decisions/0044-use-stock-shared-s3-with-planned-downtime
---

# 0044 — Use stock shared S3 with planned downtime

> Keep SeaweedFS S3 for applications, Harbor, and Loki; accept planned downtime and best-effort logs in order to retire custom runtime patches.

_Public edition prepared on 2026-10-21 from the original record; decision date and meaning retained._

## Context

The native two-copy migration from [ADR 0043](0043-keep-two-seaweedfs-copies-for-maintenance.md) had completed, but uninterrupted maintenance had not been proven. Strict fault testing showed the durability and error-handling limits of stock SeaweedFS, and that stock Loki can lose records during WAL replay. The operator prefers unmodified software and explicitly accepts planned downtime and occasional loss of diagnostic logs. Applications still need S3.

## Decision

Keep shared SeaweedFS S3 for applications, Harbor, and Loki, and qualify stock releases against ordinary operation, orderly cutover, and recovery.

- Keep Loki's WAL enabled, with flush on shutdown.
- Record known fault-handling failures as accepted risks instead of maintaining downstream fixes.
- Preserve existing native copies, PVCs, and Longhorn replicas through image changes.

ADR 0043's requirement for uninterrupted maintenance is retired; its two-copy placement stays. A later capacity decision may revisit topology.

## Alternatives considered

- **Maintain runtime forks indefinitely:** too costly to own and upgrade.
- **Remove SeaweedFS, or move Harbor and Loki to a filesystem:** applications still need S3, so migration adds work without removing it.
- **Add databases, controllers, or another storage service:** deferred until an application's durability needs justify the cost.

## Consequences

Planned interruptions and occasional missing diagnostic logs are accepted. Acknowledged uploads can still be lost after a cache or power failure, or a metadata or index failure, and compaction I/O errors can require repair or restore.

Tolerating log loss does not make unique application files disposable. Before unique uploads are admitted or migrated, each application must declare how it recovers, how fresh its independent backup is, and what a restore must achieve. Replicas and in-cluster snapshots are not independent backups. Every rollout, snapshot, clone, or restart still needs its own approval.
