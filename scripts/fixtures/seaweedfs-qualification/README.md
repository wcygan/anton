# SeaweedFS 4.48 qualification

This disposable Docker lab compares pinned Linux amd64 binaries. It never
uses Kubernetes, production PVCs, registry credentials, or real application
data. Ports bind only to `127.0.0.1`; containers use a uniquely named Docker
bridge. The bridge has ordinary Docker egress, so this is not a network sandbox.
Use a local Docker context. The test does not intentionally contact external
services after the pinned images are available.

Requirements: Python 3 standard library, Docker, and enough resources for ten
containers in the HA case (each capped at 768 MiB and two CPUs). Docker may need
to pull the pinned images first. On Apple Silicon the amd64 binaries run under
emulation: these checks prove functional behavior, not production performance.
Stop on a failed correctness gate. A recovery gate has a 75-second retry budget,
plus the duration of an in-flight predicate. HTTP operations have socket
timeouts, and individual Docker commands have a 90-second bound. Allow
20 minutes for the matrix below. A socket timeout is not
a whole-body deadline against a continually trickling peer.

Run from the repository root, giving each run a **new absolute output path**:

```sh
python3 scripts/fixtures/seaweedfs-qualification/test_guard.py

python3 scripts/fixtures/seaweedfs-qualification/run.py \
  --output /tmp/anton-sw448-restarts --version 4.48 \
  --address dns --scenario restarts --cycles 6

python3 scripts/fixtures/seaweedfs-qualification/run.py \
  --output /tmp/anton-sw448-upgrade --version 4.40 \
  --address dns --scenario upgrade --ha

python3 scripts/fixtures/seaweedfs-qualification/run.py \
  --output /tmp/anton-sw448-address --version 4.48 \
  --address dns --scenario stale
```

Repeat the address scenario three times per version with distinct output paths,
alternating `--version 4.40` and `--version 4.48`. Repeat with `--address ip` to
observe the dead-address timeout. Timing depends on whether topology updates
have already reached the gateway; do not call this an S3 latency benchmark.

The lab verifies deterministic numbered objects, overwrite and deletion
semantics, a two-part multipart object, full bytes, ranged reads, HEAD lengths,
and exact listing membership. It also checks the actual production signed GET
probe and the native `SeaweedFS_s3_request_total` GET/200 metric contract.
Repeated restarts alternate SIGTERM with a 20-second grace and immediate
SIGKILL. This is process-crash testing; it does not simulate losing the host's
page cache or power.

The HA case uses three masters, three volume servers, two independent LevelDB2
filers, and two gateways pinned to different filers. It checks both gateways
and agreement among all three masters after each one-component version
transition. It stops the lab to retain a
hash-recorded offline copy of the baseline master, volume, and filer data,
upgrades 4.40 to 4.48, creates objects on mixed versions and on 4.48, and rolls
back to 4.40 while retaining the new data, including a collection/volume newly
created on 4.48. It does not restore over the baseline
copy. It checks application compatibility; it does not emulate the Kubernetes
operator's rollout ordering, Longhorn, CoreDNS, or real production load.

All run-owned containers and the network are removed in `finally`; synthetic
datasets, logs, manifests, and the offline copy remain in the output directory.
The last `cleaned` event asserts that no run-owned container or network remains.
Review `*-exit.json` to distinguish an orderly exit from Docker escalating to
SIGKILL. A failed run is retained, never silently reused or deleted.

## Deterministic source tests

Pin upstream source to these commits, not a moving branch:

| Version | Commit |
| --- | --- |
| 4.40 | `875cd1f67ea25e8965a4f5ba1e6aaf501ba6b6fa` |
| 4.48 | `530be3e37337488ecc34d58441e0bc476e121c93` |

Create a disposable full checkout at the selected commit, copy
`stale_cache_test.go` into `weed/filer/qualification_stale_cache_test.go`, then
run from that checkout (requires the Go version declared by upstream):

```sh
QUALIFICATION_VERSION=4.48 go test ./weed/filer \
  -run '^TestQualification.*StaleCacheRecovery$' -count=3 -v -timeout=90s

go test ./weed/util/http \
  -run 'TestRetriedFetchChunkData(RetriesFreshUrlsImmediately|KeepsBackoffWhenLocationsAreUnchanged|RefreshesLocationsAfterPartialFailure)$' \
  -count=3 -v -timeout=120s

go test ./weed/filer -run '^Test(FetchWholeChunk|PrefetchContextCancellation)' \
  -count=3 -v -timeout=120s
go test ./weed/wdclient -count=3 -v -timeout=120s
go test ./weed/storage \
  -run '^Test(WriteNeedle2.*|Batch.*|MixedBatchSyncFailureRollsBackAsOneUnit|FailedBatchMarksEveryRequestFailed|Load_CorruptIdx_NoSegfault)$' \
  -count=3 -v -timeout=120s
```

For the first command on 4.40, set `QUALIFICATION_VERSION=4.40`. The remaining
commands target the 4.48 upstream regression suite. Both versions must return
exact bytes in the streaming test. The buffered-reader comparison additionally
requires the old backoff to be exercised on 4.40 and skipped on 4.48. These use
real HTTP listeners and actual filer code with an injected location provider;
they do not claim to test DNS publication or the initial TCP timeout.

`operator_image_test.go` tests component digest overrides against operator
1.0.39's actual `api/v1/image.go` (source commit
`8ba00153c593258784e7cf7294e8ba6bdc1a055d`). Copy both files to a disposable
directory and run `go test -v image.go operator_image_test.go`. It checks
that `version: tag@digest` renders correctly and that a digest on the shared
image takes precedence over component version fields. The qualification
record explains the resulting rollout sequence.
