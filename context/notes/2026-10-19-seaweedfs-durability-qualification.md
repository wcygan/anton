# SeaweedFS 4.48 durability qualification

Historical initial-candidate record. The subsequent deployment review found an
independently persisted-index recovery gap and revised the patch. See
[review and rollout](2026-10-19-seaweedfs-durability-rollout.md). Measurements below
remain bound to their original image IDs; the current fixture builds the revised
candidate and has 40 fault cases.

Date: 2026-10-19 America/Chicago (execution continued into October 20 UTC).
Scope: isolated local qualification; production changes require a separate approval.

## Question and candidate

Can Harbor and Loki object writes preserve acknowledged data, index entries and
local filer metadata after unflushed bytes disappear, and reject writes when a
required sync fails?

The experiment exports upstream tag 4.48 at
`530be3e37337488ecc34d58441e0bc476e121c93`. The candidate modifies three files:

- Explicit fsync volume writes sync the data file, then the needle index, before
  acknowledging success. Both batch and inline paths are covered. An inline
  index-sync failure fences the volume; batch failures use upstream's existing
  rollback and fencing behavior.
- LevelDB2 gains opt-in `leveldb2.sync=true`, applied to entry create/update,
  delete, directory-child batch deletes, and bucket key/value mutations.
- Default LevelDB2 behavior remains unchanged unless the option is enabled.

The retained patch and reproduction entry point are
`scripts/fixtures/seaweedfs-durability/durable-ack.patch` and `prepare.py`.
The candidate is an experiment, not a published image or accepted upstream fix.

The corresponding storage policy is explicit fsync for `/buckets/harbor/` and
`/buckets/loki/`, SeaweedFS replication `001`, and synchronous local LevelDB2
metadata. Replication and sync solve different failure modes. Production's
existing single-serving-copy volumes were not migrated during this work.

## Fault model and acceptance

Volume tests use the production-style in-memory needle map with its append-only
index file. They call real SeaweedFS writes and reopen a new native volume containing
only the byte images retained by successful data/index Sync calls. They cover
new writes, overwrites, batch and inline paths, unchanged retries, and one-shot
and persistent data/index sync errors. Previously acknowledged payloads must
remain readable; a failed sync must never produce a successful acknowledgment.

Metadata tests call the actual LevelDB2 public mutations over real GoLevelDB.
Configuration passes through LevelDB2 Initialize. A storage wrapper retains only
synced journal/manifest bytes, and recovery opens a fresh database from them.
The six operations are create, update, delete, delete children, key/value put,
and key/value delete. Each is tested for acknowledged recovery and sync failure.

Explicit fsync-disabled and metadata-sync-disabled negative controls demonstrate
loss of the latest unflushed operation while retaining a seeded durable record.
The tests therefore exercise actual loss and recovery rather than merely count
Sync calls. There are 32 unique leaf cases.

This model assumes directory-entry changes persist and successful sync images
remain intact. It does not simulate torn sectors, reordered directory entries,
lying disk caches, or a physical power cut. Metadata tests use a single LevelDB
partition after verifying real initialization/configuration; they do not prove
cross-partition transactions or a metadata peer quorum.

## Completed fault verification

The candidate passed all 32 unique leaf cases in five race-enabled repetitions
(160 leaf checks), plus three Linux/amd64 repetitions (96 leaf checks) under
local emulation. The reconstructed source and formatted fixture passed all 32
again. Full upstream storage and LevelDB2 package suites passed with the same
production patch. No candidate fault case failed. The unchanged baseline failed
22 of 32 cases on each of five repetitions
(110 failures, 50 passing controls). Failures cover acknowledged index recovery,
ignored index-sync failures, acknowledged metadata recovery, and ignored
metadata-sync failures. Negative controls and existing data-sync error handling
passed. The failures are behavioral, not compilation or harness setup failures.

## Reproducibility and evidence

The retained fixture exports an immutable Git archive into separate baseline and
candidate trees and refuses existing evidence directories. That refusal was
tested and left existing identity metadata unchanged. Reconstructed production
source files match the tested candidate byte-for-byte; test fixtures match after
gofmt normalization only.

Both binaries use Go 1.26.7, CGO disabled, Linux arm64, the same dependencies and
build options. Automatic enclosing-repository VCS stamping is disabled; the
explicit upstream commit and patch hashes identify the source. An initial build
with misleading enclosing-checkout VCS metadata was detected and replaced before
the scored comparison.

Local image IDs:

| Image | ID |
| --- | --- |
| Baseline | `sha256:0149a1a80c9e49fe6598a95d6c998ec7ead147c54de6664d48d36d981de6593d` |
| Candidate | `sha256:0a6674286729afb05b1ef075e8f62deed8feb74f09678d2a7626f2522816777b` |

Raw evidence is retained outside Git under
`.private/seaweedfs-durability-qualification/`: source exports, identity and
hashes, fault-test logs, full-package logs, Linux/amd64 test binaries/results,
benchmark logs/results, application logs, object hashes, traces and cleanup
evidence. It contains synthetic data and local-only test credentials. No real
cluster credential or production dataset was used.

## Performance method

Four cases isolate default writes, stock data fsync, candidate data/index fsync,
and candidate data/index plus synchronous metadata. Five rounds alternate forward
and reverse order. Every case uses native `001` replication with two serving
copies verified on distinct local volume servers. Warmup creates both bucket
collections outside the timed region.

Each trial starts a new master, three volume servers, filer, S3 gateway, Harbor
registry component and Loki. Each SeaweedFS container has two CPUs and 768 MiB.
Disposable Docker named volumes provide the Linux VM filesystem. Localhost is
the only published interface. Each trial cleans up its containers, network and
named volumes, retaining evidence.

Harbor's pinned 2.15.2 registry component uploads one 48 MiB and five 4 MiB
incompressible blobs, checks every downloaded digest, then uploads and reads an
OCI manifest. Payload generation is outside upload timing. Registry core,
database, authentication and full Harbor control-plane behavior are excluded.
The registry image is amd64 under emulation; SeaweedFS and Loki run native arm64.

Loki 3.7.8 receives 8,000 numbered records across eight streams, verifies exact
record contents with no missing or duplicate entries, flushes chunks to S3,
and shuts down gracefully to upload a TSDB index. The benchmark checks actual
uploaded index bytes and records Loki S3 PutObject count/time. Push latency
measures ingester acceptance, not S3 durability. The isolated upstream Loki image
does not include Anton's custom checkpoint fix; this is an object-store-path
comparison, not requalification of that separate patch.

Report the 48 MiB layer separately from the median of the five 4 MiB layers.
Per-trial medians/ranges preserve variability. Separate traced runs identify sync
calls and their cost; traced runs are excluded from scored performance.
Docker statistics captured after the workload cannot establish its CPU limiter.
These measurements do not predict Talos/Longhorn production throughput.

## Scored performance results

All 20 final trials passed: 160,000 exact Loki records, 1,360 MiB of verified
registry layers, 20 verified OCI manifests, uploaded TSDB index objects and native
two-copy placement. These are 20 fresh lab lifecycles, not 20 power-cut trials.

Values are milliseconds: median of five trials, with minimum–maximum in parentheses.

| Setting | Registry 48 MiB PUT | Registry 4 MiB PUT median | Registry total 68 MiB PUT | Loki S3 PUT mean | Loki flush |
| --- | --- | --- | --- | --- | --- |
| baseline | 1015.2 (980.6–1030.9) | 102.0 (98.9–104.0) | 1529.9 (1505.7–1561.6) | 9.8 (8.8–10.7) | 59.4 (53.4–61.3) |
| data-only | 1100.9 (1047.2–1141.8) | 117.0 (114.0–127.7) | 1717.6 (1622.3–1768.8) | 13.8 (13.4–15.2) | 58.9 (55.3–61.7) |
| data-index | 1130.1 (1050.3–1245.6) | 133.4 (125.2–136.7) | 1835.7 (1726.6–1929.5) | 16.5 (15.2–18.9) | 80.7 (57.7–85.2) |
| full | 1151.0 (1129.8–1485.2) | 157.6 (146.4–162.6) | 1970.2 (1860.8–2276.9) | 23.1 (21.1–44.8) | 96.3 (89.8–174.1) |

Compared with baseline, full durability adds about 29% to median total layer
upload time and 55% to the median 4 MiB upload. The 48 MiB median rises about 13%.
Loki S3 PUT latency rises from 9.8 to 23.1 ms; completed flush latency rises from
59.4 to 96.3 ms, with a 174.1 ms maximum. Push acceptance remains about 12 ms
because it acknowledges the ingester rather than completed object persistence.
The 48 MiB GET ranges overlap substantially (baseline 31.5–46.6 ms; full
30.4–46.2 ms); this run does not establish a significant read regression.

No scored request, digest, record, manifest, index or placement assertion failed.
No container OOM was recorded. Teardown records include nonzero registry exits
and filer SIGKILL after the 20-second stop grace. All Loki writer exits were zero.
Those teardown events are retained and are not counted as graceful SeaweedFS
shutdown or crash-recovery proof. Raw `performance-summary.json` retains every
trial metric, and `summarize.py` rejects incomplete or mixed-profile comparisons.

## Separate sync tracing

| Case | Volume sync calls (all three servers) | Filer sync calls |
| --- | ---: | ---: |
| baseline | 3 | 2 |
| data-only | 150 | 2 |
| data-index | 287 | 2 |
| full, including cold readback | 285 | 216 |

The traces observe fsync/fdatasync and their elapsed syscall times. Added volume
and metadata barriers account for substantially more synchronization work. Full
volume syscall time sums to about 1.30 seconds across three servers, and filer
sync time to 0.35 seconds. Calls overlap, so summed syscall time is not wall-clock
latency. The full trace also includes cold reader startup and queries. Counts
include background activity and are not an exact per-object contract.

Registry client/network/serialization and amd64 emulation remain part of upload
latency. Neither traces nor idle post-workload Docker stats prove a single
exclusive bottleneck. Trace overhead is visible; none of these runs is included
in the scored performance table.

## Cold object-store readback

A separate full-durability trial shipped the TSDB index, stopped the writer
cleanly, then started a fresh Loki container with an empty local filesystem.
Every one of the 8,000 numbered records and payloads was recovered exactly from
S3, with 24 chunk downloads confirmed in query statistics. This demonstrates
object/index readability without the original ingester or WAL. It is a clean
writer shutdown followed by cold recovery, not a physical power-loss test.

## Harness failures and excluded evidence

Pilot failures are retained rather than counted as successful trials. The first
metadata wrapper tried to read an open in-memory storage writer; it was replaced
with a wrapper recording writes and successful sync images. A registry pilot lost
its signed upload-state query parameter; the harness now preserves the complete
Location query. A policy assertion initially depended on JSON whitespace; the
harness now decodes and checks the returned policy. Early Loki timing included
first-volume allocation; both collections now warm before measurement.

The first scored attempt stopped when a server with zero assigned volumes
returned `Volumes: null`. The parser now treats that valid response as an empty
list while still requiring two distinct owners for every allocated volume. That
entire interrupted attempt is excluded. The final measurements use a frozen
harness hash recorded in `measurement-method.json`, with no concurrent builds or
fault-test runs launched by this qualification.

## Recommendation

Recommend the candidate barrier changes with explicit bucket fsync and
`leveldb2.sync=true` as the fix for the demonstrated acknowledgment gaps. The
isolated correctness gates pass, including sync failures, lost unflushed bytes,
and real Harbor/Loki object paths. The measured local cost is material but
bounded at this workload; production capacity must be measured during staging.

Proceed next to independent review and a pinned production-architecture image,
then a separately approved staged rollout with fresh consistent backups and
explicit stop/rollback gates. Upgrade volume binaries before relying on the
stronger bucket policy, and filer binaries before enabling the new metadata
option. Stock 4.48 ignores the new LevelDB2 option and does not sync the index on
this acknowledgment path; configuration alone cannot provide the qualified fix.
An old-image rollback restores the old durability limitations, so a failed
rollout must pause affected writes rather than silently claim the stronger
acknowledgment guarantee after downgrade. There is no format migration in this
patch, but production upgrade/rollback compatibility has not been newly rehearsed
by this bounded experiment.

Retain Longhorn's two replicas and use SeaweedFS `001` with bounded copy-two volume
growth as a separate redundancy improvement. Migrate and verify existing copies
explicitly after rechecking free capacity and failure-domain placement. This
qualification does not authorize those production operations.

## Scope limits and production gate

This candidate addresses the modeled durable-write acknowledgment gaps. It does
not make ordinary non-fsync volume deletes durable, establish synchronous filer
peer replication, make every filesystem operation crash-atomic, or change Loki's
own WAL acknowledgment guarantees. No evidence here proves the historical cause
of volume 9's zero-filled suffix.

A production proposal must separately pin a reviewed amd64 image, preserve fresh
consistent backups, enable only the intended bucket policies and metadata
setting, rehearse rollback with the same data format, and migrate existing
volumes to two native copies with capacity/placement checks. Never assume changing
the default replication policy retroactively replicates existing volumes.
Observe Harbor digest reads/pushes, numbered Loki delivery, filesystem/storage
errors, sync failures and existing ntfy alerts throughout a staged rollout.

Principles that changed the experiment:

- **Fix Root Causes:** test all three persistence barriers rather than treating
  extra replicas as proof that an acknowledged cached write survives power loss.
- **Test Behavior, Not Implementation:** reopen native volumes and real LevelDB
  from durable bytes and assert literal recovered payloads and metadata.
- **Explain the Number:** warm allocation outside timing, split blob sizes, use
  alternating repetitions, and state VM/emulation and acknowledgment boundaries.

The repository contract suite passed: 493 tests, one skip. Python fixtures compile,
and source/fixture identities, the evidence-overwrite guard and final cleanup
checks passed. No temporary qualification container, network or data volume remains.
Local images, binaries and private evidence remain available for review.

No Kubernetes resources, Flux configuration, credentials, production data or
registry publications were changed. The patch and this report remain uncommitted.
