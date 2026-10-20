# SeaweedFS durable acknowledgment review and rollout

## Current state

The initial amd64 candidate passed its stated fault/rehearsal checks, but a later
independent review found a blocking rollback-boundary bug. That image is
superseded and must not be published. The revised boundary fix is undergoing
qualification. Source, fixtures and the policy helper were committed as `f7f629a0` and pushed to
`codex/qualify-seaweedfs-durability`. All 502 repository contract tests passed
(one skipped). Publication, fresh production backups, GitOps rollout and
production acceptance remain pending. Main has not been advanced by this task.

The operator authorized review, amd64 build, upgrade/rollback rehearsal, commit,
push, fresh backups and staged deployment. Another active cluster-maintenance
task currently owns SeaweedFS's Flux/operator pauses and S3 outage; this task has
made no production mutation and must wait for those controls to be restored.

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
- The exact revised image's HA upgrade/rollback/re-upgrade rehearsal is running.

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
superseded v3 candidate. None is currently eligible for publication; the
revised patch must pass fault, amd64 and rehearsal checks with a new identity.
No image has yet been published by this task.

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
