# SeaweedFS durable acknowledgment review and rollout

## Current state

All ten production components run the reviewed amd64 binary. PR #522 deployed
the pinned source at `080ae85e`. Fresh encrypted exports passed
every file hash and complete gzip CRC/end-of-stream checks. Runtime rollout,
bucket policy activation, final production acceptance and cleanup passed. The
copy-budget correction in PR #524 passed all 506 contract tests (one skipped).

The source/fixture helper first landed as `f7f629a0`; independent review found a
blocking rollback-boundary bug in the initial candidate. The revised fix in
`13649abb` passed fault and HA qualification before publication. Superseded
candidate identities below remain ineligible for deployment.

The operator authorized review, amd64 build, upgrade/rollback rehearsal, commit,
push, fresh backups and staged deployment. Another active cluster-maintenance
task finished its recovery and cleanup before this task acquired its own backup
holds. Volumes, filers, S3 gateways and masters were replaced in that order, with
followers before the master leader. All ten image manifests and embedded binary
hashes matched the qualification identity. The staged durability policy CronJob
is now eligible for activation because every component passed runtime checks.

## Review findings and disposition

The initial candidate's acknowledged-write barriers passed its original
all-unflushed-bytes-lost model, but a critical pass found a missing ordering case:
the OS can persist an unsynced index append independently before data sync fails.
A deterministic reproduction made the previous acknowledged object unreadable
and loaded the volume read-only with an index reference beyond the data file.

The first proposed recovery ordering synced an appended restored mapping before
truncating data. That restored object readability but retained a historical
out-of-range index entry. Expanded tests correctly rejected the read-only result.

**Act on, resolved:** inline recovery now uses the existing batch rollback
routine instead of a separate implementation. It restores mappings, truncates
and syncs the index, then truncates and syncs data. Failed recovery fences the
volume. Data and index sync errors share the same recovery path. This removes
the old duplicate inline rollback implementation and preserves map metrics and
append timestamps. Successful writes still require both barriers.

**Act on, resolved:** the upstream inline-recovery success test now injects a
one-shot sync error. Persistent recovery sync errors intentionally fence the
volume, and the new qualification fixtures explicitly verify that behavior.
Changing the test's fault setup preserves its original positive recovery check;
it does not relax recovery assertions to hide a failure.

The retained new fixture exercises batch/inline, new/overwrite, and one-shot/
persistent data-sync failures with an independently persisted index append.
Recovery must retain exact previously acknowledged bytes and load without an
index-past-data read-only condition. Directly failed writes are never acknowledged.

The first review was a critical source-and-runtime pass by the implementing agent.
A later independent reviewer reproduced a second blocker: `IndexFileSize()`
returns zero when `Stat` fails. Both batch and inline recovery could use that
invalid boundary to truncate an existing index to zero, losing an earlier
acknowledged mapping. The retained regression failed both paths on the old
candidate. The revised patch obtains a fallible index position under the mapper
lock and rejects every affected request before any data/index mutation when the
position cannot be established. The sorted-file mapper also implements the
fallible boundary through its file pool.

Qualification covers successful explicit data/index barriers and completed
recovery from injected sync failures. It does not establish crash atomicity for
in-flight overwrites: an index append can persist before its data append and
before recovery runs; a crash in that interval may leave a read-only volume and
require index repair to recover an earlier acknowledged mapping.
Remaining limitations include torn
sectors, directory-entry reordering, hardware caches that lie about sync,
non-fsync deletes, and asynchronous filer metadata peers.

## Revised boundary fix evidence

- Patch SHA-256: `b00fd3c71917b23bb6836ee4e505c1c8775cdcbb6c210592f89e66604474c277`.
- Binary SHA-256: `09def5fc4c367ff96ea5806e377f1cc79f94cc099c818b50949904f4d38ddaf6`.
- Local amd64 image: `sha256:6636cc129d5a27328999eda8d9f424772da01831fbd7667781e102b433651efd`.
- Full storage and LevelDB2 suites passed.
- All 43 fault cases passed five race-enabled repetitions (215 checks).
- All 43 fault cases passed three Linux/amd64 repetitions (129 checks).
- Stock baseline failed 31 of 43 cases; 12 controls passed.
- Independent review reproduced the old destructive rollback in both paths,
  found no remaining blocker in the revised boundary fix, and independently
  passed its three new cases three times (nine checks).
- The exact revised image passed the ten-component HA stock → patched → stock →
  patched rehearsal. Four stages verified 8,000 exact Loki records each, with
  hot and empty-local-filesystem cold reads; Harbor blob/manifest digests, both
  S3 gateways, fresh writes, Raft quorum and two-copy placement all passed.
  Qualification completed at 2026-10-20 02:22:41 UTC; lab cleanup completed at
  02:23:01 UTC with no owned containers or networks remaining.
- Revised archive: 752,218,112 bytes, SHA-256
  `ba4dc80c04808590a92d2d75e457651e93236a34a49902473dfe708b1f94b97c`.
  Account verification preceded archive creation; tar listing, amd64
  configuration and patch label matched.
- Expected archive manifest digest:
  `sha256:5ecf8cd3027e48c530ac360514fa21e4d02f00f37294b7238f8e64d3aaf50fcb`.
  This exact digest was published to
  `192.168.1.106/library/seaweedfs-durable:4.48-durable1` and its remote amd64
  configuration/patch label verified. Temporary library pull/push robot 56 was
  revoked; the temporary 1Password item, auth files and localhost tunnel were
  removed. The two run-owned image archives were removed after retaining their
  identities. All three nodes independently verified the embedded binary hash.
- A cold anonymous Harbor pull verified all 13 OCI objects (315,235,750 bytes).

## Fresh backup progress

Five original PVC identities were captured and preserved. With S3 and both filer
writers stopped, five retained CSI snapshots became ready.
All 241 files across the five restored clones matched the source-before and
source-after manifests (about 31.45 GB). Three encrypted master archives also
decrypted and matched all file hashes. Source reader Pods were removed by UID
before filers restarted, preserving normal volume attachment.

The original replica counts, HelmRelease and Flux controls were restored;
the backup service outage lasted 439 seconds. All ten SeaweedFS Pods, all 23
Longhorn volumes including temporary clones, and controller ownership were
healthy afterward, with no active storage/log-loss alert. Loki had two queued
flushes immediately after restoration; require that backlog to drain before
another planned interruption. Encrypted clone export and decrypted file-hash
verification completed for all five exports: 241 files, 31,454,082,494 source
bytes and 23,877,631,676 encrypted bytes. Archive hashes and gzip integrity also
passed independently. The five reader Pods and temporary clone PVCs were removed
by recorded UID; original PVCs and five retained snapshots are preserved.

A later helper review found that the remote shell invocation lacked its stdin
forwarding flag, so the intended native vacuum disable/enable commands were not
forwarded. Do not treat those commands as verified evidence. Complete
source-before, source-after and restored-clone file equality independently
establishes the captured backup state despite this missing fence. The helper now
forwards stdin, retains stderr and rejects shell errors before reuse. No native
volume copy or vacuum command was run by this helper during the backup.

The initial v0 encrypted export decrypted but had a truncated gzip stream and
was rejected. A separately retained retry, with an explicit stdout flush and a
brief process-exit delay, passed every file hash. The failed archive remains
evidence and is not an eligible backup. Both filer exports and v2 have also
passed verification, as did v1. The failed export's stderr identified an abnormal
Kubernetes exec WebSocket closure. A command exit or successful decryption alone
was never accepted as backup completion.

## Production runtime checkpoint

The first controller-owned policy Job, `seaweedfs-durability-ensure-29874443`,
failed before its main container started: both init attempts were OOM-killed while
copying the 212 MiB binary under a 32 MiB memory limit. No bucket policy command
ran. An isolated Job with a 384 MiB init limit and 256 MiB request copied the
exact binary successfully and completed native RPC readbacks from both filers
under the unchanged 128 MiB main-container limit. The source budget is corrected;
the builder now checks actual binary size against copy RAM and volume capacity.
Regression cases cover the original insufficient memory and volume limits.
Failure and passing Job evidence are retained privately. The corrected policy
execution and final acceptance subsequently passed as recorded below.

At 2026-10-20 03:21:03 UTC all ten patched Pods and all 18 original Longhorn
volumes were healthy, with no active storage/log-loss alert and Loki flush queue
zero. Original update strategies, S3 deployment state, operator replicas and
Flux/HelmRelease ownership were restored. No Pod was replaced by that restoration.

Fresh 1 MiB Harbor and Loki objects each had two byte-identical native copies on
different nodes (volumes 52 and 50); both test keys were deleted and confirmed
absent. A new anonymous Harbor cold pull verified all 13 OCI objects and
315,235,750 bytes. Loki returned all 4,981 numbered records across the S3 outage,
with no missing, unexpected or duplicate records. All 1,800 historical records
also remained queryable before runtime replacement. Final checks extended these
results through policy activation and cleanup, as recorded below.

Two private-helper assertions were corrected during rollout: Kubernetes omits a
false `paused` value and may omit default `maxUnavailable: 1`. The API's documented
default was checked before comparing strategies semantically. Both pauses were
fail-closed; evidence and recovery are retained, and no extra image replacement
or data-file repair was performed.

## Final production acceptance

Runtime source landed in [PR #522](https://github.com/wcygan/anton/pull/522), policy
activation in [PR #523](https://github.com/wcygan/anton/pull/523), and the qualified
copy budget/build guard in [PR #524](https://github.com/wcygan/anton/pull/524).
Flux applied the corrected code revision `5fec6992`. The successful
`sw-dur-policy-apply-20261020` Job used that CronJob template; independent native
readbacks from both filers confirmed exactly the two intended bucket rules with
`fsync=true` and replication `001`. Serving Pod UIDs remained unchanged.

At 03:50 UTC, all ten SeaweedFS Pods were Ready without a new restart; all 18
Longhorn volumes and 36 replicas were healthy. Original PVC UIDs were preserved.
All update strategies and controller replicas were restored; the original absent
suspension fields were restored as absent. The three masters agreed on their
leader, and both filer mounts retained `/data/filerldb2` with `sync=true`.

After policy activation, fresh Harbor and Loki objects passed exact GETs through
the service and both individual S3 gateways. Both native copies were read and
hash-verified directly on different nodes. Both test objects were deleted and
confirmed absent through every gateway. A final empty-workspace Harbor pull
verified all 13 OCI objects and 315,235,750 bytes.

All 8,838 numbered production-test records and all 1,800 historical records were
queryable, with no missing, unexpected or duplicate records. A final Loki flush
persisted 77 additional chunks without a new flush failure and drained to queue
zero. Fourteen retry failures occurred during the planned backup service outage
and its recovery at 02:32–02:39 UTC; the counter stayed unchanged afterward.
This is bounded test-record evidence, not a census of every application log.

All 19 matching Prometheus alert rules were healthy and inactive; all three Loki
log-rule groups evaluated freshly without errors. No storage or log-loss alert
fired from the runtime-rollout gate at 03:01:51 UTC through post-cleanup
verification. Current storage/log-loss alerts were empty.

Cleanup completed at 03:52:16 UTC. Nine run-owned Jobs, including the resolved
first failed policy run, their Pods and the pre-pull DaemonSet were absent.
Failure evidence and successful replacement proof were saved before removal.
The five temporary clone PVCs and their readers were absent; five retained CSI
snapshots and eight verified encrypted archives remained. Publishing robot 56
was revoked; its temporary 1Password item, local auth files and tunnel were gone.

The daily Harbor check independently verified the scheduled 01:30 UTC run:
policy 1/execution 708 and policy 2/execution 709 succeeded with `dry_run=false`;
the exact proof survived the 03:02:46 UTC Flux reconciliation. Its wider alert
window was classified failed because historical read-only alerts fired during
the [01:50–02:15 maintenance and recovery](2026-10-20-seaweedfs-migration-abort.md).
The alerts cleared before this runtime rollout. Dated evidence and the outcome
fingerprint are retained under `.private/harbor-retention-fix/daily/`.

Legacy singleton data was not migrated. In-flight overwrite crash atomicity,
torn sectors, directory ordering, hardware sync honesty, non-fsync deletes and
asynchronous filer peers retain the qualification limits described above.

The independent pass covered source, lock ordering, capability inheritance,
boundary fault execution and six Python policy tests. It did not independently
run the full suites, race checks, Docker or production acceptance.

## Superseded build and qualification evidence

- Upstream: `530be3e37337488ecc34d58441e0bc476e121c93` (4.48).
- Patch SHA-256: `2199142cfbccf6bab93bac5764774e71d78a8caf0cd7f1fe9b133fb8e64c05c5`.
- Go: 1.26.7, CGO disabled, Linux/amd64, trimmed paths, automatic VCS stamping disabled.
- Binary SHA-256: `1042a463d9ed43334746ddc54392e45a18f7dbca67cd3b5223034b8d0fdbdfef`.
- Local image: `sha256:b94f71e2d6b3f16acced438717e9cb7f0a07b7ba7933984af7bc94dc0d2b0ce5`.
- Archive: 752,206,848 bytes, SHA-256 `5336ee242f70005889734bd090eb1b73a553afea7d26d5dd459c1d2a4ee6f918`;
  listing and embedded Linux/amd64 configuration verified.
- Crane's archive manifest digest is
  `sha256:3decbb4e989cab0a2e720bd24c7bccea69c32dff1f7da98fd570874a98803033`.
  This is an expected publication identity, not a verified remote image yet.
- Full upstream storage and LevelDB2 package suites passed.
- All 40 fault cases passed five race-enabled repetitions (200 checks).
- All 40 fault cases passed three Linux/amd64 repetitions (120 checks).
- The expanded stock baseline failed 28 of 40 cases; its failures are retained.
- HA stock → patched → stock rollback → patched passed across all ten components,
  with application checks at every complete stage and object checks after every
  component replacement. Each of four stages verified 8,000 exact Loki records,
  then all records again with a new reader and empty local filesystem.
- Harbor Registry verified 68 MiB of layer digests and an OCI manifest at every
  stage. Additional fresh S3 objects and multipart writes exercised mixed versions.
- Both gateways, Raft quorum, native two-copy placement, deleted-object absence,
  range reads, HEAD and listings were verified. No format migration was required.
- The bounded bucket-policy helper passed its focused tests and a real HA-lab
  apply/readback against both filer endpoints.

Private evidence remains under `.private/seaweedfs-durability-qualification/` and
`.private/seaweedfs-durability-rollout/` in the primary checkout. Failed review
attempts and superseded local builds are retained. The build above is the
superseded v3 candidate. These builds are ineligible for publication; only the
revised identity above passed the expanded checks.
These superseded images were never published by this task.

The earlier performance table belongs to the initial candidate and its recorded
image IDs. It is historical evidence, not a latency guarantee for this revised
patch or production Longhorn hardware.

## Deployment contract

Keep the existing bucket-creation job as the lifecycle owner. A separate bounded
policy helper converges only Harbor/Loki prefix fsync and replication, then reads
both filers back and refuses missing, weak, duplicate or read-only policy results.
It does not change credentials, bucket lifecycle, TTL, WORM, quotas or data.

Preserve the LevelDB2 directory `/data/filerldb2` and its eight partitions. Enable
local synchronous writes only with the patched filer binary. Do not introduce a
new empty metadata store or treat filer peers as a synchronous quorum.

Wait for the other maintenance task's explicit operational completion and verify
actual controller restoration, writable replicated topology and healthy data
paths. Re-fetch Git intent before each landing. Do not advance main during its
revision-bound maintenance procedure.

Fresh backups must fence S3/filer writers and vacuum, retain original PVC UIDs,
capture five CSI snapshots plus master state, restore isolated clones, and export
encrypted archives outside the cluster with every decrypted file hash verified.
Snapshots alone are not independent backups. Longhorn currently uses its normal
system-sync snapshot path with filesystem freezing disabled; with application
writes quiesced, verify source and restored-clone hashes before acceptance.
See the [Longhorn 1.11.1 snapshot settings](https://longhorn.io/docs/1.11.1/references/settings/#freeze-filesystem-for-snapshot).

Publish through a scoped robot and verify the remote amd64 configuration/digest.
Stage StatefulSets with controlled updates, observe each component transition,
retain the old image and a concrete rollback path, and enable the prefix policy
only after patched volume and filer runtime is verified. A failed rollout must
not silently promise strong durability after reverting to the stock image.

Operator 1.0.39 exposes `statefulSetUpdateStrategy` in its CRD/accessor, but its
master, filer and volume StatefulSet constructors hardcode RollingUpdate and
partition zero. The reconcile paths update replicas and pod templates without
overwriting an existing StatefulSet's update strategy. Setting the CR field alone
therefore does not establish a rollout hold. Use an explicitly retained temporary
live OnDelete strategy on the three existing StatefulSets, verify it survives
operator reconciliation before publishing new pod templates, replace one pod at
a time with UID and disruption-budget checks, then restore each captured original
strategy. Do not add ineffective CR fields or leave temporary controls behind.

Acceptance requires the intended Git revision applied by Flux, stable readiness,
original PVC identity, all Longhorn volumes healthy, two native copies on distinct
nodes where promised, verified Harbor push/pull and old digests, historical and
fresh Loki records, fresh S3 GET probes, healthy alert evaluations and no active
storage or log-loss alerts after the observation window. Restore all pause and
update controls and remove temporary credentials, listeners and diagnostic objects.

## Principles that changed decisions

- **Sequence Work into Verifiable Units:** stop publication at a newly failing
  recovery case, and defer production until the other storage owner releases it.
- **Prove It Works:** test the actual amd64 image through upgrade and downgrade,
  and require exact object/record readback rather than container readiness alone.
- **Encode Lessons in Structure:** reject a built binary that exceeds the
  policy Job's copy-memory or tool-volume budgets before creating an image;
  retain the full successful resource-constrained Job as runtime proof.
