# SeaweedFS availability during node maintenance — 2026-10-19

## Scope and ownership

Improve cold S3 reads and fresh writes during one node's planned maintenance.
The operator requested GPT-6 Luna high-effort workers in separate worktrees.
Root owns integration, publication and all live mutations. Workers own the
read-only audit, isolated Docker proof and Seaweed CR candidate separately.
The canonical checkout's unrelated dirty work remains untouched.

Repository implementation and local isolated tests are authorized. A new live
replication migration and drain require an exact reviewed plan and operator
approval; the earlier replacement/drain approval was consumed by that drill.
No new live mutation has been performed for this follow-up.

## Baseline

At 22:54:10–22:54:11 UTC, the integrated read-only audit verified cluster UID
`5848c42c-b3ec-4003-a02c-becc2c9fa63f` and Seaweed UID
`dce6fb89-c179-4c19-9a98-2bfc7d0aaa73`. Every volume had native placement
`000` and one active serving location. The command correctly exited 2.

| Collection | Native volume IDs | Reported volume bytes |
| --- | --- | ---: |
| Empty collection | 9, 10, 11, 12, 13, 14, 15 | 10,442,690,344 |
| Harbor | 20, 21, 22, 23, 24 | 19,611,585,016 |
| Loki | 25, 26, 27, 28, 29, 30, 31 | 126,162,344 |
| S3 read probe | 49 | 65,592 |

These are native reported volume sizes, including any obsolete contents;
they are not live object payload or physical disk allocation measurements.
The three servers have 6/20, 8/20 and 6/20 occupied logical-volume slots on
`k8s-1`, `k8s-2` and `k8s-3` respectively. Each has a 120Gi Longhorn PVC with
two Longhorn replicas. All existing IDs, including the empty collection and
probe volume, must be preserved.

Two SeaweedFS copies of this corpus would add about 28.1 GiB of reported
volume data plus indexes/metadata, and consume 40 of 60 slots before any new
allocations. This is a capacity estimate, not a performance measurement.
Additional application-level writes and LAN traffic are the recurring cost;
Longhorn would still replicate each backing PVC. New allocations need free
slots on the two surviving servers during maintenance.

## First verifiable unit: placement audit

`scripts/verify-seaweedfs-maintenance.py` performs bounded GETs and joins native
per-copy placement to active master topology, owned Pods, actual Bound PVCs
and Ready nodes. It rejects inactive/stale locations, foreign DNS aliases,
terminating resources, mixed placements and reported-size mismatches.
It deliberately leaves byte integrity, S3 cache behavior and write availability
unassessed. Its observation interval is not an atomic multi-API snapshot.

Independent review found and closed inactive-location and mismatched-size
fail-open cases. All 16 focused tests pass. The integrated public contract
suite passed 493 tests with one skip. Removing this script and its tests
reverts this unit; it changes no runtime state.

[PR 517](https://github.com/wcygan/anton/pull/517) merged this unit at
23:00:15 UTC as `73202f81`; GitHub checks passed. No runtime manifest changed.

Both exact filer Pods returned readable root metadata and HTTP 404 for
`/etc/seaweedfs/filer.conf` in a subsequent GET-only observation. The running
filer command has no explicit replica-placement override. At pinned 4.40 an
empty filer default is supplied by the master's current default on each
assignment, rather than cached once at filer startup. Repeat this path-rule
preflight before rollout; an explicit persisted rule would take precedence.

## Current decision gate

The root independently executed the frozen 4.40 fixture, then added the review's
same-volume control assertion and reran the resulting artifact successfully.
All five withdrawals assert one chunk per warm/cold object, the same VID and
different file IDs. The `000` unread GET timed out at 10.058 seconds while the
warm GET returned exact bytes. All four `001` unread GETs passed (two migrated,
two newly allocated), as did fresh PUT/GET operations whose native placement
had two surviving owners. The migrated source/destination `.dat`, `.idx` and
`.vif` hashes matched, read-only state persisted through restart and copy,
and both copies became writable with VID 1 in the master's `001` write layout.
The test's source `.dat` was 4,194,632 bytes below its 8 MiB limit.
All responses verified 1,048,576 bytes with the expected digest. Local timings
are not production throughput or latency estimates.

Both root executions exited zero and verified cleanup of their own Docker
containers, networks and volumes. The final guarded run's raw evidence is
retained in the integration checkout's ignored
`.private/seaweed-maintenance/proof-final-controls.log`. The final public
contract suite passed 493 tests with one skip, and the docs production build
passed. Source and runbook review closed the stale-location, size-consistency,
warm/cold volume, writer fence, bucket CronJob, node-owner, credential-exposure,
budget, restore-state and filer-before-S3 sequencing findings.

The same pinned fixture now supports 4.48 without changing its cache settings.
The worker and root independently executed it successfully: the single-copy
cold GET failed, while all four two-copy cold GETs and fresh PUT/GET checks
passed. The exact migration retained FID/VID, matched all three file hashes,
persisted read-only state and restored the `001` write layout. Unlike the 4.40
observation, the worker's 4.48 warm baseline timed out too; the cause of that
warm-read difference remains unassessed. The required baseline is cold-read
unavailability, not the presence of a warm body-cache hit. Every successful
response must have the expected digest. Root's first 4.48 evidence is retained
in `.private/seaweed-maintenance/proof-root-4.48.log`.

Final review additionally requires distinct permitted volume-server hosts
instead of counting duplicate location entries as copies, and rejects a corrupt
HTTP 200 cold response instead of classifying it as an expected outage. Mocked
duplicate/foreign-owner, multi-chunk and corrupt-response cases reject as
expected. The final guarded 4.40 worker run and independent root 4.48 run both
exited zero, each with five same-volume controls and four successful two-copy
withdrawals. Root separately inspected returned hashes and distinct surviving
owners in the final log and queried Docker labels to confirm cleanup. Evidence
is retained in the proof worktree's ignored
`.private/seaweed-maintenance-availability/4.40-guarded-final.log` and integration
checkout's `.private/seaweed-maintenance/proof-root-4.48-guarded.log`.
The reusable proof is delivered separately in
[PR 518](https://github.com/wcygan/anton/pull/518); it changes no runtime state.

An earlier sequential local experiment failed its second cold GET after a
server returned and a one-location lookup was reused. That failed run did not
capture every process's map. Direct filer `LookupVolume` observations and fresh
S3 processes are preparation gates; the S3 map's contents/completeness remain
unassessed. Actual never-read bytes while an owner is absent are the outcome
evidence, rather than a claim that gateway readiness synchronizes caches.

At 23:27 UTC, GET-only checks found 3/3 Ready schedulable nodes, 86/86 Ready
reconcilers, 72/72 desired Ready Deployments/StatefulSets, 23 healthy Longhorn
volumes and 46 running replicas. The extra five PVCs and their unmanaged reader
Pods belong to the separate SeaweedFS 4.48 restore/upgrade workstream. Our
production inventory remains the same 20 single-copy `000` volumes. All three
masters were back on 4.40 at that observation, after main's staged master pin
`e00c4ee7` and revert `3f182a85`; that owner is still working on its readiness
gate. Preserve its evidence and resources, and serialize all live storage
changes. Main subsequently added Raft-gated 4.48 masters and began staged volume
server upgrades. This proposal preserves those source changes. Its local
qualification cannot authorize work during that rollout or replace the fresh
owner/version check. The [qualification record](2026-10-19-seaweedfs-4.48-qualification.md)
belongs to that separate workstream.

The candidate is native placement `001` while retaining one volume server per
node, existing PVCs and Longhorn replication. Local fresh and migrated `001`
tests support the intended cold-read behavior. Production still needs the
approved copy procedure, byte verification and gateway lookup-cache checks.
No production availability improvement is claimed before those gates pass
and the separately approved live exercise succeeds.

The earlier R3 recovery drill used a fresh OCI client after warming the same
fixture through S3. Its metadata mapped the fixture to the replaced server,
but a gateway body cache could serve that request. It proves the recorded
client-visible recovery, not that the replacement server supplied those bytes.
This follow-up uses never-read objects to distinguish those cases.

## Engineering choices

- **Fix Root Causes** selected data-copy availability as the target, rather
  than treating gateway readiness as evidence that object data is available.
- **Explain the Number** requires exact-object owner mapping and separates
  warm gateway hits from cold reads; reported volume bytes remain labelled.
- **Separate Before Serializing Shared State** gives each Luna worker a
  branch/worktree and keeps root as the sole integration/live writer.
- **Sequence Work into Verifiable Units** separates audit, local proof,
  runtime policy, existing-data migration and node maintenance gates.
- **Build the Lever** produces a rerunnable audit and local proof fixture.
- **Prove It Works** requires actual S3 bytes and fresh writes in the outage
  window, rather than accepting metadata or replica counts as end-to-end proof.
