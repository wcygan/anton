---
status: In-progress
opened: 2026-10-20
closed: null
affects: storage
intent: concrete-need
related-adrs: ['0005', '0015', '0032', '0043']
review-by: 2026-10-27
---

# 0028 — Retire custom storage runtime patches

> Keep shared SeaweedFS S3 for apps, Harbor and Loki; return to stock software with planned downtime, best-effort logs and explicit upload-recovery limits.

## Goal

Keep SeaweedFS S3 as a shared cluster capability for applications such as Drop,
Harbor and Loki. Run unmodified upstream SeaweedFS and Loki with a small GitOps
configuration and one understandable maintenance procedure. Accept planned
downtime and occasional diagnostic log loss instead of maintaining runtime forks.
Application uploads remain a separate data class with explicit crash-loss and
backup limits; log-loss tolerance does not declare uploads disposable. Zero
runtime patches is the target. This plan update authorizes no production change.

### Scope

SeaweedFS runtime, its maintenance and policy helpers, the custom Loki WAL
runtime, dependent Harbor/Loki/private S3 consumers, and their operating records.
This is not a claim to inventory every custom binary in Anton. Do not replace
Longhorn, add a database, switch deployment controllers, or migrate to another
object store as part of this plan. Do not move Harbor or Loki to filesystem
backends merely to remove their dependency on the retained S3 service. Existing unrelated work stays
with its owners. One operator coordinates all live storage changes serially.

### Completion

An upstream-only deployment passes the agreed maintenance and recovery checks;
custom runtime build/patch dependencies are removed; the current runbook and
skills describe the deployed system. Known fault-injection failures remain
recorded as accepted limitations where the consumer contract permits them, never
relabeled as passing tests. Block on ordinary-operation failures, unsafe migration
or an app requirement that the chosen storage cannot meet; do not add a new fork.

## Acceptance criteria

- [ ] Harbor, Loki and every discovered S3 consumer run against qualified stock
  releases; no active runtime or deployment job depends on Anton source patches.
- [ ] A real planned node-maintenance exercise passes the selected availability
  contract: orderly maintenance preserves checked object bytes, Harbor artifacts
  and flushed log history; crash/replay log loss is recorded rather than a zero-loss gate.
- [ ] Consistent independent backups pass an isolated restore and actual service
  readback; recovery time and backup freshness meet the accepted per-data contract.
- [ ] Normal operations use one policy owner and one maintenance runbook; retired
  migration paths, build scripts and stale instructions are removed from active use.
- [ ] Source, Flux revision, applied runtime, stable health and cleanup agree;
  remaining risks and any superseded maintenance promises are recorded honestly.

## Tasks

### Recommendation and decision boundary

The selected route is stock SeaweedFS serving apps, Harbor and Loki on their
existing S3 endpoints. Keep separate buckets and scoped credentials. Keep Loki
monolithic with stock WAL enabled and graceful-shutdown flushing: disabling WAL
is not required to remove patches and would broaden unflushed-log loss. Harbor
stays on S3; no filesystem or external-service migration is scheduled.

The operator accepts planned downtime and occasional log loss. This supersedes
the earlier requirement that every retained crash/fault fixture pass before a
stock image can proceed to transition qualification. Preserve the failed results;
change the operating contract explicitly instead of modifying tests to pass.
The completed native replica migration stays in place. Record a successor to
ADR 0043 before retiring its uninterrupted-maintenance acceptance requirement.
Measure an exact maintenance budget before proposing a live window.

### Data contract and risks to app uploads

| Data class | Accepted tradeoff and required recovery |
| --- | --- |
| Loki diagnostic logs | Best-effort history; occasional gaps after crashes/replay are acceptable. No completeness/audit-log guarantee. Keep ordinary ingestion/query, retention, disk alerts and graceful flush; quantify observed gaps without promising a maximum loss interval. |
| Harbor images and artifacts | Planned push/pull interruption is acceptable. Preserve current artifact digests through the transition and retain consistent registry/database recovery. Rebuildability is per artifact: rebuilding source may produce a different digest and will not repair a missing pinned image automatically. |
| Application uploads, including future S3 consumers | Stock SeaweedFS may acknowledge bytes or metadata still buffered in memory. A host/power failure before persistence can lose a successful upload; replication reduces some failures but does not eliminate shared-power/cache loss. Index/metadata inconsistency or a compaction I/O failure can make objects unreadable and require restore/repair. Risk is not restricted to the most recent object or a measured number of seconds. |

A successful PUT or immediate GET is not an independent durable backup. Longhorn
replicas and in-cluster snapshots do not provide a separate failure domain or
force application buffers onto disk. A restore can lose all changes since the
last usable backup; inconsistent data/metadata backups can leave missing objects.
Planned downtime also means failed or delayed uploads, downloads and presigned-URL
requests; applications need visible failure/retry behavior and upload completion
verification. Clients must not silently present an interrupted upload as saved.

Before enabling unique user uploads or cutting over an existing upload consumer,
record whether users retain originals, what can be regenerated, independent backup
coverage/freshness, tested restore time and the owner-approved loss expectation.
Do not advertise guaranteed preservation of acknowledged uploads. For data that
must never lose its only copy, require an independently durable original/copy or
a separately selected stronger storage service; that app is gated, not a reason
to maintain a cluster-wide fork. No new app-side replication framework is part of
this plan. Unknown app requirements are an onboarding gate, not a reason to delay
isolated stock qualification or unrelated best-effort logs.

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
The isolated stock comparison is complete: see the qualification note below.
Neither candidate passed the former strict fault contract. Transition qualification
under the revised best-effort contract is still pending; no production eligibility
is implied merely by accepting the known risks.

| Local change | What it buys | Exit condition |
| --- | --- | --- |
| `durable-ack.patch`: volume data/index barriers and rollback boundaries | Stronger acknowledged-write persistence and error recovery | Remove after stock transition/restore checks and applicable upload-risk review; retain fault failures as documented limits, not mandatory upstream-fix gates. |
| Same patch: synchronous LevelDB2 mutations | Stronger local metadata persistence | Preserve filer metadata and test restore using stock behavior; remove patch-only settings/helper expectations. Do not add a database solely to mimic this patch. |
| `growth-http-fence.patch` | Fences the special native migration | Retire that completed migration workflow; keep ordinary writer fencing for the cutover. No stock growth-fence equivalent is needed for an abandoned procedure. |
| `compaction-sync.patch` | Rejects source sync/close failures | Record the stock I/O-error risk, inventory automatic vacuum/compaction, retain recovery and disk-error alerts. Do not run discretionary cleanup during cutover or claim disabling a job eliminates every compaction path. |
| Loki checkpoint/counter patches | Stronger WAL replay completeness | Accept occasional crash/replay log loss; prove clean flush/exit and compatible stock startup, normal ingestion/query and retention. Preserve old WAL as rollback evidence; no upstream merge is a prerequisite. |

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
  margin. Occasional log loss is accepted, without a measured maximum gap. Agree upload
  loss expectations, backup freshness and restore time per consumer; do not assign
  a blanket disposable-data label.
- [ ] Reconcile plan 0027 and the scratch backlog only after the architecture
  decision. If the continuity goal is retired, mark that gate superseded with a
  successor ADR; never mark the unperformed availability drill passed.

### Unit qualify
Status: pending
Depends on: none
Write scope: Existing SeaweedFS/Loki qualification fixtures and a compact evidence table linked from this plan.
Acceptance: Stock images pass normal S3/Harbor/Loki behavior and clean cutover/rollback checks. Each removed patch has either a procedural replacement or an explicit risk disposition under the revised data contract; no new runtime patch is required.
Verification: Pin upstream release/source/image identities, run the existing failing-before cases on unmodified candidates, test data-format upgrade/downgrade, and check real Harbor registry plus Loki/S3 behavior in isolation. Retain failure output and exact bytes, not only process exit status.
Evidence: [2026-10-20 stock qualification](../notes/2026-10-20-stock-storage-qualification.md) records the completed strict-contract experiment, including passing patched controls. Its stock-promotion blocker was conditional on the former no-regression contract; the revised decision above permits proceeding with normal-operation and transition qualification. The failures remain valid. Production preparation requires the contract and remaining checks; no new passing result is claimed.

- [x] Complete the first bounded stock-release fault comparison and retain its
  failures and passing controls. Do not repeat it solely to pursue zero log loss.
- [ ] Test stock S3 PUT/GET/hash, multipart completion/abort, listing/deletion,
  scoped auth and presigned access needed by apps, plus Harbor digest push/pull
  and Loki ingestion/query/retention. Exercise clean restart with exact object
  readback; distinguish expected crash-loss limits from normal-operation defects.
- [x] Reuse the existing fixtures for sync failures, rollback-boundary errors,
  compaction failures, metadata persistence, and Loki checkpoint/replay. Preserve
  tests that express necessary behavior; retire tests tied only to an abandoned
  internal procedure once the replacement behavior is covered.
- [ ] Retain existing reproductions and patch correspondence as historical
  evidence. Further upstream contribution is optional, separately authorized and
  not on the critical path to stock deployment.

### Unit prepare
Status: pending
Depends on: contract, qualify
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
- [ ] Preserve existing S3 endpoints, bucket ownership and credentials. Inventory
  active app consumers in both repositories; do not provision future uploads
  implicitly. Keep Harbor and Loki attached to SeaweedFS during the transition.
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
  normal read/write checks, degraded storage, ambiguous copy, unexpected allocation
  or time budget. Known isolated fault-test failures alone are not rollback triggers.
  Rollback before admitting new writes where possible; after new writes, preserve
  their authoritative state before restoring any older files or endpoint.
- [ ] Downtime path: drain/flush writers, preserve Loki WAL and bounded buffers,
  stop affected services safely, maintain one node, restore service and verify
  exact bytes. Do not claim uninterrupted availability from post-recovery success.
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
- [ ] Remove patch-only durability policy enforcement and its binary-copy init
  container once stock rollout is verified. Keep only supported settings required
  by the revised contract, owned by the existing bucket provisioner where needed;
  do not recreate the old helper merely to preserve its former guarantees.
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
- [ ] Close only when required normal-operation/recovery gates pass and known
  risks have explicit consumer dispositions. An accepted crash-loss limitation
  does not keep the plan open indefinitely; an unmet upload contract, migration
  defect or untested restore does. Retain these distinctions in the final record.

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

- 2026-10-20: Operator authorized isolated stock qualification before production
  changes. Clean SeaweedFS 4.48 fails volume/index, metadata and compaction failure
  cases; clean Loki 3.7.8 fails checkpoint/recreation replay. All selected Go cases
  pass three times with existing patches in separate control trees. The official
  Loki image lost 8 of 256 acknowledged synthetic entries after forced restart.
  Recorded identities, setup limitations and results in the linked qualification
  note. Stock promotion is blocked; no new patches or production changes made.
  The contract is no longer a prerequisite to isolated qualification, but remains
  required before production preparation. Next: select a released upstream fix
  when available, or evaluate external S3 plus a separate logging replacement;
  external S3 alone cannot fix Loki. No further migration test against these
  failing candidates is warranted.

- 2026-10-20: Operator explicitly retained SeaweedFS S3 for apps, Harbor and
  Loki, accepted planned downtime and occasional log loss, and requested the
  simplest stock-software path. Updated this plan in place as requested. Retired
  external-S3/filesystem migration as the default and removed strict fault-test
  equivalence as an automatic promotion gate. Previous experiment/log entries
  remain historical evidence; no failed test was relabeled. Stock WAL stays on,
  topology stays unchanged during image cutover, and app uploads have explicit
  cache/index/metadata/compaction and backup-loss risks with per-consumer review.
  Redesign From First Principles retained S3 as an application capability and
  shifted qualification to the accepted operating contract. No production work
  was authorized or performed by this update.

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
