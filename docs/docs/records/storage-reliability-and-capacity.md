---
title: Storage reliability, capacity, and backups
record_type: historical-operations
period: 2026-10
---

# Storage reliability, capacity, and backups

October 2026 storage work reclaimed abandoned space, tested a stock SeaweedFS and Loki runtime, and rehearsed a Harbor restore. None of it established a recurring backup or authorized a production cutover.

## Reclaiming capacity

Cleanup separated abandoned replica data from live volumes. Verified orphan directories were removed and supported filesystem trims were run; current replicas and application data were left alone. Together they reclaimed substantial allocated space.

The gap between expected and observed usage was mostly explained by abandoned replicas, with a small remainder from filesystem overhead and timing. This is a dated cleanup result, not a capacity forecast.

## Backups

The dedicated Longhorn backup target was turned off on purpose. The operator accepted that disposable persistent data could be lost and declined to run external backup infrastructure. That is a risk decision, not a restore capability.

A later backup window captured coordinated recovery points and rehearsed restoring Harbor. It did not set up recurring backups.

## Retiring custom runtime patches

The work aimed to replace locally patched SeaweedFS and Loki runtimes with stock releases while keeping the S3 and logging behavior Anton depends on.

| Stage | Result |
| --- | --- |
| First qualification, original contract | Failed the retained-integrity requirement |
| Revised contract (planned downtime and occasional log loss allowed) | Normal-operation and transition tests passed; no new ordinary-operation blocker |
| Production readiness | Not reached |

## Still open

- Known crash-loss risks were not repaired.
- No fresh coordinated production recovery point exists for a cutover.
- Recurring backups and the stock production cutover are not implemented.

The private working copy of the plan keeps the exact gates and tasks. Local qualification does not authorize a deployment. Before any further storage change, collect current evidence for capacity, restore, ownership, and data integrity.
