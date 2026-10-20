# SeaweedFS durable acknowledgment review and rollout

## Current state

Review and isolated amd64 qualification passed. Publication, fresh production
backups, GitOps rollout and production acceptance are pending. This record will
be updated with actual delivered state rather than treating preparation as rollout.

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

Review was a critical source-and-runtime pass by the implementing agent; it is
not independent human or agent approval. Remaining limitations include torn
sectors, directory-entry reordering, hardware caches that lie about sync,
non-fsync deletes, and asynchronous filer metadata peers.

## Exact build and qualification evidence

- Upstream: `530be3e37337488ecc34d58441e0bc476e121c93` (4.48).
- Patch SHA-256: `2199142cfbccf6bab93bac5764774e71d78a8caf0cd7f1fe9b133fb8e64c05c5`.
- Go: 1.26.7, CGO disabled, Linux/amd64, trimmed paths, automatic VCS stamping disabled.
- Binary SHA-256: `1042a463d9ed43334746ddc54392e45a18f7dbca67cd3b5223034b8d0fdbdfef`.
- Local image: `sha256:b94f71e2d6b3f16acced438717e9cb7f0a07b7ba7933984af7bc94dc0d2b0ce5`.
- Archive: 752,206,848 bytes, SHA-256 `5336ee242f70005889734bd090eb1b73a553afea7d26d5dd459c1d2a4ee6f918`;
  listing and embedded Linux/amd64 configuration verified.
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
attempts and superseded local builds are retained; only the exact build above is
eligible for publication. No image has yet been published by this task.

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
