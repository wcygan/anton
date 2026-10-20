# Stock SeaweedFS and Loki qualification — 2026-10-20

Decision: neither current published release qualifies for Plan 0028's retained
integrity contract. Brief planned downtime is acceptable; loss of acknowledged
data has not been accepted. No production configuration, data, or runtime changed.

## Candidates and method

Release discovery on 2026-10-20 returned SeaweedFS 4.48 and Loki v3.7.8 as the
latest published releases. Exported clean source with `git archive`:

- SeaweedFS: `530be3e37337488ecc34d58441e0bc476e121c93`.
- Loki: `09e6ce2ff1bdc19763a10265b870c86f51c98655`.
- Anton fixture source: `886fbd6a30efff5a8ac75befb25d1e40c8fef45b`.
- Official Loki linux/amd64 image:
  `grafana/loki@sha256:81a6802ec4bd1b88c564494f06376889ed022998a188826190d26d2754ac2aae`.

Only retained Go test files were added to the stock trees. Post-test hashes verify
all 4,111 SeaweedFS and 22,465 Loki original files unchanged. Compiled Linux amd64
Go test binaries ran in resource-limited, network-isolated containers. The loader
image's SeaweedFS executable was never invoked. Separate control trees received
only the existing durable-ack/compaction-sync or checkpoint-and-counter patches;
no new runtime patch was written. Each selected Go test ran three times.

Private evidence: `.private/stock-software-qualification-20261020/`, including
`prepare.py`, `identity.json`, `verified-summary.json`, build/test logs, immutable
binary hashes, source/control trees, and real-image `checks.json` and logs.
Tests use synthetic data. Docker resources are isolated from production.

## Results

| Check | Stock result | Existing-patch control |
| --- | --- | --- |
| SeaweedFS acknowledged volume writes after modeled dirty-byte loss | Fail in batch and inline paths; acknowledged payload not found | Pass, three repetitions |
| SeaweedFS sync failures, independently persisted index, index-position boundaries | Fail; failure handling does not preserve required boundaries | Pass, three repetitions |
| SeaweedFS compaction source-sync/close failures | Fail; injected EIO can yield success, and recovery/quarantine expectations fail | Pass, three repetitions |
| LevelDB2 acknowledged metadata and sync-failure handling | Fail, including with requested `leveldb2.sync=true` | Pass, three repetitions |
| Volume and metadata unflushed-data negative controls | Pass, three repetitions: harness actually discards unflushed state | Pass, three repetitions |
| Loki flushed-stream checkpoint recovery | Fail, missing stream reference, three repetitions | Pass, three repetitions |
| Loki stream recreation/replay with and without checkpoint | Fail, missing entries/counter state, three repetitions | Pass, three repetitions |
| Official Loki image, initial HTTP push/query | Pass: 256 acknowledged, 256 returned, no duplicates | Pass: 256/256 recovered |
| Official Loki image, forced restart after checkpoint/flush overlap | Fail: 248 of 256 acknowledged entries returned; 8 missing; one WAL corruption reported | Pass: 256/256 recovered |

The current patched Loki image control, immutable local image ID
`sha256:e08b7f504501aada07bd6d4b79c4468f6480393740c483d1c3785cafaf1f2370`,
passed the same stock-compatible runtime script: 256/256 after forced restart,
320/320 after graceful restart and after the second checkpoint restart, with zero
missing or duplicate results. Its evidence is `loki-control-runtime-run2/`.

The official-image run reproduced loss using the filesystem object store, so
changing SeaweedFS or the S3 endpoint alone cannot fix this Loki failure. This is
one timed runtime reproduction, not a measured failure rate. Deterministic Go
fixtures separately establish the checkpoint and counter defects.

The first runtime attempt stopped at an assertion requiring our custom
`errors=false` WAL log field. That was a harness incompatibility, not evidence of
loss. The private stock-compatible copy changes only that assertion to require
completion of WAL segment recovery; exact entry-set, duplicate, metric and
checkpoint checks remain intact. The second run reached the data check and
recorded the eight missing IDs. Initial image-selection/setup failures are retained
in logs and excluded from behavioral results.

## Simplest path and patch disposition

1. **Stop stock-image promotion here.** Preserve the current data topology and
   patched images until a qualified replacement exists. This is an interim hold,
   not completion of the zero-patch goal. Do not add more downstream patches.
2. **Retire the special migration requirement.** Native two-copy migration is
   already complete. The HTTP growth fence can lose its operational purpose when
   that workflow is retired. This does not justify dropping the other SeaweedFS
   patches, nor prove a stock orphan-cleanup procedure safe.
3. **Seek an upstream release for the integrity fixes.** Retain these small
   reproductions and patch correspondence. Loki PR 25162 was open/unmerged at this
   check; even a merge must cover both checkpoint references and counters, then
   pass these cases in a released artifact. No upstream publication was performed.
4. **If patch ownership must end before those releases, evaluate replacement
   services.** Independently operated S3 can remove SeaweedFS runtime ownership;
   qualify Harbor compatibility, each consumer, restore, privacy and cost before
   choosing a provider. Loki requires its own qualified replacement or externally
   operated logging service. Moving only its object store leaves the replay bug.
5. **Keep configuration changes proportional.** An external filer database can
   address metadata persistence only; it adds another service and does not solve
   volume/index or compaction errors. Disabling Loki WAL sacrifices the protection
   being tested. Longer checkpoint/retention intervals reduce some exposure but
   do not establish correctness. Planned shutdowns cannot prevent unplanned
   process/host failures. None qualifies as a proven configuration-only solution.

After a candidate clears integrity checks, test the image transition separately:
flush/preserve Loki's old WAL and rehearse a fresh-WAL transition, verify real
Harbor push/pull and S3 behavior, restore, and measure stop/start interruption.
These were deliberately not run against a candidate that already fails integrity.
No downgrade compatibility, full restore, power-loss hardware test, throughput or
production resource-sizing claim is made by this experiment. SeaweedFS faults are
modeled storage failures; they are not a physical power-cut qualification.

The existing 32-volume/64-copy topology, backups, probes and Raft readiness guard
remain required. Do not combine patch retirement with smaller PVCs or fewer
Longhorn replicas. Optional four-record orphan cleanup remains separately gated.

## Reproduction

Use the fixture files from the pinned Anton revision, over clean source archives.
For SeaweedFS compile `./weed/storage` and `./weed/filer/leveldb2` with
`CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go test -c -p 2 -vet=off`; run the binaries
on Linux amd64 with `-test.count=3 -test.timeout=180s -test.v` and:

- storage: `-test.run 'TestQualification|TestCompactionSourceSyncErrors|TestCompactionClose'`
- metadata: `-test.run TestQualification`
- Loki `./pkg/ingester`: `-test.run 'TestForensicFlushedStreamCheckpoint|TestWALReplayAfterStreamRecreation'`

Use `scripts/verify-loki-checkpoint-restarts.py` from the same Anton revision for
the real image, with the single stock log-field assertion adaptation documented
above, `--cycles 1`, the immutable image above, and a private output directory.
Run only in an isolated Docker environment. Retain `checks.json` even on failure.

Principles applied: **Test Behavior, Not Implementation** kept exact acknowledged
entry recovery as the runtime gate and removed the custom-log-field assumption.
**Prove It Works** required pristine source hashes and passing patch controls.
**Subtract Before You Add** rules out a new database or availability machinery as
a response to faults those additions cannot fix.

Sources: [SeaweedFS 4.48](https://github.com/seaweedfs/seaweedfs/releases/tag/4.48),
[Loki v3.7.8](https://github.com/grafana/loki/releases/tag/v3.7.8),
[Loki upstream PR 25162](https://github.com/grafana/loki/pull/25162),
[Loki WAL contract](https://grafana.com/docs/loki/latest/operations/storage/wal/).
