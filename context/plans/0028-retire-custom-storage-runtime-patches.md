---
status: In-progress
opened: 2026-10-20
closed: null
affects: storage
intent: concrete-need
related-adrs: ['0005', '0015', '0032', '0043', '0044']
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

- [x] Harbor, Loki and every discovered S3 consumer run against qualified stock
  releases; no active runtime or deployment job depends on Anton source patches.
- [ ] A real planned node-maintenance exercise passes the selected availability
  contract: orderly maintenance preserves checked object bytes, Harbor artifacts
  and flushed log history; crash/replay log loss is recorded rather than a zero-loss gate.
- [ ] Consistent independent backups pass an isolated restore and actual service
  readback; recovery time and backup freshness meet the accepted per-data contract.
- [x] Normal operations use one policy owner and one maintenance runbook; retired
  migration paths, build scripts and stale instructions are removed from active use.
- [x] Source, Flux revision, applied runtime, stable health and cleanup agree;
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

**Operator-delegated default (2026-10-20):** treat app uploads as potentially unique;
never assume users retain originals. Before treating the cluster as the only copy,
require an independent encrypted backup and demonstrated restore. Target at least
daily backups with the newest usable recovery point no more than 24 hours old.
A restore may lose uploads since that point; this is a recovery objective, not a
guaranteed 24-hour loss bound or protection against every corruption scenario.
Until backup coverage is working and monitored, require a retained independent
original/copy or keep unique-upload onboarding gated. Measure restore time in the
actual rehearsal before promising an RTO. No recurring job, destination or live
maintenance approval is created by selecting this default.

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

### Historical coordination baseline before the stock cutover

**Check cluster health**, thread `01a15287-1d2f-7180-a4a6-ea5808cf1ef8`,
completed its authorized qualification on October 20 and is idle. Its final
report is dated 15:56 CDT. The wait-for-session hold is released; execution units
were then pending, and that planning request authorized no rollout or cleanup.
The execution record below supersedes this baseline for current live state.
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

**Current next step:** complete the real node-maintenance exercise, seven-day
stock observation and upload-protection gate in the units below. Contract,
qualification, preparation and runtime/tooling transition have passed.
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
under the revised best-effort contract passed the bounded local checks described
below; production preparation still needs a fresh coordinated recovery point and
full Harbor restoration. Accepting known risks alone is not production eligibility.

| Local change | What it buys | Exit condition |
| --- | --- | --- |
| `durable-ack.patch`: volume data/index barriers and rollback boundaries | Stronger acknowledged-write persistence and error recovery | Remove after stock transition/restore checks and applicable upload-risk review; retain fault failures as documented limits, not mandatory upstream-fix gates. |
| Same patch: synchronous LevelDB2 mutations | Stronger local metadata persistence | Preserve filer metadata and test restore using stock behavior; remove patch-only settings/helper expectations. Do not add a database solely to mimic this patch. |
| `growth-http-fence.patch` | Fences the special native migration | Retire that completed migration workflow; keep ordinary writer fencing for the cutover. No stock growth-fence equivalent is needed for an abandoned procedure. |
| `compaction-sync.patch` | Rejects source sync/close failures | Record the stock I/O-error risk, inventory automatic vacuum/compaction, retain recovery and disk-error alerts. Do not run discretionary cleanup during cutover or claim disabling a job eliminates every compaction path. |
| Loki checkpoint/counter patches | Stronger WAL replay completeness | Accept occasional crash/replay log loss; prove clean flush/exit and compatible stock startup, normal ingestion/query and retention. Preserve old WAL as rollback evidence; no upstream merge is a prerequisite. |

### Unit contract
Status: complete
Depends on: none
Write scope: This plan, a successor ADR if needed, and the maintenance portions of plan 0027/backlog.
Acceptance: Every consumer has an agreed downtime budget, data-loss contract, backup freshness and recovery target; one selected target architecture and one current storage operation owner are recorded.
Verification: Read current Git/Flux/runtime identities and S3 consumer declarations in both repositories; classify rebuildable images, unique artifacts, retained logs and private application data separately. Confirm which existing maintenance work has completed since the baseline. Record the accepted brief-downtime preference in the successor to ADR 0043 and agree the exact interruption budget.
Evidence: ADR 0044 and the [completed stock cutover](../notes/2026-10-20-plan0028-stock-cutover.md) record the approved 60-minute reservation, planned downtime, best-effort logs, unique-upload protection default and the tested independent recovery point.

- [x] Record the actual current topology, complete native-volume corpus, serving
  copies, physical free bytes, slots, active writers and in-flight operations.
  Use read-only APIs first; any exec/probe follows the repository approval boundary.
- [x] Agree a 60-minute reservation, no new image steps after minute 40, and
  20 minutes reserved for recovery. Occasional log loss is accepted without a
  measured maximum gap. Uploads use the independent-copy/24-hour usable backup
  default; no production disaster-recovery RTO or disposable-upload label is implied.
- [x] Reconcile plan 0027 and the scratch backlog only after the architecture
  decision. If the continuity goal is retired, mark that gate superseded with a
  successor ADR; never mark the unperformed availability drill passed.

### Unit qualify
Status: complete
Depends on: none
Write scope: Existing SeaweedFS/Loki qualification fixtures and a compact evidence table linked from this plan.
Acceptance: Stock images pass normal S3/Harbor/Loki behavior and clean cutover/rollback checks. Each removed patch has either a procedural replacement or an explicit risk disposition under the revised data contract; no new runtime patch is required.
Verification: Pin upstream release/source/image identities, run the existing failing-before cases on unmodified candidates, test data-format upgrade/downgrade, and check real Harbor registry plus Loki/S3 behavior in isolation. Retain failure output and exact bytes, not only process exit status.
Evidence: [Strict fault qualification](../notes/2026-10-20-stock-storage-qualification.md) remains historical evidence of known risks. [Revised-contract qualification](../notes/2026-10-20-stock-storage-revised-qualification.md) records stock app S3 behavior, scoped credentials, presigned access, synthetic cold restore and Loki clean transition results. The later production-shaped restore and live cutover now pass in the completed execution record; isolated qualification alone was not rollout approval.

- [x] Complete the first bounded stock-release fault comparison and retain its
  failures and passing controls. Do not repeat it solely to pursue zero log loss.
- [x] Test stock S3 PUT/GET/hash, multipart completion/abort, listing/deletion,
  scoped auth and presigned access, plus synthetic cold restore and Loki's clean
  patched-to-stock transition with preserved old WAL.
- [x] Complete the multi-component patched → stock → patched rollback → stock
  rehearsal with both-gateway object checks, native two-copy checks, Harbor registry
  blob/manifest checks and 8,000 exact Loki records per hot/cold application stage.
- [x] Verify stock retention with pre-aged records and actual S3 deletion:
  11 records/chunks become the four expected survivors under 24h/336h/720h policy.
  Verify clean Loki stock-to-patched rollback with a fresh WAL: 512 final records
  survive, both earlier WAL trees unchanged. These are isolated tests; full Harbor
  recovery subsequently passed; the seven-day production observation remains open.
- [x] Reuse the existing fixtures for sync failures, rollback-boundary errors,
  compaction failures, metadata persistence, and Loki checkpoint/replay. Preserve
  tests that express necessary behavior; retire tests tied only to an abandoned
  internal procedure once the replacement behavior is covered.
- [x] Retain existing reproductions and patch correspondence as historical
  evidence. Further upstream contribution is optional, separately authorized and
  not on the critical path to stock deployment.

### Unit prepare
Status: complete
Depends on: contract, qualify
Write scope: Selected stock image pins/configuration, one cutover runbook, existing backup/recovery tooling and any separately approved migration manifest.
Acceptance: The exact candidate, consistent restore rehearsal, writer fences, rollback and measured maintenance budget are reviewable before live approval; bootstrap access does not depend solely on the Harbor instance backed by this storage.
Verification: Restore the selected backup into isolated storage and read real object/log contents; rehearse cutover and rollback on copies using the actual image architecture. Verify images are obtainable through a tested independent source/cache and current credentials remain scoped.
Evidence: [Verified backup/Harbor restore](../notes/2026-10-20-plan0028-backup-window.md), [recovery/retention qualification](../notes/2026-10-20-plan0028-recovery-and-retention.md), and the [completed stock cutover](../notes/2026-10-20-plan0028-stock-cutover.md). Exact images executed on all three live nodes, final fields passed admission, and the approved owner/webhook/dependency corrections were exercised and restored. Daily monitored backup coverage remains a separate open protection gate.

- [x] Verify retained encrypted archive identities and a stock isolated restore
  of historical volume/filer data: 271 file hashes, expected buckets and exact
  seeded object bytes. This is not the current coordinated Harbor recovery point.
- [x] Use an independent consistent backup of data, filer metadata and required
  master state, Harbor database/roles/recovery configuration and Loki WAL state:
  six exports / 414 file hashes verified, full isolated Harbor restore on stock
  SeaweedFS passed. This does not recover already-missing manifests or implement
  daily backups; refresh the checkpoint before a later cutover.
- [x] For stock SeaweedFS, keep current PVC identities, metadata paths and
  placement. Remove patch-only configuration only when the stock replacement's
  semantics are verified. Keep supported fsync settings where applicable.
- [x] Preserve existing S3 endpoints, bucket ownership and credentials. Inventory
  active app consumers in both repositories; do not provision future uploads
  implicitly. Keep Harbor and Loki attached to SeaweedFS during the transition.
- [x] Prepare and exercise the cutover/rollback runbook. Use the existing
  StatefulSet RollingUpdate while operator and S3 are held; no OnDelete strategy
  or manual Pod deletion. CR replicas zero is rejected by admission. The exact
  webhook exception, owner-before-dependent reconciliation and explicit CronJob
  restoration are now recorded from live evidence.
- [x] Complete the approved backup-only capture, sequential clone export and
  isolated full Harbor restore. Production recovery/cleanup finished at minute
  53.42 of the 60-minute reservation; conservative service interruption totaled
  13m24s across three attempts. That backup window restored original images/PVCs/owners; the later stock cutover
  changed only the reviewed runtime/config fields.
- [x] Keep the three currently missing Harbor manifests recorded as unrepaired
  gaps without deleting or relabeling them. Their pre-window status is unknown,
  and no current source reference was found. Repair/rebuild is a separate data
  operation; the image change must preserve every artifact readable at baseline.
- [x] Refresh identities, independent image availability and chart/contracts
  validation on the eventual release revision; publish the contract/ADR decision,
  obtain and execute approval for the exact stock cutover, including the temporary
  operator/webhook boundary. Use the verified independent
  checkpoint only while it is within the delegated 24-hour freshness contract;
  later writes remain outside disaster recovery. Refresh first if an app requires
  it or that point expires. Backup authorization does not authorize image rollout.

### Unit execute
Status: running
Depends on: prepare
Write scope: Approved GitOps runtime/configuration cutover and exact maintenance resources recorded in the reviewed runbook.
Acceptance: The selected maintenance contract passes against the actual owning node, all preserved data checks pass, and full recovery has no unmanaged drift or temporary residue.
Verification: Verify source revision through Flux and applied image digests, historical Harbor pulls, new push/pull, old/new Loki records and each private consumer. Perform one approved node-maintenance exercise, measure interruption/recovery, and inspect controllers, replicas, errors and cleanup after restoration.
Evidence: [Completed stock cutover](../notes/2026-10-20-plan0028-stock-cutover.md). Source/runtime checks, old/new Harbor reads/writes, real Drop downloads, both-gateway reads/ranges, native corpus, historical/fresh Loki records and a clean stock restart pass. The real node-maintenance exercise remains unperformed; Pod replacement does not satisfy it.

- [x] Roll one causal change at a time; stop on identity/hash mismatch, failed
  normal read/write checks, degraded storage, ambiguous copy, unexpected allocation
  or time budget. Known isolated fault-test failures alone are not rollback triggers.
  Rollback before admitting new writes where possible; after new writes, preserve
  their authoritative state before restoring any older files or endpoint.
- [ ] Downtime path: drain/flush writers, preserve Loki WAL and bounded buffers,
  stop affected services safely, maintain one node, restore service and verify
  exact bytes. Do not claim uninterrupted availability from post-recovery success.
- [x] Change Loki in a separately verified phase within the approved budget,
  or its own window if time runs short. Follow the tested drain/complete flush/clean
  exit and WAL compatibility procedure; do not plain-revert its image against
  incompatible counter history or discard old WAL directories after an unclean stop.

### Unit simplify
Status: complete
Depends on: prepare
Write scope: Retired custom image builders/patches, policy helpers, readiness/probe configuration, storage documentation/skills and completed task records.
Acceptance: Active references to custom SeaweedFS and Loki runtime builds are zero, one owner controls each policy, and routine maintenance needs no private one-off migration scripts.
Verification: Search source and rendered manifests for old image/build/patch references, run contracts:validate and the documentation build for touched surfaces, inspect live image identities, and rehearse the concise runbook with its retained behavioral checks.
Evidence: [Completed stock cutover](../notes/2026-10-20-plan0028-stock-cutover.md), runtime revision `069da499` and cleanup revision `9de9f031`. Cleanup followed verified live stock operation; it does not depend on the later hardware-maintenance/observation gates. Every tracked runtime patch and custom build path is deleted; rollback binaries remain.

- [x] Delete custom runtime build paths and their now-unused implementation
  fixtures after live stock verification. The prepared cleanup removes 37 files
  and all five runtime patches. Exact off-cluster rollback OCI archives are
  verified, so observation requires retaining those binaries and old WAL trees,
  not maintaining build/patch sources. Historical tests/failures remain in Git.
- [x] Audit policy ownership: the existing fsync/001 prefix helper uses supported
  upstream commands, not patched semantics. Keep that small owner and its tests;
  its binary-copy init container now selects the pinned stock weed image. The
  bucket provisioner continues to own bucket/prefix lifecycle without duplication.
- [x] Retain the three small Raft readiness sidecars. Actual CRD/renderer checks
  show probe overrides change timings only, not the HTTP handler. A candidate
  native handler change failed the render gate and was removed. Stock healthz
  passes full/two-master quorum and rejects lost quorum with HTTP 503; no new
  operator patch or migration is justified merely to remove three containers.
- [x] Keep a small real S3 read check, useful alerts and persistent filer metadata.
  Disable the retired Iceberg listener explicitly (`-port.iceberg=0`); stock 4.48
  otherwise defaults to 8181. No Service or active repository consumer was found.
  Keep legacy bucket data/credentials untouched. Refresh the stale lakehouse
  skill and node runbook; retain historical evidence in Git.
- [x] Keep Harbor active-image protection and recovery checks. Avoid adding
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

- [ ] Verify independent-copy protection for current unique uploads. Automate and
  monitor independent S3/filer/master backup coverage before relying on the
  cluster as their sole copy; Plan 0008 covers the Harbor DB component only.
  A tested one-time point does not establish a continuing 24-hour freshness SLA.

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

- 2026-10-20: Committed the revised contract as `fc2e73d2`, then ran isolated
  qualification. Stock S3 presigned access, bucket isolation, multipart abort and
  synthetic cold restore passed. Four SeaweedFS cutover/rollback application
  stages passed, each with 68 MiB registry blobs and 8,000 hot/cold Loki records;
  historical registry digests survived the final stock return. Loki's separate
  clean patched-to-stock transition preserved old WAL and all 448 final records.
  No new ordinary-operation blocker found. Recorded test/setup/parallel-teardown
  limits and remaining production-shaped restore, retention, upload-contract and
  runbook gates in the revised qualification note. All owned lab resources were
  removed. Prove It Works kept local protocol success distinct from deployment
  readiness; no production action or new runtime patch was performed.

- 2026-10-20: Worked remaining gates without production mutations. Verified
  current ready workloads and normal Flux ownership; confirmed Harbor CNPG has
  no configured backup/plugin and Longhorn's backup target is empty. All eight
  encrypted archives remain byte-identical. Restored five historical data/filer
  archives (271 files, 31,140,434,016 bytes) into isolated stock SeaweedFS and read
  the exact probe and bucket inventory. Stock retention physically deleted seven
  expired chunks and kept four expected records; Loki's fresh-WAL image rollback
  preserved all 512 records and both prior WAL trees. Marked bounded qualification
  complete and preparation blocked on fresh coordinated Harbor DB/S3 capture and
  actual Harbor restore, plus the pending upload contract. Prepared the runbook,
  stock source/ADR drafts and split capture packet; no deployment file was changed
  and no live capture/clone/restart was performed. Prove It Works required service
  readback and object deletion; Laziness Protocol reused the controller-freeze procedure
  and the encrypted export path rather than introducing a new backup platform.

- 2026-10-20: Operator delegated the app-upload policy to the recommended
  default. Treat uploads as potentially unique; require independent encrypted
  backup and verified restore before relying on the cluster as the only copy.
  Set daily cadence / at-most-24-hour usable-backup-age as the target, with loss
  since the recovery point explicit and restore time still to be measured.
  Backup infrastructure and the live maintenance window remain unapproved and
  unimplemented; this resolves the policy choice, not its implementation gate.

- 2026-10-20: Operator approved and started the backup-only window (at most 60
  minutes); preparation committed as `b572c38b`. Six coordinated snapshots and
  encrypted Harbor database/roles/recovery captures completed. Original patched
  service, templates, PVC UIDs and automation were restored at 23:14:09 UTC;
  Harbor health/admin/three-project checks and Loki readiness passed. Snapshot
  exports and full isolated Harbor restore remain in progress; no stock cutover
  is authorized. [Window evidence](../notes/2026-10-20-plan0028-backup-window.md).

- 2026-10-20: Backup-only operation completed within its 60-minute reservation;
  independent encrypted exports cover 414 files / 62,211,982,066 bytes. All file
  hashes and gzip integrity checks passed, all temporary cluster resources were
  removed and original service/ownership/PVC identity checks passed. Full Harbor
  restore on pinned stock SeaweedFS 4.48 passed database/roles/catalogue, login,
  portal, a live-verified manifest plus seven blobs (68,298,243 bytes), and new
  robot-authorized push/pull. Repeat lab recovery took 122.4 seconds with cached
  images, not a production RTO. Three earlier-selected manifests are also missing
  in current production; their pre-window status is unknown. Retain that data gap
  and its separate disposition gate. Prove It Works required actual Harbor reads
  and writes; Attack the Premise corrected the observer; Laziness Protocol kept
  the existing export/topology model. No production stock cutover occurred.

- 2026-10-20: Prepared the stock release on `codex/stock-storage-simplification`
  from deployed `886fbd6a`, preserving unrelated checkout work. ADR 0044 records
  the operator's settled downtime/S3/upload contract. Normal operator rolling
  updates with S3/writers fenced replace manual OnDelete/template/eviction work.
  Current status has 32 volumes / 64 writable copies, 8 free slots and 18 healthy
  Longhorn volumes. Exact stock/rollback image archives and fresh Harbor restore
  evidence remain available. Prepare 37 source removals / five runtime patches;
  publish cleanup only after live stock checks, retaining rollback binaries
  through observation instead of maintaining build sources. Keep supported native
  fsync policy and Raft guards. Renderer evidence rejected a probe-handler
  override; stock defaults require explicit Iceberg port zero. Prove It Works
  caught both assumptions; Laziness Protocol removed custom rollout steps;
  Outcome-Oriented Execution removes unused fork tooling without waiting to
  rebuild it. No live rollout or publication has occurred in this preparation.

- 2026-10-20: Executed the approved cache and writer-fence preflight. All four
  images ran on all three nodes, historical Harbor blobs and stored Loki records
  passed. Stopped before publication/images when live CRD admission rejected S3
  replicas zero. The renderer test had missed this constraint. Prepared a bounded
  operator-held RollingUpdate correction and proved final CR/config/template
  changes with API-server dry runs; requested approval for the changed boundary.
  Original runtimes, templates, owners and PVCs were restored; conservative writer
  interruption was 5m41s, with S3 never stopped. Harbor old/new reads/writes, stored
  and fresh Loki records, native corpus and all 18 Longhorn volumes pass; temporary
  cache and scratch Harbor objects are removed. No release was promoted.

- 2026-10-20: Completed the approved stock cutover and clean Loki restart.
  SeaweedFS 4.48 and Loki 3.7.8 use upstream images; revision `9de9f031` removes
  all five runtime patches and 37 build/fixture/migration files. Original PVCs,
  replica/suspend fields, webhook lists and native 32/64 corpus are verified;
  all 18 Longhorn volumes are healthy. Harbor old/new blob operations, three real
  Drop downloads, 100 historical Loki hashes and 25 stock-restart hashes pass.
  The revised execution also resolved the stopped-operator webhook dependency,
  Flux dependency order and one retained CronJob suspension. No admission exception
  or cache/scratch resource remains. Plan stays open for the real node exercise,
  seven-day stock observation and the independent-upload protection gate; daily
  monitored S3/filer/master backups remain a separate protection follow-up;
  Plan 0008 tracks the Harbor DB component only. See the completed execution record.

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
