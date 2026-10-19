# Loki 3.7.8 WAL forensics

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

## Candidate fix regression

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
