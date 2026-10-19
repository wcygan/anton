# Loki 3.7.8 WAL forensics

**Current candidate: `checkpoint-and-counter.patch`. The earlier checkpoint-only
patch is rejected and retained solely as a negative control.**

These fixtures diagnose private evidence with upstream Loki's real ingester
recoverer. They do not configure or repair production Loki. Raw WAL, binaries,
archives, encryption keys, detailed hashes and replay reports belong in private
storage, never Git. Retain the original volume and snapshot throughout review.

`forensic_test.go` invokes checkpoint recovery and WAL recovery separately,
reports the returned errors and reader errors, and inventories checkpoint,
segment and failed entries by timestamp/body SHA256. It never prints log bodies
or full labels. `replay-loki-wal.py` runs it twice against separate working copies
in a network-disabled container, and verifies that the baseline hashes remain
unchanged. The binary and image must already exist locally; no production
configuration, endpoints, credentials or source directory are mounted.

Prepare a private upstream checkout at **09e6ce2ff1bdc19763a10265b870c86f51c98655**
(tag `v3.7.8`, matching the investigated production revision). Fetch the pinned
Go image before attaching evidence. Copy both Go fixtures into `pkg/ingester/`.
Build using upstream's vendored dependencies:

```sh
# SOURCE is the private upstream checkout; choose an absolute path.
docker run --rm --network none \
  -v "$SOURCE:/src" -w /src -e CGO_ENABLED=0 \
  -e GOPROXY=off -e GOSUMDB=off -e GOTOOLCHAIN=local \
  golang@sha256:705e964a93a2fd2e75c7d59bb7d781b57e30f12293ffde5175c69229e18fb678 \
  go test -c -p 4 -vet=off -o forensic.test ./pkg/ingester

mise exec -- python3 scripts/replay-loki-wal.py \
  --wal "$BASELINE/wal" --binary "$SOURCE/forensic.test" \
  --output "$PRIVATE/replay.json"
```

The output hashes identify records, not independent proof of durable storage.
Compare them to bounded Loki queries by exact nanosecond timestamp and body
SHA256. Query statistics distinguish active ingester chunks from downloaded
stored chunks. Retained evidence covers only its captured interval; unavailable
historical files cannot be declared recovered.

## Initial checkpoint-only hypothesis (rejected)

`forensic_regression_test.go` models a stream captured by checkpoint iteration
whose chunks have subsequently been flushed. Unmodified 3.7.8 omits its stream
reference; a following WAL batch fails recovery. The candidate patch retains
that metadata, skips already-checkpointed entries through their existing counter,
and recovers a newer entry. It prevents future bad checkpoints; it cannot
reconstruct a reference already absent from an existing checkpoint.

Run the fixture on unmodified source and retain its expected failure. Apply
`retain-flushed-stream-reference.patch` with `git apply --unidiff-zero` only
to the private upstream checkout,
rebuild the binary, and run the fixture plus surrounding checkpoint/recovery tests
in a `--network none` container with writable `/tmp`. This is a candidate for
upstream review, not a production deployment artifact. Never suppress unknown
references globally or delete WAL to clear the alert. Upgrade/patch deployment
requires a reviewed image, a fresh retained snapshot, numbered restart canaries,
and production approval. Rollback restores the previous image/configuration,
without replacing or truncating the original PVC; retained evidence remains intact.

## Reviewed image candidate (2026-10-19)

**Do not deploy the checkpoint-only patch above.** Review and an actual-image
negative control found that retaining an empty stream's stale entry counter can
lose acknowledged entries after the stream is recreated. That image lost
128/256 synthetic numbered logs after checkpoint/flush overlap and a crash.

`checkpoint-and-counter.patch` combines reference retention with the bounded
counter fix adapted from [upstream PR 25162, commit 9cf0657](https://github.com/grafana/loki/commit/9cf0657212438f968facc96a34202f992b23ac49)
and adds returned checkpoint/segment errors to logging. The upstream PR was open
when reviewed. The adapted `forensic_counter_test.go` removes the newer
`MustPlan` API dependency and adds iterator capture before flush/removal, two
recreated entries, and removal/recreation after restart. It asserts returned log
contents. The combined patch prevents new bad state; it cannot reconstruct
historically missing references or previously reused WAL counters.

For a fresh exact source checkout, apply only the combined patch with
`git apply --unidiff-zero`. Copy the Go fixtures into `pkg/ingester/`. Fetch the
pinned Go 1.26.6 and amd64 Loki base images before building. Then:

```sh
mise exec -- python3 scripts/build-loki-wal-image.py \
  --source "$SOURCE" --output "$PRIVATE/image"
# Use image_config_digest from image.json for the local immutable image.
mise exec -- python3 scripts/verify-loki-checkpoint-restarts.py \
  --image "$IMAGE_ID" --cycles 2 --output "$PRIVATE/restarts"
mise exec -- python3 scripts/verify-log-durability.py \
  --loki-image "$IMAGE_ID" --backend-failure http503 \
  --output "$PRIVATE/collector-restarts.json"
```

The builder verifies the complete tracked source diff, builds linux/amd64 with
CGO disabled and pinned Go 1.26.6, retains the original pinned Loki runtime base,
and exports both a loaded image and an OCI archive. It verifies that the loaded
config digest equals the OCI manifest's config digest. The temporary packaging
builder is removed. `image.json` identifies the manifest digest, binary hash,
source revision and patch hash; a local config ID is not a registry pull digest.
No image is pushed or production configuration changed by these commands.

The restart driver uses synthetic data, a filesystem object store, an internal
Docker network and a private HTTP client, with no published ports. It verifies
checkpoint start/end overlap with flush, removal of all old chunks, stream
recreation, SIGKILL recovery, graceful restart, and another completed checkpoint
followed by SIGKILL. Two cycles run six restarts and check all 640 acknowledged
records with no missing, extra or duplicate query results. Runtime recovery
counters must exist, and startup logs must show successful checkpoint and
segment recovery. The deterministic Go fixture proves the iterator-capture order;
runtime timing alone is not that proof. The separate collector test verifies
durable export through an overlapping backend outage and collector restarts.

Generate an actual missing-reference negative control with the
`TestForensicWriteMissingReference` fixture, setting `FORENSIC_SYNTHETIC_WAL` to
an explicit private directory. Pass that directory to the image driver using
`--missing-reference-fixture`. It requires the segment failure counter to be one,
the actual unset-reference error to be logged, and 64 newly acknowledged test
records to remain queryable. Original evidence must never be used as this
synthetic output directory.

Before any production rollout, retain a fresh snapshot and drain/verify old
acknowledged data in object storage: this patch does not heal existing reused
counters. A downgrade needs its own flush/checkpoint and restart rehearsal;
reverting an image while newer WAL counter gaps remain is not a verified
rollback. No production rollout or downgrade is authorized by these fixtures.

## Downgrade rehearsal

Use `--downgrade-image` with the exact old image config ID/digest. After the
normal restart trial, the driver flushes all chunks and requires every numbered
record to be served from stored chunks with zero matching memory chunks. It
requires a clean exit, preserves every original WAL hash, starts the old image
with a new WAL directory on the same test volume, writes again, crashes, writes
again and restarts gracefully. The rehearsal passed 448/448 records with the
original WAL unchanged. This validates a drained WAL-directory cutover; it does
not validate reverting an image against the newer WAL's counter history.

```sh
mise exec -- python3 scripts/verify-loki-checkpoint-restarts.py \
  --image "$IMAGE_ID" --cycles 1 --downgrade-image "$OLD_IMAGE_ID" \
  --output "$PRIVATE/downgrade"
```
