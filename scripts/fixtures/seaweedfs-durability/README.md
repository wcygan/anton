# SeaweedFS durable-acknowledgment qualification

This local experiment changes no Kubernetes resource and uses no real credential.
It exports upstream 4.48 commit `530be3e37337488ecc34d58441e0bc476e121c93`,
keeps an unchanged baseline, and applies `durable-ack.patch` to a separate candidate.
Nothing here authorizes deployment or registry publication.

The hypothesis is that explicit data-plus-index fsync and opt-in synchronous
LevelDB2 mutations preserve acknowledged state when unflushed writes disappear,
and return an error when either persistence barrier fails. Acceptance requires
failing-before/passing-after checks, preservation of previous acknowledged data,
and no false success on sync failure. An unsupported or inconclusive result does
not qualify the image for production.

The volume fixture invokes real SeaweedFS writes with storage wrappers retaining
only the last successfully synced data/index images. Recovery opens a new native
volume from those images. An explicit non-fsync negative control proves that the
fixture actually loses unflushed bytes. Metadata tests invoke real LevelDB2 public
mutations, configured through Initialize, over a real GoLevelDB database with a
storage wrapper. A new database recovers only journal/manifest bytes whose sync
succeeded. Directory metadata operations are modeled as durable; this is not a
complete filesystem, torn-sector, device-cache or power-cut simulator.

Prepare fresh trees (Python 3.12+, Git, patch, Go 1.26.7 required):

```sh
mise exec -- python3 scripts/fixtures/seaweedfs-durability/prepare.py \
  --source-repo /path/to/upstream-seaweedfs \
  --output /path/to/new-evidence
```

In each tree, run `mise exec -- go test ./weed/storage ./weed/filer/leveldb2
-run '^TestQualification' -count=5 -v` and save its output. Baseline must fail the
behavior checks, not compilation. Candidate must pass. Also run the full two
packages and a separate race-enabled focused run. A baseline failure is evidence
of the defect; it is not a passing result.

Build both binaries with matching tools:

```sh
# Run separately within baseline/ and candidate/; choose the matching output name.
GOMAXPROCS=4 CGO_ENABLED=0 GOOS=linux GOARCH=arm64 mise exec -- \
  go build -buildvcs=false -p 4 \
  -ldflags "-X github.com/seaweedfs/seaweedfs/weed/util/version.COMMIT=530be3e37337488ecc34d58441e0bc476e121c93" \
  -o ../weed-baseline ./weed
```

Use `+durability` after the commit string for the candidate. Disabling automatic
VCS stamping prevents an enclosing checkout from supplying the wrong revision.

Copy this Dockerfile into the evidence directory and build the two local images,
selecting `weed-baseline` or `weed-candidate` as BINARY. No push is needed:

```sh
docker build --platform linux/arm64 --build-arg BINARY=weed-baseline \
  -t localhost/anton/seaweedfs:durability-baseline /path/to/evidence
docker build --platform linux/arm64 --build-arg BINARY=weed-candidate \
  -t localhost/anton/seaweedfs:durability-candidate /path/to/evidence
```

Use a Docker ignore file allowing only Dockerfile and the two binaries. Retain
image IDs, binary hashes, Go identity and source/patch hashes with measurements.

```sh
mise exec -- python3 scripts/fixtures/seaweedfs-durability/benchmark.py \
  --output /path/to/new-benchmark-output --rounds 5
mise exec -- python3 scripts/fixtures/seaweedfs-durability/summarize.py \
  /path/to/new-benchmark-output
```

The harness reuses the S3 signing and isolated lifecycle from
`../seaweedfs-qualification/run.py`. Each trial has a new local master, three
volume servers, a filer, an S3 gateway, Harbor's pinned registry component and
Loki 3.7.8. Localhost is the only published interface. Data uses disposable Docker
named volumes. Cleanup retains logs/results and removes owned containers,
networks and data volumes; existing evidence directories are refused.

Cases are unchanged default writes, unchanged image with data fsync, candidate
with data/index fsync, and candidate with data/index plus synchronous metadata.
All use two serving copies and bounded one-pair volume growth. Collections are
warmed outside the timed region. Trials alternate case order for at least five
rounds. The workload verifies registry blob hashes/manifests, numbered Loki
records, completed chunk flushes, and TSDB objects uploaded on shutdown. Each
trial uploads 68 MiB of registry layers (one 48 MiB and five 4 MiB blobs) and
8,000 numbered Loki records across eight streams. `--cold --rounds 1 --case full`
additionally verifies every record from a fresh Loki container reading S3.
Harbor core/database/auth are outside this storage-component benchmark.

SeaweedFS and Loki run native Linux arm64; the matching Harbor registry binary
runs amd64 under Docker emulation. Filesystem storage is the Docker Linux VM,
not Talos/Longhorn. Results compare these matched local configurations; they do
not predict production throughput or certify hardware power-loss protection.
Separate `--profile --rounds 1 --case full` and baseline runs trace fsync system
calls outside scored measurements. Report per-trial medians/ranges and operation
counts, count all errors, and identify allocation, client, scheduler and storage
costs before attributing a difference to fsync.

The candidate only strengthens explicit fsync writes and opt-in LevelDB2 local
persistence. It does not provide a filer metadata quorum, strengthen ordinary
non-fsync volume deletes, or solve every directory-entry and torn-write hazard.

The deployment review expanded the model to independently persisted index appends.
`independent_index_test.go` adds eight cases. The current patch shares batch and
inline rollback, persisting a truncated index before truncating data and fencing
failed recovery. There are now 40 fault cases; earlier benchmark results remain
bound to their original patch/image identities. Use
`images/seaweedfs-durability/build.py` and `rehearse.py` for the production amd64
runtime and HA upgrade/rollback/re-upgrade proof.
