---
status: Accepted
date: 2026-10-20
deciders: ['@wcygan']
affects: storage
intent: concrete-need
supersedes: ['0043']
superseded-by: null
retrospective: false
---

# 0044 — Use stock shared S3 with planned downtime

> Retain SeaweedFS S3 for apps, Harbor and Loki; accept planned downtime and best-effort logs to retire runtime forks.

## Status

Accepted by the operator in Plan 0028's scope decisions; production execution remains separately gated.

## Context

Native two-copy migration has completed, but uninterrupted maintenance is not
proved. Strict fault qualification demonstrates stock SeaweedFS durability/error
handling limits and stock Loki replay loss. The operator prefers unmodified
software and explicitly accepts planned downtime and occasional diagnostic log
loss. S3 remains a concrete application capability, including future Drop uploads.

## Decision

Retain shared SeaweedFS S3 for apps, Harbor and Loki. Qualify stock releases
against ordinary-operation, orderly cutover and recovery requirements. Keep Loki
WAL enabled and flush on shutdown. Record known fault failures as risks rather
than requiring downstream fixes. Preserve existing native copies, PVCs and
Longhorn replicas during image changes. A separate capacity decision may revisit
topology later. ADR 0043's uninterrupted-maintenance requirement is retired;
its completed native copy placement remains.

## Alternatives considered

- Maintain runtime forks indefinitely: rejected for ownership and upgrade cost.
- Remove SeaweedFS or move Harbor/Loki to filesystem: rejected for this plan;
  S3 is required by apps and migration adds work without eliminating it.
- Add databases/controllers or another storage service: deferred until a concrete
  app durability requirement justifies that operating cost.

## Consequences

Planned interruptions and occasional missing diagnostic logs are accepted.
Acknowledged app uploads can be lost after cache/power or metadata/index failures;
compaction I/O errors can require repair/restore. Log-loss tolerance does not
classify unique app files as disposable. Each app must declare recoverability,
independent backup freshness and restore expectations before unique uploads are
admitted or migrated. Replicas and in-cluster snapshots are not independent backups.

## Follow-ups

- Complete Plan 0028's consistent backup/restore and reviewed cutover procedure.
- Obtain exact live-action approval before any rollout, snapshot, clone or restart.
- Keep historical test failures, rollback images and recovery evidence through
  the observation period; remove active custom build paths after it passes.
