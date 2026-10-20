# SeaweedFS durable acknowledgments

The runtime keeps the pinned upstream 4.48 amd64 base and replaces only its Go
`/usr/bin/weed`. The patch is in
`scripts/fixtures/seaweedfs-durability/durable-ack.patch`. Production uses the Go
server roles; inherited Rust binaries are unchanged and are not qualified here.

Build with the repository environment (Go 1.26.7, Python 3.12+ and yq):

```sh
mise exec -- python3 images/seaweedfs-durability/build.py \
  --source-repo /path/to/upstream-seaweedfs \
  --output /path/to/new-private-build
```

The source repository must contain the exact upstream 4.48 commit. The builder
exports immutable source, applies the retained patch, cross-compiles a static
Linux/amd64 binary with trimmed paths and explicit revision identity, builds a
local image, verifies its platform, and retains source/patch/binary/image hashes.
It refuses existing output and performs no publication or cluster operation.
Before creating the image, it checks the actual binary size against the policy
Job's init-copy memory limit and tool-volume capacity, and records those budgets
in the build identity.

Run fault tests in the exported candidate tree and retain their output:

```sh
mise exec -- go test ./weed/storage ./weed/filer/leveldb2
mise exec -- go test -race ./weed/storage ./weed/filer/leveldb2 \
  -run '^TestQualification' -count=5 -v
```

From Anton's repository root, test the exact immutable local image:

```sh
mise exec -- python3 scripts/fixtures/seaweedfs-durability/rehearse.py \
  --image sha256:<verified-local-image-id> \
  --output /path/to/new-private-rehearsal
```

The ten-component local HA lab retains its data across stock → patched → stock
rollback → patched transitions. It checks both gateways, range reads, listings,
multipart objects, fresh writes, Raft quorum, native replication, Harbor Registry
and exact/cold Loki reads. SeaweedFS runs amd64 under local emulation; this is a
compatibility/correctness rehearsal, not a production performance benchmark.

Explicit fsync writes acknowledge only after data and index syncs succeed. Both
inline and batch paths use the existing rollback routine, persisting the
truncated index before truncating data and fencing failed recovery. LevelDB2
requires `sync=true` in its existing store configuration. The data format and
existing LevelDB2 path/partition count are unchanged. The patch does not establish
a metadata quorum, strengthen ordinary non-fsync deletes, or certify physical
power-loss behavior. A crash after an in-flight overwrite's index persists but
before its data barrier or recovery completes can still require offline index
repair. An old-image rollback restores the old acknowledgment gaps. Both patched
write paths refuse to mutate data/index files when their rollback boundary cannot
be established; a Stat error must never masquerade as an empty index.

Publication follows the scoped-robot and archive/platform gates in
`docs/docs/notes/harbor-developer-guide.md`. Stage Kubernetes changes only after
fresh consistent backups and isolation checks; preserve the current replication
policy and original PVC identities. Do not overwrite another operation's pauses.
