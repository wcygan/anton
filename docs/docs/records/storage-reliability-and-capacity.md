---
title: Storage reliability, capacity, and backups
record_type: historical-operations
period: 2026-10
---

# Storage reliability, capacity, and backups

In October 2026, storage work reclaimed abandoned space, tried and partly abandoned an uninterrupted-maintenance design for SeaweedFS, and then moved SeaweedFS and Loki back to stock upstream releases. By 2026-10-21, stock SeaweedFS 4.48 and Loki 3.7.8 served the existing data. Recurring off-cluster backups were still not in place.

## Reclaiming capacity

Cleanup separated abandoned replica data from live volumes. Verified orphan directories were removed and supported filesystem trims were run; current replicas and application data were left alone. Together they reclaimed substantial allocated space.

The gap between expected and observed usage was mostly explained by abandoned replicas, with a small remainder from filesystem overhead and timing. This is a dated cleanup result, not a capacity forecast.

## Two copies for maintenance

With replication `000`, each SeaweedFS volume had one serving copy, so cold reads stopped whenever its node was down. [ADR 0043](../decisions/0043-keep-two-seaweedfs-copies-for-maintenance.md) chose two copies per volume.

- **A first Harbor maintenance exercise failed.** A cold pull missed its deadline while a node was drained, and the drain stopped on a proxy reset. Volume servers had been advertising pod IPs that went stale after replacement. They now advertise stable DNS names, and the maintenance command restores its proxy path before draining.
- **The first live migration was aborted safely.** Its first configuration step timed out against a stale address. No volume was changed or copied, no node was drained, and every original volume was restored and verified within about 25 minutes. The temporary objects it left behind showed that cleanup must confirm dependent pods are gone, not just their Jobs.
- **The migration later completed.** All native volumes now have two copies. Uninterrupted maintenance was never proven, and [ADR 0044](../decisions/0044-use-stock-shared-s3-with-planned-downtime.md) retired that goal in favor of planned downtime.

## Retiring custom runtime patches

The goal was to replace locally patched SeaweedFS and Loki builds with stock releases while keeping shared S3 for applications, Harbor, and Loki.

| Stage | Result |
| --- | --- |
| First qualification, original contract | Failed the retained-integrity requirement |
| Revised contract (planned downtime and occasional log loss allowed) | Normal-operation and transition tests passed |
| Backup window | Coordinated recovery points captured; Harbor restore rehearsed |
| Production cutover, 2026-10-21 | Completed inside a 60-minute window |

During the cutover, conservative interruption bounds were about 19 minutes for S3, 22 minutes for Harbor, and 23 minutes for Loki. Every SeaweedFS process now runs the stock image, with the original volumes, copies, and claims. Afterward, known objects, Harbor images and blob hashes, and stored and fresh Loki records all verified. Logs may have been lost during the interruption, and a successful sample does not prove collection was continuous.

The cutover also showed that the S3 custom resource rejects zero replicas, and that the operator's admission webhooks and Flux dependency order must be restored in sequence. Three Harbor manifests that were missing before the cutover are still unrepaired.

## Backups

The dedicated Longhorn backup target is off on purpose. The operator accepted that disposable persistent data could be lost and declined external backup infrastructure. That is a risk decision, not a restore capability.

ADR 0044 adds a condition: before unique application uploads are admitted, each application must declare how it recovers and how fresh its independent backup is. Replicas and in-cluster snapshots do not count.

## Still open

- Recurring, independent backups with freshness checks.
- Known crash-loss risks in stock SeaweedFS and Loki, which were accepted rather than fixed.
- A planned one-node maintenance exercise and the seven-day post-cutover observation.
- The three missing Harbor manifests.

The private plan keeps the exact gates and tasks. Before any further storage change, collect current evidence for capacity, restore, ownership, and data integrity.
