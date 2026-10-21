# Plan 0028 — stock runtime cutover completed

Stock SeaweedFS **4.48** and Loki **3.7.8** now serve the existing cluster. Shared
S3 remains available to apps, Harbor and Loki. The runtime/decision revision is
`069da499`; `9de9f031` removes all five tracked runtime patches and 37 build,
fork-test and completed-migration files (3,920 lines). No custom runtime build is
needed. Exact rollback binaries remain available independently of Harbor.

The corrected 60-minute window began **2026-10-21 02:51:16 UTC** (October 20 local
date). All image changes and the controlled Loki restart completed before minute
28. Conservative interruption bounds, measured from the relevant replica-zero
patch to full verified readiness, were **18m39s for S3**, **21m47s for Harbor** and
**23m15s for Loki's initial transition**. They overcount partial service availability
and verification delay. Loki's additional clean restart had a **53-second** conservative interruption
bound, recorded separately in the private journal. Best-effort collectors may have lost logs during these
interruptions; successful sampled queries do not prove uninterrupted collection.

## What passed

- All four exact stock/rollback manifest digests executed on all three storage
  nodes before the outage. Rollback availability was verified independently of
  a laptop cache and the registry being stopped.
- Existing StatefulSet RollingUpdate replaced three masters, three volume
  servers and two filers, one role at a time. All eight old backend processes
  exited zero; no OnDelete strategy, manual Pod deletion or PVC replacement was
  needed. Raft quorum gates remained active.
- All ten SeaweedFS serving processes (including two new S3 gateways) use the
  stock digest. The complete corpus remains **32 native volumes / 64 writable
  copies**, with original replica placement and PVC identities. All **18 original
  Longhorn volumes** are healthy after client recovery.
- Both gateways pass signed, uncached 64KiB seeded GETs and signed byte-range
  checks. Both filers retain the native Harbor/Loki `fsync=true`, replication
  `001` prefix policies. No bucket or credential was removed.
- Harbor passes health/admin login, the original project identities, a known
  historical manifest and all seven blob hashes (**68,298,243 bytes**), plus a
  new scratch robot blob/manifest push/pull and catalogue visibility. Only the
  newly recorded project/repository/robot were removed afterward. The three
  previously missing manifests remain a separate, unrepaired gap.
- Drop's real storage-readiness route and downloads of three objects created
  before the cutover pass through its existing Service. Download lengths match
  their metadata; payloads stay private. This is not a claim that every app
  object was exhaustively compared against a pre-cutover byte baseline.
- Stock Loki uses `/var/loki/wal-stock-0028`, with WAL and shutdown flush enabled,
  its original PVC, unchanged S3 schema and retention. All **100 baseline stored
  canary records** match their hashes; fresh ingestion/query works. After a flush
  and zero-exit stock restart, **25 post-cutover canary hashes** remain readable.
  No old WAL tree was deleted or replayed in stock. The stock image lacks ordinary
  filesystem inspection tools, so no diagnostic Pod was added merely to list
  old directories; preservation follows the retained PVC and absence of deletion.
- Source-owner readiness, original replica/suspend fields, expected templates,
  main-container image IDs and zero container restarts pass after cleanup-source
  promotion. Both webhook lists equal their captured originals. No temporary
  admission exception remains. The cache DaemonSet/policy/Pods and owned
  loopback forwards are removed; backups/snapshots are retained.

## Operational corrections retained

The [attempt record](2026-10-20-plan0028-cutover-attempt.md) preserves the failures
rather than relabeling them as passing preparation:

1. The installed CRD rejects CR S3 replicas zero even though the renderer accepts
   it. The valid CR stayed at two; S3 was stopped through its Deployment while
   its operator was held.
2. The operator also hosts fail-closed admission webhooks. The operator approved
   an exact-object exception in the two webhook configurations, in addition to
   the original maintenance scope. Both exceptions were removed once the operator
   returned. CRD validation remained active throughout.
3. `seaweedfs-config` requires the operator Kustomization's current source
   revision. Restore the already-matching operator first, restore admission,
   then reconcile the operator owner before dependent config; waiting for config
   health while that dependency is held cannot complete.
4. An intentionally detached client volume reports Longhorn robustness `unknown`.
   The two stopped clients each retained their two healthy, non-failed replica
   records; final verification requires all 18 volumes healthy after restart.
5. Explicitly restore CronJob suspension fields. An omitted source field did not
   undo the imperative bucket-provisioner suspension; final field comparison
   caught it and the original `false` value was restored.

The maintained [cutover/rollback runbook](../../docs/docs/runbooks/seaweedfs-stock-cutover.md)
now includes these constraints. These are bounded maintenance operations, not
permanent CRD/operator patches or a new deployment controller.

## Remaining limits

The coordinated encrypted recovery point is **2026-10-20 23:08:03 UTC**, verified
by full file/archive checks and an isolated full Harbor application restore on
stock SeaweedFS. That is a tested point, not monitored daily backup coverage.
Unique app uploads must retain independent originals or remain gated until
independent S3/filer/master backup coverage is running and monitored.
[Plan 0008](../plans/0008-harbor-postgres-backup-strategy.md) tracks Harbor DB
backups only; it does not yet implement that wider upload-recovery coverage. Disaster recovery can lose writes after the newest
usable point; ordinary binary rollback preserves current PVCs instead.

Plan 0028 stays open for its **real planned node-maintenance exercise** and
**seven-day stock observation**. Pod replacements are not a Talos/node exercise.
No node drain/reboot or future automation was authorized or scheduled here.
Keep rollback archives, existing snapshots and old WAL state through observation.
Slot headroom remains eight; no orphan/bucket/capacity cleanup was combined with
the image transition. Existing stock crash/I/O-error limitations remain accepted
limits under ADR 0044, not passing crash-proof guarantees.

Private evidence is in `.private/plan0028-stock-cutover-02-20261020/` in the
canonical checkout: journals/watches, exact image IDs, topology/Longhorn/PVC
captures, restored webhook lists, Harbor results and cleanup IDs, private Drop
readback hashes, stored/fresh Loki ledgers and the clean restart result. The final contract suite passes **507 tests, one skipped**, and Docusaurus builds.
Prior qualification/backup evidence remains linked from Plan 0028.

**Laziness Protocol** deletes the fork/build surfaces while keeping small supported
policy/readiness checks. **Prove It Works** uses real Harbor/Drop/S3 reads and
writes, stored log hashes, restart readback and exact final field comparisons;
it caught the admission, dependency and CronJob gaps. **Outcome-Oriented
Execution** retains verified rollback binaries instead of continuing to maintain
source forks during observation.

## Overnight checkpoint — October 21

Read-only verification at **2026-10-21 12:32 UTC** confirms the same serving Pod
UIDs and zero container restarts since the completed cutover. All 18 Longhorn
volumes remain healthy; all 32 native volumes and 64 writable copies remain.
The 100 historical canary hashes and fresh Loki records still pass. Main and
Flux source revision `350a9b8e` agree, and all four affected Kustomizations are
Ready at that revision. Temporary cache resources remain absent and both webhook
lists retain their originals. This is an overnight checkpoint, not the full
seven-day observation or a real node-maintenance exercise.
