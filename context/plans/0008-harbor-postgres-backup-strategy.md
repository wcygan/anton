---
status: Draft
opened: 2026-04-23
closed: null
affects: registries
intent: concrete-need
related-adrs: [0015]
review-by: null
---

# 0008 — Harbor Postgres backup strategy

> Define and implement a backup + restore story for Harbor's CNPG Postgres cluster (`registries/harbor-postgres`), which holds the registry's irreplaceable state (users, projects, roles, repo metadata, audit log).

## Goal

Harbor's blob storage is reproducible — images can be re-pushed from developer laptops or CI. Harbor's Postgres is not: it holds project/user/role definitions, audit trails, robot-account credentials, vulnerability scan history, and the identity surface that downstream consumers authenticate against. ADR 0015 Consequences called this out as the most important piece of state Harbor introduces. Plan 0006 closed with Postgres backups explicitly out of scope, on the understanding that anton's broader backup story is still unwritten. This plan exists to either: (a) stand up a Harbor-specific backup flow as an interim, or (b) wait for the broader anton backup ADR and apply its pattern to Harbor as the first consumer. Done means: a documented, tested restore drill — not just scheduled backups sitting in an object store.

## Acceptance criteria

- [ ] Backup target decided and provisioned (options: CNPG `Backup`/`ScheduledBackup` to SeaweedFS bucket `cnpg-backups` with Barman; `velero` + CSI snapshots; off-cluster S3; something else — TBD during Draft → In-progress transition).
- [ ] Scheduled backups running at an agreed cadence (hourly WAL + daily base is the CNPG default starting point; validate against Harbor's actual churn and RPO target).
- [ ] Restore drill executed end-to-end: destroy a throwaway `harbor-postgres-*` cluster, restore from backup, verify Harbor's `core` reconnects to the restored DB and `/api/v2.0/projects` returns the expected project set.
- [ ] Runbook in `docs/docs/notes/` documenting: how to trigger an on-demand backup, how to restore to a new cluster, RPO/RTO, and the exact CNPG/Barman CLI or `kubectl cnpg` invocations.
- [ ] Monitoring wired: backup-success metric alert in the existing `harbor-health` PrometheusRule family (or a sibling rule) — we must know when backups stop.

## Tasks

This is a **Draft** plan — the phase structure below is a sketch to be refined when work actually starts. The Goal and acceptance criteria are the stable contract; tasks will churn.

### Phase 0 — Scope decision (do this first)

- [ ] Decide: Harbor-specific plan, or wait for the broader anton backup ADR. If waiting, flip this plan's status to `Blocked` naming the broader ADR as the blocker. If Harbor-specific, continue to Phase 1.
- [ ] Pick backup target: SeaweedFS S3 (same cluster — OK for ops-error recovery, not for site loss), off-cluster S3 (e.g. a separate provider), or both (3-2-1).
- [ ] Decide RPO/RTO. Harbor is "important but not hot-path" — likely 1h RPO / 4h RTO is overkill; 24h RPO / 24h RTO is probably fine. User owns this call.

### Phase 1 — Stand up backups (when Phase 0 unblocks)

- [ ] Author CNPG `ScheduledBackup` + `ObjectStore` (or equivalent) pointing at the chosen target.
- [ ] Provision the target: bucket + scoped identity (mirror the `harbor` bucket-scoped identity pattern from plan 0006).
- [ ] Verify first backup uploads successfully; check artifact is actually readable.

### Phase 2 — Restore drill

- [ ] Author a restore runbook in `docs/docs/notes/harbor-postgres-restore.md`.
- [ ] Execute it against a throwaway namespace + Harbor test instance. Time the RTO.
- [ ] If the drill surfaces gaps, iterate.

### Phase 3 — Monitoring + close

- [ ] Alert rule: backup age > expected cadence + grace period.
- [ ] Close this plan Done; if the work produced a durable decision (e.g., "anton uses CNPG Barman backups to SeaweedFS as the platform default"), hand off to the `adr` skill.

## Log

- 2026-04-23: Plan opened as the successor-trigger from plan 0006 close. ADR 0015 Consequences flagged Harbor's DB as irreplaceable state; plan 0006 deferred backups explicitly so its scope stayed bounded. Status `Draft` — Phase 0 scope decision (Harbor-specific now vs wait for broader anton backup ADR) is the gating question before this plan graduates to `In-progress`.

## References

- Anchor decision: [ADR 0015 — Adopt Harbor as the in-cluster image registry](../adrs/0015-adopt-harbor-for-image-registry.md) — Consequences section flags Postgres as irreplaceable state
- Predecessor plan: [plan 0006 — Adopt Harbor on SeaweedFS S3 backend](./0006-adopt-harbor-seaweedfs.md) — Phase 7 line 95 triggers this plan
- Broader anton backup ADR: not yet written; flagged across plans 0001, 0002, 0005, 0006. If that ADR lands first, this plan becomes its first consumer.
- CNPG backup docs: https://cloudnative-pg.io/documentation/current/backup/
- Cluster check: `kubectl -n registries get cluster harbor-postgres` (current cluster state)
- SeaweedFS bucket pattern: `kubernetes/apps/storage/seaweedfs-config/` (example of the bucket-scoped identity pattern per plan 0006 Hardening entry)
