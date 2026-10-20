---
status: Draft
opened: 2026-10-20
closed: null
affects: storage
intent: concrete-need
related-adrs: ['0005', '0015', '0032', '0043']
review-by: 2026-10-27
---

# 0028 — Retire custom storage runtime patches

> Finish SeaweedFS maintenance with a tested operating contract, then remove custom SeaweedFS and Loki binaries without silently weakening data guarantees.

## Goal

Run the Harbor/Loki/S3 path on supported, unmodified upstream releases with a
small GitOps configuration, one understandable maintenance procedure, and a
tested recovery path. The operator accepts brief planned downtime; use that
contract to retire custom availability machinery. Zero downstream
runtime patches is the target; permanently maintaining a fork is not an acceptable
completion state. This is a proposed execution plan, not a rollout authorization.

### Scope

SeaweedFS runtime, its maintenance and policy helpers, the custom Loki WAL
runtime, dependent Harbor/Loki/private S3 consumers, and their operating records.
This is not a claim to inventory every custom binary in Anton. Do not replace
Longhorn, add a database, switch deployment controllers, or migrate to another
object store unless the bounded comparison below demonstrates a lower total
operating burden and receives its own decision. Existing unrelated work stays
with its owners. One operator coordinates all live storage changes serially.

### Completion

An upstream-only deployment passes the agreed maintenance and recovery checks;
custom runtime build/patch dependencies are removed; the current runbook and
skills describe the deployed system. If upstream cannot meet the agreed data
contract, return a bounded migration proposal or an explicit unmet gate. Do not
claim success by renaming the custom image or relabeling a data-loss regression.

## Acceptance criteria

- [ ] Harbor, Loki and every discovered S3 consumer run against qualified stock
  releases; no active runtime or deployment job depends on Anton source patches.
- [ ] A real planned node-maintenance exercise passes the selected availability
  contract and preserves exact old/new object contents and numbered log records.
- [ ] Consistent independent backups pass an isolated restore and actual service
  readback; recovery time and backup freshness meet the accepted per-data contract.
- [ ] Normal operations use one policy owner and one maintenance runbook; retired
  migration paths, build scripts and stale instructions are removed from active use.
- [ ] Source, Flux revision, applied runtime, stable health and cleanup agree;
  remaining risks and any superseded maintenance promises are recorded honestly.

## Tasks

### Recommendation and decision boundary

Start by qualifying stock software after the current storage owner finishes.
The native replica migration has already completed; preserve it and do not repeat
or undo it. The operator accepted brief planned downtime on October 20. Record
the successor to ADR 0043 before retiring its continuity acceptance requirement;
retire the remaining uninterrupted-maintenance drill if that decision is accepted.
The exact outage budget and live procedure still need review. Downtime tolerance
and acknowledged-write durability are separate decisions.
Backups, replication and a UPS do not substitute for correct write barriers.

| Candidate | When to choose it | Consequence |
| --- | --- | --- |
| Stock SeaweedFS with bounded planned downtime | Selected first candidate, subject to stock releases passing the required data contract | Retain the completed two-copy topology. Test orderly stop, node return and recovery; no further replication migration is needed for this goal. |
| Stock SeaweedFS with uninterrupted maintenance | Deferred; revisit only if the operator later changes the maintenance requirement and released software supports the necessary paths | Qualify owner-absent cold-read/write behavior on the existing two-copy topology; retain capacity and cache checks. |
| Move affected consumers to an independently operated S3 service | Evaluate if stock SeaweedFS fails the required integrity contract and no qualified release is available | Removes local SeaweedFS patch ownership but introduces cost, network dependence and migration work. Select an actual provider only after feature, privacy, cost and restore checks. |

Do not reduce Longhorn replicas, downgrade existing two-copy volumes, shrink the
160Gi PVCs, or consolidate servers as part of the image transition. These are
separate migrations with different failure modes. Preserve every registered copy
and FID. A later capacity review may decide whether one replication layer can own
durability; it needs a specific failure model and verified recovery, not merely
the observation that replication is duplicated.

### Evidence baseline and patch disposition

Repository review is pinned to `886fbd6a30efff5a8ac75befb25d1e40c8fef45b`.
The prior read-only cluster check observed this revision applied, healthy storage,
three 160Gi data claims, 24 slots per volume server, and the custom
`4.48-durable1-growth1-sync1` image. These are dated observations, not execution
preconditions. Main and live ownership must be refreshed before each unit.

Coordination on October 20 found newer operational evidence than the committed
parent plan: the migration is complete, with 32 volumes / 64 writable copies on
distinct servers, distributed 22/21/21 across 72 slots (eight free). Its S3/filer
outage lasted about 47 minutes within a separately approved 60-minute window.
The later sync-guard rollout at `886fbd6a` retained that topology. Four transient
read timeouts recovered during replacements; uninterrupted maintenance is still
unproved. Do not mistake completed replication for that stronger guarantee.

### Completed coordination and remaining gates

**Check cluster health**, thread `01a15287-1d2f-7180-a4a6-ea5808cf1ef8`,
completed its authorized qualification on October 20 and is idle. Its final
report is dated 15:56 CDT. The wait-for-session hold is released; execution units
below remain pending, and this planning request authorizes no rollout or cleanup.
Refresh current operation ownership before any later live work.

The final report and retained result files establish:

- Production remained unchanged at `886fbd6a`: 32 volumes / 64 writable copies,
  original five PVC identities, unchanged serving Pod identities/restart counts,
  and 18 healthy Longhorn volumes. Normal Flux/operator ownership is restored.
- Both whole-root filer censuses found zero references to the four old test
  records on volumes 50, 58, 60 and 61. Live sequential scans do not establish
  a transactionally frozen deletion proof or cover arbitrary external raw FIDs.
- All 16 interruption scenarios and 17 exact pair rollback exercises passed.
  Additional mixed-progress and native restore checks preserved earlier completed
  work and neighboring volumes. Wrong-cookie, persisted read-only fence and
  failed-flush controls passed. The three runtime labs report passing results
  and removal of their owned containers and networks.
- Injected sync/close failures reached callers safely across three source-test
  repetitions. These are modeled backend failures, not physical power-cut tests.
- Eight encrypted production archives remain intact and ten retained snapshots
  are Ready. Synthetic encrypted export trials passed full decrypt/hash/size and
  gzip-integrity checks; interrupted/truncated or wrong-hash exports were rejected.
- Harbor/Loki artifact checks, relevant probes and alert checks passed, with no
  monitored storage/log-loss alerts during qualification. Strict production audit
  still fails on the same four old test-record differences; nothing was deleted.

The optional cleanup proposal reserves **60 minutes**, with no new repair after
minute 45 and 15 minutes reserved for recovery. This is a conservative planning
estimate from local trials and historical operations, not a certified production
outage duration and not approval under the user's brief-downtime preference.
It applies to this cleanup only, not the separate stock-image transition.

Fresh consistent pre-cleanup backups, writer/growth fencing, exact current
identities and a repeated fenced reference/live-index check remain mandatory
before any separately approved deletion. The five newest retained snapshots are
crash-consistent; older archives predate subsequent writes. Neither replaces the
fresh rollback point. The qualified cleanup is bound to the deployed custom image;
stock replacement must independently pass its necessary integrity checks.

**Next planning step:** proceed to the contract and stock-qualification units.
Treat the four synthetic leftovers as documented exceptions, not an automatic
prerequisite for patch retirement or a reason to reopen a 60-minute outage.
Choose cleanup only if it is necessary for the accepted operating contract or
separately requested. Preserve logical integrity checks and do not hide the strict
failure by comparing total sizes alone. Retain the completed replica placement,
PVCs, snapshots and encrypted evidence regardless of that decision.

The latest published upstream SeaweedFS release returned by GitHub on October 20
is 4.48. Inspection of upstream master `610346ae8c84fb4cc62bb947a516417637009548`
still found compaction logging and continuing after source sync errors, and the
HTTP growth handler without the local growth-disabled check. This is source
evidence for two unresolved paths, not qualification of all current upstream code.
No stock release has been qualified by this planning task.

| Local change | What it buys | Exit condition |
| --- | --- | --- |
| `durable-ack.patch`: volume data/index barriers and rollback boundaries | Rejects failed persistence and preserves previously acknowledged mappings in modeled failure cases | A published stock release passes the retained failure/recovery cases, or migrate affected data to a service satisfying the agreed contract. Do not silently revert to weaker writes. |
| Same patch: opt-in synchronous LevelDB2 mutations | Persists local filer metadata before success | Qualify upstream support. Consider a supported external metadata backend only if that resolves this specific gap with less operating burden; it cannot fix volume-write durability. |
| `growth-http-fence.patch` | Blocks administrative growth during the special native migration | Remove the need for that migration, or prove a stock procedure fences every allocation path; no source patch merely to preserve a preferred maintenance procedure. |
| `compaction-sync.patch` | Aborts compaction on source sync/close failures | Qualify an upstream fix. Deferring discretionary compaction reduces exposure but does not prove automatic/background paths are safe; inventory those before changing policy. |
| Loki checkpoint/counter patches | Addresses demonstrated WAL checkpoint/replay behavior | Stock Loki passes checkpoint, stream recreation, replay and numbered-record tests. Upstream PR 25162 was open/unmerged at review; its merge alone would not prove every local fix is covered. |

### Unit contract
Status: pending
Depends on: none
Write scope: This plan, a successor ADR if needed, and the maintenance portions of plan 0027/backlog.
Acceptance: Every consumer has an agreed downtime budget, data-loss contract, backup freshness and recovery target; one selected target architecture and one current storage operation owner are recorded.
Verification: Read current Git/Flux/runtime identities and S3 consumer declarations in both repositories; classify rebuildable images, unique artifacts, retained logs and private application data separately. Confirm which existing maintenance work has completed since the baseline. Record the accepted brief-downtime preference in the successor to ADR 0043 and agree the exact interruption budget.
Evidence: pending

- [ ] Record the actual current topology, complete native-volume corpus, serving
  copies, physical free bytes, slots, active writers and in-flight operations.
  Use read-only APIs first; any exec/probe follows the repository approval boundary.
- [ ] Propose a bounded 30-minute planned service interruption for the simpler
  path, with the exact limit set only after measuring stop/start and Loki buffer
  margin. No accepted data-loss budget is implied. Agree backup freshness and
  restore time per consumer rather than assigning a blanket disposable-data label.
- [ ] Reconcile plan 0027 and the scratch backlog only after the architecture
  decision. If the continuity goal is retired, mark that gate superseded with a
  successor ADR; never mark the unperformed availability drill passed.

### Unit qualify
Status: pending
Depends on: contract
Write scope: Existing SeaweedFS/Loki qualification fixtures and a compact evidence table linked from this plan.
Acceptance: Each patch has a verified stock-release replacement, a proved procedural alternative, or an explicitly unresolved integrity gap; the chosen route requires no new downstream runtime patch.
Verification: Pin upstream release/source/image identities, run the existing failing-before cases on unmodified candidates, test data-format upgrade/downgrade, and check real Harbor registry plus Loki/S3 behavior in isolation. Retain failure output and exact bytes, not only process exit status.
Evidence: pending

- [ ] Timebox the first stock-release comparison to two focused engineering
  sessions. Do not keep extending it with more production patches. If blocked,
  return the exact failed guarantees and compare the external-S3 route before
  another migration window. Do not wait indefinitely for upstream to merge fixes.
- [ ] Reuse the existing fixtures for sync failures, rollback-boundary errors,
  compaction failures, metadata persistence, and Loki checkpoint/replay. Preserve
  tests that express necessary behavior; retire tests tied only to an abandoned
  internal procedure once the replacement behavior is covered.
- [ ] Prepare minimal upstream reproductions and patch correspondence locally.
  Obtain explicit authorization before publishing issues, PRs or comments.
  Upstream submission is useful but is not a promise of a released fix.

### Unit prepare
Status: pending
Depends on: qualify
Write scope: Selected stock image pins/configuration, one cutover runbook, existing backup/recovery tooling and any separately approved migration manifest.
Acceptance: The exact candidate, consistent restore rehearsal, writer fences, rollback and measured maintenance budget are reviewable before live approval; bootstrap access does not depend solely on the Harbor instance backed by this storage.
Verification: Restore the selected backup into isolated storage and read real object/log contents; rehearse cutover and rollback on copies using the actual image architecture. Verify images are obtainable through a tested independent source/cache and current credentials remain scoped.
Evidence: pending

- [ ] Use an independent consistent backup of data, filer metadata and required
  master state; include Harbor database/registry consistency and Loki WAL state
  in the recovery boundary. Snapshot availability alone is insufficient.
- [ ] For stock SeaweedFS, keep current PVC identities, metadata paths and
  placement. Remove patch-only configuration only when the stock replacement's
  semantics are verified. Keep supported fsync settings where applicable.
- [ ] For an external-S3 alternative, enumerate API requirements including
  multipart/range access, auth, listing, lifecycle and any version metadata;
  freeze writes for final synchronization, verify manifests and object hashes,
  switch all consumer endpoints coherently, and retain the old source. If writes
  have reached the new backend, rollback must preserve those writes rather than
  blindly switching back. Provider adoption requires separate intake and approval.
- [ ] Present exact targets, commands, expected transitions, stop time, recovery
  operation and cleanup list. Coordinate with any existing storage work; old
  approvals and recorded Pod/PVC bindings do not carry into a new window.

### Unit execute
Status: pending
Depends on: prepare
Write scope: Approved GitOps runtime/configuration cutover and exact maintenance resources recorded in the reviewed runbook.
Acceptance: The selected maintenance contract passes against the actual owning node, all preserved data checks pass, and full recovery has no unmanaged drift or temporary residue.
Verification: Verify source revision through Flux and applied image digests, historical Harbor pulls, new push/pull, old/new Loki records and each private consumer. Perform one approved node-maintenance exercise, measure interruption/recovery, and inspect controllers, replicas, errors and cleanup after restoration.
Evidence: pending

- [ ] Roll one causal change at a time; stop on identity/hash mismatch, failed
  barriers, degraded storage, ambiguous copy, unexpected allocation or time budget.
  Rollback before admitting new writes where possible; after new writes, preserve
  their authoritative state before restoring any older files or endpoint.
- [ ] Downtime path: drain/flush writers, preserve Loki WAL and bounded buffers,
  stop affected services safely, maintain one node, restore service and verify
  exact bytes. Do not claim uninterrupted availability from post-recovery success.
- [ ] Continuity path, only if selected later: refresh the full corpus and verify
  the completed placement rather than repeating migration. Resolve any remaining
  integrity exceptions through their separately approved procedure. Then prove
  never-read object GETs through each
  surviving S3 backend and fresh PUT/GET during actual owner absence. Local
  fixtures, Ready gateways and aggregate copy counts are insufficient.
- [ ] Change Loki in its own window. Follow the tested drain/complete flush/clean
  exit and WAL compatibility procedure; do not plain-revert its image against
  incompatible counter history or discard old WAL directories after an unclean stop.

### Unit simplify
Status: pending
Depends on: execute
Write scope: Retired custom image builders/patches, policy helpers, readiness/probe configuration, storage documentation/skills and completed task records.
Acceptance: Active references to custom SeaweedFS and Loki runtime builds are zero, one owner controls each policy, and routine maintenance needs no private one-off migration scripts.
Verification: Search source and rendered manifests for old image/build/patch references, run contracts:validate and the documentation build for touched surfaces, inspect live image identities, and rehearse the concise runbook with its retained behavioral checks.
Evidence: pending

- [ ] Delete custom runtime build paths and their now-unused implementation
  fixtures after the stock rollout and rollback observation period pass. Keep
  regression tests that remain valuable and evidence in Git history; remove active
  references rather than preserving a parallel legacy interface.
- [ ] Consolidate the hourly durability policy helper with the existing bucket
  provisioning owner if that owner can apply and verify supported settings.
  Preserve drift detection; remove the large binary-copy init container only when
  the replacement actually performs the required policy check.
- [ ] Remove the sleeping readiness sidecar only when the selected upstream
  operator/chart exposes a working Raft-aware probe. Do not weaken quorum gating
  just to reduce container count. A chart/controller migration is a separate cost
  decision, not a prerequisite for removing runtime source patches.
- [ ] Keep a small real S3 read check, useful alerts and persistent filer metadata.
  Remove the retired Iceberg listener/configuration after verifying no consumer.
  Refresh obsolete lakehouse skill routes; retain historical evidence as history.
- [ ] Keep Harbor active-image protection and recovery checks. Avoid adding
  automated orphan deletion or compaction merely to make counters look cleaner.
  Revisit reclamation scheduling using measured disk pressure and safe stock paths.

### Unit close
Status: pending
Depends on: simplify
Write scope: This plan, successor ADR evidence, plan 0027 maintenance status and the single maintained runbook.
Acceptance: Upstream-only operation remains healthy over one normal seven-day maintenance/retention cycle, with restore evidence and no open custom-patch dependency.
Verification: Review normal writes, retained-image checks, Loki records, policy reconciliation, storage headroom and scheduled jobs for that cycle. Confirm the accepted recovery objective using the restore rehearsal, and compare the final operational steps and active custom artifacts against the baseline.
Evidence: pending

- [ ] Review on October 27 or after the first completed operating cycle, whichever
  is appropriate to actual execution. This date creates no scheduled automation.
- [ ] If an integrity gap remains, retain an explicit blocker and next decision;
  do not call the plan done because the cluster is currently healthy.

## Log

- 2026-10-20: Drafted at the operator's request for the simplest maintainable
  setup and a preference for no locally maintained patches. Planning only;
  no commits, publication, runtime changes or maintenance work are authorized here.
- 2026-10-20: Operator confirmed brief planned S3 downtime is acceptable. Selected
  stock SeaweedFS with orderly maintenance as the first qualification candidate;
  uninterrupted maintenance and legacy migration solely for that goal are deferred.
  This preference does not authorize an outage or relaxing data integrity.
- 2026-10-20: Operator authorized coordination with the active SeaweedFS chat and
  a local plan commit, then waiting for that work to finish. Its migration report
  confirms 32 two-copy volumes; replaced the obsolete pending-migration premise.
  Recorded the four-record qualification scope, retained-backup limitations,
  strict-audit exceptions and operational ownership hold. No execution started.
- 2026-10-20: The owner supplied a coordination handoff confirming isolated
  four-volume repair/backup qualification passed and production remains at
  `886fbd6`. Cleanup is not authorized; fresh consistent backups and fenced
  reference checks remain mandatory. Incorporate its final report at pickup.
- 2026-10-20: Redesign From First Principles made upstream-only operation the
  target rather than assuming the existing migration must be completed unchanged.
  Laziness Protocol favors retiring the continuity requirement if acceptable and
  consolidating policy ownership. Subtract Before You Add defers new databases,
  controllers and cleanup automation until an observed requirement justifies them.
  Prove It Works keeps stock qualification and real maintenance/restore acceptance
  mandatory; planned downtime is not a waiver of write-integrity requirements.

- 2026-10-20: Confirmed the other chat completed and is idle; read its final
  four-record qualification report/plan and checked retained runtime/fault/final
  result files. Released the coordination hold, recorded 16 interruption cases,
  17 pair rollbacks, unchanged production, retained backup limits and the optional
  60-minute cleanup reservation. Prove It Works kept isolated qualification
  distinct from production repair; Laziness Protocol made stock qualification
  the next step rather than automatically scheduling synthetic-record cleanup.

## References

- [ADR 0043 and its accepted continuity goal](https://github.com/wcygan/anton/blob/886fbd6a/context/adrs/0043-keep-two-seaweedfs-copies-for-maintenance.md).
- [Parent operational plan 0027](https://github.com/wcygan/anton/blob/886fbd6a/context/plans/0027-improve-cluster-operational-outcomes.md).
- [Recovered migration abort](https://github.com/wcygan/anton/blob/886fbd6a/context/notes/2026-10-20-seaweedfs-migration-abort.md).
- [Durability rollout and limits](https://github.com/wcygan/anton/blob/886fbd6a/context/notes/2026-10-19-seaweedfs-durability-rollout.md).
- [Custom runtime and all three SeaweedFS patches](https://github.com/wcygan/anton/blob/886fbd6a/images/seaweedfs-durability/README.md).
- [Loki plan and rollback boundary](https://github.com/wcygan/anton/blob/886fbd6a/context/plans/0026-investigate-loki-wal-replay.md).
- [Latest published SeaweedFS release at review](https://github.com/seaweedfs/seaweedfs/releases/tag/4.48).
- [Upstream compaction source inspected](https://github.com/seaweedfs/seaweedfs/blob/610346ae8c84fb4cc62bb947a516417637009548/weed/storage/volume_vacuum.go).
- [Upstream administrative growth handler inspected](https://github.com/seaweedfs/seaweedfs/blob/610346ae8c84fb4cc62bb947a516417637009548/weed/server/master_server_handlers_admin.go).
- [Upstream Loki replay proposal, open at review](https://github.com/grafana/loki/pull/25162).
- [Upstream explanation of replication versus persistence](https://github.com/seaweedfs/seaweedfs/issues/11424).
- Private local evidence (not committed): `.private/seaweedfs-two-replica-production/REPORT.md`,
  `.private/seaweedfs-sync-guard-rollout/REPORT.md`,
  `.private/seaweedfs-sync-guard-rollout/ORPHAN-CLEANUP-ADDENDUM.md`, and
  `.private/seaweedfs-four-orphan-qualification/REPORT.md` and `PLAN.md`.
  Checked result files in that directory: `final-readonly.json`,
  `runtime-lab-02/result.json`, `runtime-lab-partial-progress-02/result.json`,
  `runtime-lab-fenced/result.json`, `fault-result.json`, and
  `backup-gate-controls.json`. Private evidence remains local; the summary above
  is the durable public-safe handoff.
