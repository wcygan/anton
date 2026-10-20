# Isolated singleton migration qualification

These prototypes run local Docker containers with disposable named volumes and
throwaway S3 credentials. They never call Kubernetes or use cluster credentials.
The SeaweedFS runtime is the exact local amd64 image used for durable1 publication;
Harbor's registry component and Anton's patched Loki image exercise the S3 path.
Workloads use an internal Docker network. A separate fixed-target Caddy relay
exposes only loopback HTTP ports for the test controller. No production data is
mounted. Debug RPC clients join only the internal network.

Run from the repository checkout with the pinned local images already present:

```sh
python3 scripts/fixtures/seaweedfs-singleton-migration/run.py --output /absolute/new/evidence-directory
python3 scripts/fixtures/seaweedfs-singleton-migration/slots.py --output /absolute/new/slot-evidence
python3 scripts/fixtures/seaweedfs-singleton-migration/reserve.py --output /absolute/new/reserve-evidence
python3 scripts/fixtures/seaweedfs-singleton-migration/faults.py --output /absolute/new/fault-evidence
python3 scripts/fixtures/seaweedfs-singleton-migration/availability.py --output /absolute/new/application-hold-evidence
```

Every output directory must be new. Cleanup stops only run-owned containers and
removes their networks and named volumes, retaining logs, hashes and summaries.
The full runner observes at least 660 seconds with growth disabled and another
660 seconds after restoring growth. Do not shorten those periods to infer safety
across the real five-minute background sweep. A failed run retains `failure.txt`.

The full runner creates real legacy singleton data using Registry and Loki,
changes server addresses, rejects old container bindings, rehearses pre-copy
configuration rollback, and compares source/destination data/index/info hashes.
It verifies original image data and original/outage logs before writing the
post-migration test corpus. Cold log readers use a new local data volume. Each
server hold uses separate never-read keys per gateway and joins chunk IDs to the
copy placement. It exercises serving-process absence, not a Kubernetes drain.

The slot runner verifies 20 -> 24 on the actual server, preserves the original
volume hashes, and requires rejection of a 25th volume. Its HTTP negative control
demonstrates that durable1's startup growth-disable flag does not fence `/vol/grow`.
`growth-http-fence.patch` adds that missing guard. Overlay
`growth_fence_qualification_test.go` into the pinned Seaweed source's `weed/server`
package. The regression must fail before applying the patch and pass afterward:

```sh
go test ./weed/server -run 'TestQualificationHTTPGrowthFence|Test.*Assign|Test.*Grow' -count=3
```

Build the same durable1 amd64 source plus this patch using Go 1.26.7 and the
normal CGO-disabled, trimmed build. Record the binary hash and actual image ID.
Then test that image without publishing it:

```sh
python3 scripts/fixtures/seaweedfs-singleton-migration/slots.py \
  --output /absolute/new/fixed-evidence \
  --image sha256:REPLACE_WITH_ACTUAL_LOCAL_AMD64_IMAGE_ID \
  --expect-http-blocked
```

This requires an HTTP 503 with no allocation while fenced, then a successful
allocation after the setting is removed and master registration recovers.
The reserve runner builds 28 logical volumes / 56 copies at 19/19/18 slots,
withdraws one server, and requires four new `001` allocations on both survivors.

The fault runner interrupts a throttled real copy with a deadline, requires the
source hashes to remain unchanged, and never retries the ambiguous destination.
It uses a separately empty server for the completed pair, aborts further
migration, restores service and verifies the original bytes/FIDs while retaining
both the completed pair and untouched singleton data.

The availability runner verifies original Registry data and cold Loki reads
before fresh log writes during each server hold. Its recorded native chunk map
distinguishes a real owner loss from a control hold that did not affect one of
the applications. Each application must lose an original owner in at least two
holds. `availability.py` and `faults.py` also accept the same immutable `--image`
argument to exercise a local candidate image without publishing it.

`operator_expansion_test.go` overlays into the pinned operator 1.0.39
`internal/controller` package. It invokes the real claim-template reconciler with
a fake API client and proves that an existing 120Gi claim/template remains
unchanged, identities remain intact and a mismatch Warning is emitted for 160Gi.
It does not exercise the CSI driver.

## Limits

The separate ext4 loopback test expands a sparse disposable 120Gi disk to 160Gi,
checks a real sentinel hash and accounts for 24 nominal 5000MiB files. Sparse
files are capacity arithmetic, not an allocated 117Gi write/load test. These
tests do not prove Longhorn CSI expansion, StatefulSet adoption, full Harbor
database/auth/retention behavior, production transfer rate, power-loss safety,
or an actual Kubernetes node drain. Production must retain fresh backups,
exact identity and writer/growth fences, measured recovery budgets and a
separately approved maintenance procedure.

The growth guard is a local qualification artifact. No image publication,
production source change, reconciliation, PVC expansion or migration is implied.
