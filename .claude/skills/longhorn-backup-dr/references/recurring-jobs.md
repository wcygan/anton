---
name: longhorn-recurring-jobs
description: Longhorn RecurringJob CR reference.
---

# Recurring jobs

Canonical: https://longhorn.io/docs/1.11.1/snapshots-and-backups/scheduling-backups-and-snapshots/

## Tasks

- `snapshot` — local snapshot only. Cheap, no network. Rotates per `retain`.
- `backup` — snapshot + upload to backup target. Requires target configured.
- `filesystem-trim` — issues `fstrim` inside the guest filesystem to reclaim space on sparse replicas.
- `snapshot-delete` / `snapshot-cleanup` — explicit snapshot GC.

## Groups

RecurringJobs reference groups. Volumes opt in via label `recurringjob.longhorn.io/<group>: enabled` (or `recurringjob-source.longhorn.io/<job>: enabled` for a single job). The `default` group is conventional for "every volume". Opting in via label keeps the RecurringJob spec stable as workloads come and go.

## Retention

`retain: N` keeps the last N completed runs per volume. Older runs are deleted automatically. Retention is per-volume, not per-job.

## Concurrency

`concurrency: N` caps parallel runs cluster-wide. On anton's 2.5 GbE network, start conservative (`2`) to avoid saturating inter-node links during backup uploads.

## Schedule suggestions (anton)

- `filesystem-trim` — weekly at an idle hour.
- `snapshot` — every 6h for workloads with notable churn; daily otherwise.
- `backup` — daily; keep 7–14 retention; schedule off-peak.

Stagger jobs with different cron minutes to avoid thundering-herd snapshot creation on the hour.
