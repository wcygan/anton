---
title: SeaweedFS node maintenance
---

# SeaweedFS node maintenance

SeaweedFS currently has one volume server per Kubernetes node. A Longhorn
replica protects a volume server's PVC; it does not serve SeaweedFS reads while
that server is absent. With native placement `000`, an existing object can be
unavailable for the maintenance window even when another S3 gateway is Ready.

## Check existing data placement

From the canonical Anton checkout, run the read-only audit:

```sh
mise exec -- python3 scripts/verify-seaweedfs-maintenance.py \
  --expected-kube-system-uid 5848c42c-b3ec-4003-a02c-becc2c9fa63f \
  --expected-seaweed-uid dce6fb89-c179-4c19-9a98-2bfc7d0aaa73
```

Supply `--expected-context` when an exact locally known context is available.
The command requires the Tailscale operator context, pins every subsequent
read to that context, redacts its tailnet, and bounds the entire observation
to 15 seconds. It performs GETs only. The reported start/end timestamps delimit
separate API reads, rather than an atomic snapshot.

Exit zero means every selected native volume has consistent nonzero replica
placement, matching reported sizes, and active copies on distinct Ready nodes.
The audit joins master topology to the Seaweed-owned StatefulSet, Ready Pods,
their actual Bound PVCs and Kubernetes nodes. Inactive locations, terminating
resources, ambiguous ownership and mismatched identity fail closed. Exit 2
means the condition is unmet or the observation failed; inspect `issues`.
The default selection includes every collection, including the empty collection.
Use repeatable `--collection` arguments only to produce an explicitly partial
report; it does not establish availability of excluded data.

This is a placement check. Matching sizes do not establish matching bytes.
It does not prove S3 reads, writes, cache freshness, in-flight request recovery
or permission to drain a node. Repeat fresh identity and health preflight
immediately before any separately approved maintenance.

## Availability acceptance

A useful maintenance test reads an object that has never been fetched through
the tested gateways and checks its exact digest while a known owning server
is absent. Map that exact object's chunk file IDs and each chunk's owners
before withdrawal. A new OCI client alone is insufficient: the S3 gateway can
serve a warm body cache. A fresh PUT followed by an exact GET tests a different
property and must be recorded separately.

The October 19 baseline has 20 native `000` volumes, each with one active
SeaweedFS location. Stable peer DNS improves replacement recovery, but does not
make this data available while its only serving process is absent. A future
replication-default change must include an existing-data migration and gateway
lookup-cache verification; it cannot pass acceptance from the default alone.

The measured baseline and migration investigation are recorded in
[`2026-10-19-seaweedfs-maintenance-availability.md`](https://github.com/wcygan/anton/blob/main/context/notes/2026-10-19-seaweedfs-maintenance-availability.md).

## Prepared two-copy rollout

The first approved production run on 2026-10-20 stopped before any replication
configuration or copy completed. A native command dialed a retired volume Pod
address after process replacement. All original volumes and service were
restored; the node drain was skipped. See the
[abort and recovery record](https://github.com/wcygan/anton/blob/main/context/notes/2026-10-20-seaweedfs-migration-abort.md).
The existing-data steps below require a revised, verified execution plan before
another maintenance window.

This procedure is a reviewable proposal. Obtain explicit operator approval for
the source rollout, one-time S3 outage, exact copying, temporary test Jobs,
their client/ledger ConfigMap and two egress policies, and
node drill before executing it. The existing-data migration retains every
source file and PVC. It is not an automatic rollback to `000`.

### Preconditions and recovery budget

Verify the expected context and cluster UID immediately before each mutation.
Record exact resource/Pod/PVC UIDs, generations and controller ownership in an
ignored execution ledger. Stop on an unexpected identity, source revision,
writer, volume ID, unhealthy Longhorn volume or missing serving copy.
Require all three nodes schedulable/Ready, healthy etcd, every inventoried
Longhorn volume healthy with all its replicas running, stable Seaweed components and enough
free bytes/slots on every destination. Inventory active bucket-provisioner Jobs
and any direct-volume clients; finish or explicitly quiesce them first.
At 23:27 UTC the inventory was 23 healthy volumes/46 running replicas, including
five restore-test PVCs belonging to the separate 4.48 rollout. Keep those PVCs
and their reader Pods outside this procedure's cleanup scope.

Serialize this window with the separate upgrade/restore owner: no active
SeaweedFS upgrade, restore drill, Harbor retention or other storage change may
overlap. In particular, unmanaged restore-reader Pods must be released by their
owner before a normal drain; do not add `--force` to evict someone else's test.
Require a stable homogeneous runtime version with the matching immutable local
proof, and preserve the latest readiness/telemetry controls when rebasing.
The 4.40 proof does not authorize this migration during a mixed-version 4.48
rollout. Repeat exact version/digest and ownership checks after that owner
finishes, before executing an approved live window. Approval may be conditional
on that owner closing its work; it does not waive this execution gate.

The planned outage budget is 30 minutes from stopping S3 to restoring S3/filer
service. Stop starting copies at 20 minutes and reserve the remainder for
recovery. There is no measured production copy-rate baseline yet. Copy the
largest VID (24, about 4.8 GB) first and measure copy plus hash/control time;
project the remaining bytes and per-VID overhead with a twofold time margin.
Continue only if the remaining work and restoration fit the budget; otherwise
restore service with that checked increment retained and schedule the rest.
Twenty 120-second ceilings are not a demonstrated 20-minute batch duration.
Each copy has a 120-second observation budget; timeout is ambiguous,
not permission to retry. If a copy cannot be validated, retain its files and
keep that VID read-only while restoring verified data/service. An unresolved
data state can exceed the planned outage budget; preserve data and hand off
the exact exception rather than forcing a deadline. A failed migration blocks
the node drain.

S3 access is unavailable during this one-time fence: Harbor pulls/pushes and
Loki object-store flushes can fail or retry. Record Loki WAL capacity, pending
flushes and disk-full counters before starting; stop if the planned buffer
margin is unavailable. Keep ingestion health and queue growth under observation
through recovery. This is a planned outage, not a zero-downtime migration claim.

### 1. Preserve a never-read fixture and roll the new-volume default

Before changing the default, create only bounded synthetic objects under a
unique `_maintenance/<epoch>/` prefix in the existing Harbor S3 bucket. A
temporary Job in `observability` may mount the existing `loki-s3-credentials`
Secret read-only and use it only for the approved exact keys; do not print its
values or copy the Secret. This exposes the existing broad S3 credential to
the temporary test Pod and requires explicit acceptance. A code allowlist is
not a server-side prefix permission boundary. Pin the reviewed client image,
disable API-token automount, use a non-root container with a read-only root
filesystem/no added capabilities, and apply a role-specific egress policy allowing
only DNS and the Seaweed S3 Pods. The credential-free observer has a separate
policy allowing only DNS and filer RPC. Inspect applicable namespace and
cluster-wide policies before claiming isolation; allowed egress combines across
policies. The test program must restrict its operations
to the exact ledger keys and print only status/digests, never error bodies or
authentication headers. Keep client code and the non-secret ledger in one
temporary ConfigMap. Remove both exact policies and that ConfigMap with the Jobs.
Use at most eight 1 MiB seed objects, and no more than twelve ledger keys total
including the later write/recovery checks, to select distinct never-read objects
whose existing `000` VID is in the copy table below and whose planned source/
destination pair includes the exact `k8s-2` node UID. Join both current volume
Pods to nodes; an ordinal can move between nodes during an upgrade. Before the
drain, repeat this join using the actual completed copies. Record whether the
withdrawn copy is the original or the new copy; either tests availability while
one owner is absent, but only original-owner loss can exercise serving from the
new copy.
Record each key,
file ID, VID and digest. Delete only these exact keys during cleanup, not the
bucket or a recursively selected prefix. Require exact-key HEAD 404 before a
seed PUT and after deletion; a HEAD does not fetch the object body. The run ID
and keys still require exclusive ownership because this is not an atomic
conditional create. No credential rotation is involved.

Merge the approved CR default `001` and growth `COPY_2=1` through GitOps.
Observe exact Flux source/apply revision, Seaweed generation and all three
master commands/readiness; keep quorum throughout the master-only rollout.
Confirm the volume StatefulSet template and PVC UIDs did not change. Repeat
the filer path-rule check and verify actual new assignments use `001`; do not
infer this solely from YAML. Re-audit the entire corpus before quiescence.

### 2. Establish owner controls and the master growth fence

Serialize the window with every other storage/retention owner and verify the
fresh independent backup set before replacing any process. Retain exact current
Pod/PVC/node UIDs, source revision, controls and image identities in an ignored
execution ledger. A retired address is never an acceptable RPC target.

Hold `storage/seaweedfs` and `storage/seaweedfs-config` Kustomizations, the
`seaweedfs-operator` HelmRelease and operator Deployment. Record original fields,
including absent suspension flags, then stop the operator and verify its old
process is gone. Apply holds with `--field-manager=flux-client-side-apply` and
check that parent reconciliation does not remove them. Pause both
`seaweedfs-buckets-ensure` and `seaweedfs-durability-ensure`; wait for existing
Jobs to finish. Retain the StatefulSets and all PVCs.

Hold master, volume and filer StatefulSets OnDelete before publishing a changed
Pod template. Use the qualified growth-fence image and temporary startup setting
`WEED_MASTER_VOLUME_GROWTH_DISABLE=true` for every master. Replace one master
at a time, choosing a current nonleader before the leader and requiring Raft
health between replacements. Verify image/binary, startup environment and
count-zero HTTP `/vol/grow`503 without a VID-set change. The old durable1 image
fences background/assignment growth but leaves this HTTP path open.

Where current writable `001` layouts have capacity, this master preparation can
precede the S3 outage. Require actual existing-object reads and fresh writes
after each master; the fence prevents new allocation, so stop if existing
layouts cannot serve traffic. No native replication change occurs in this
phase. A source pin applied under these holds is a recorded temporary owner
exception; final CR, templates and controls must match Git before completion.

After the master fence is verified, stop S3 and then both filers, recording the
outage start and waiting for every old writer process to disappear. Disable
vacuum with the current UID/IP-bound master and the admin lock. There is no
vacuum-state read command at this pin; confirm no other owner holds it and do not
claim a captured in-memory state. Do not treat a readonly flag alone as draining
already-admitted writes. Section 3 establishes the final inventory and process
boundary before copying.

### 3. Copy existing data in exact, checked units

The old fixed 20-volume table is obsolete. Capture every current native VID,
including empty volumes, after the writer and growth fences are established.
Prepare a new exact source/destination plan using current Pod/PVC/node UIDs,
per-server free bytes and slots. The October 20 post-capacity baseline contains
32 logical volumes: 24 singletons and eight two-copy volumes. Migrating these
requires 64 of 72 slots, with projected per-server use 22/21/21. This fits the
copy but no longer guarantees four fresh two-copy allocations with any server
absent. Do not infer maintenance allocation headroom from the earlier 28-volume
rehearsal. Recalculate for any pre-fence allocation; a new VID after the fence
is an abort condition.

Reverify every master's exact qualified image/environment and HTTP503 for the
count-zero growth check. The complete isolated rehearsal covered two background
sweep periods, leader replacement and recovery. Stop if any master or writer
fence has changed since section 2.

Stop S3/filer writers, both provisioning/durability CronJobs and vacuum. Mark
all captured copies persistently read-only, then UID-evict each volume process
serially under OnDelete/PDB control to drain already-admitted writes. Preserve
source PVCs and require the captured native inventory and RO state after every
replacement. Capture final Pod UID/IP/PVC/node bindings only after replacement.

The shell replication command previously dialed a retired address. Use the
qualified direct-RPC path from a pinned, credential-free in-cluster client.
Verify target Pod UID, IP, Bound PVC UID/PV and Ready node before and after each
call. Reject stale bindings. Preserve stable advertised peer DNS.

Configure only the exact read-only source, using its current Pod IP:

```sh
grpcurl -plaintext -max-time 15 \
  -d '{"volumeId":24,"replication":"001"}' \
  <current-source-pod-ip>:18444 volume_server_pb.VolumeServer/VolumeConfigure
```

The example VID is illustrative; use the generated current ledger. Require a
successful structured response, native `001` and persisted read-only `.vif` state.
Before copying, prove the destination neither serves the VID nor contains any
matching collection/VID files, including `.note` or `.copying` remnants.

Copy to the exact current destination IP. `sourceDataNode` must also use the
current UID-bound source IP, because the destination itself dials that address:

```sh
grpcurl -plaintext -max-time 120 \
  -d '{"volumeId":24,"sourceDataNode":"<current-source-pod-ip>:8444"}' \
  <current-destination-pod-ip>:18444 volume_server_pb.VolumeServer/VolumeCopy
```

Parse every streamed response and reject reported errors. A timeout is
ambiguous: stop and retain all destination files; never retry automatically.
Use the largest current volume as a pilot and measure copy, full hashing and
control time. Apply a twofold margin to the remaining work and retain ten
minutes for restoration inside the agreed outage budget. Finish in checked
windows if the measured work does not fit; retain completed verified pairs.

Compare exact source/destination `.dat`, `.idx`, `.vif` SHA-256 while both remain
read-only. Source `.vif` changes at configuration time; compare the configured
source with the copied destination. Require unchanged source data/index hashes,
preserved FIDs, two active native `001` locations and distinct Ready nodes before
advancing. Do not use global repair, delete sources or downgrade a completed
pair to `000`. Abort by preserving original data and completed verified pairs.

### 4. Restore writes, owners and caches

Only after all exact copies pass, mark both copies of each verified pair
writable if the original ledger state was writable; preserve intentionally
read-only originals. The pinned command is `-writable`, not an assumption that
`-readonly=false` restores state:

```text
volume.mark -node=<source-peer>:8444 -volumeId=<VID> -writable
volume.mark -node=<destination-peer>:8444 -volumeId=<VID> -writable
```

Verify both native per-copy states and persisted `.vif` flags, and require the
master's writable layout to contain each originally writable `001` VID before
starting clients. A single writable member is insufficient for assignment.
Rebuild all three master processes one at a time while growth remains fenced,
preserving quorum. Require the rebuilt topology to contain only the verified
current placements before reenabling growth; old empty layout objects must not
resurrect `000` allocations. Enable automatic vacuum as approved and restore
filer replicas to 2. Keep S3
and the operator at zero, Flux suspended and the CronJob paused while checking
the filer maps below. Do not recreate a workload or Secret to bypass recovery
errors.

Query every concrete filer backend's gRPC `LookupVolume` for the migrated VIDs;
require two locations for each, with a bounded wait. The pinned server supports
reflection:

```sh
grpcurl -plaintext -d '{"volumeIds":["<VID>"]}' \
  <one-filer-pod>:18888 filer_pb.SeaweedFiler/LookupVolume
```

Use the actual TLS settings if configured. A temporary pinned observer Job can
make this call in-cluster; it needs no S3 credentials or Kubernetes API token.
Record each filer Pod UID and returned map, rather than using a balanced Service.
Bind the observer to its concrete Pod IP, verify the IP-to-UID join immediately
before and after the Job, and invalidate output if that identity changed.
Only after every map passes, restore S3 replicas to 2 and verify fresh Pod UIDs
and actual S3 reads. These are fresh processes after the approved outage; no
additional gateway reset is needed. Restore the original growth setting with a quorum-safe master rollout after
existing-layout reads/writes pass. Restore the original update strategies only
when all current Pod revisions match the intended templates. Then restore
operator replicas to 1, both CronJobs' original suspension fields and the exact
prior Flux/HelmRelease suspension fields. Verify
desired/applied source, controller generations, readiness and every PVC UID.
A gateway reset clears its own lookup/body caches but does not clear a filer's
map. Readiness, master `/dir/lookup`, and a warm GET do not guarantee either
layer's cache is complete. The next outage test is the final data-path gate.

For a later, separately approved maintenance window, repeat the filer-map gate
for all current VIDs before serially refreshing existing S3 processes; retain
one Ready S3 endpoint throughout that refresh. Do not restart healthy filers
merely to satisfy a gateway reset. If their maps fail the gate, investigate
before draining.

### 5. Verify the approved node hold and clean up

With all components healthy, drain only `k8s-2` (UID
`e8a83ec7-6902-4f39-ae15-8454fdd9e3f4`) through the reviewed `drain:node` helper,
with emptyDir deletion explicitly approved. Preserve PDB enforcement and the
helper's proxy relocation and overall timeout. Immediately before cordon,
join each tested chunk's two active locations to exact volume Pod UIDs and
node UIDs; require one owner on that exact `k8s-2` UID and the other on a Ready
surviving node. Ordinal 1 alone does not prove node identity. If that join fails,
stop this drill rather than changing the approved node or claiming owner loss.
Record current S3/filer Pod UIDs after cache preparation. Cordon the exact node,
then run the helper with fresh expected context, cluster/node UIDs and the
Tailscale operator Deployment UID; it requires an already cordoned node.
Keep the node cordoned for at
most five minutes after drain. Record expected 2/3 master/volume readiness,
healthy surviving Longhorn replicas and at least one Ready S3 endpoint.

While the volume server on the drained `k8s-2` node is absent, verify that exact
location is unavailable and the other location remains Ready. Use new bounded
client Jobs to GET distinct
never-read pre-migration objects through every surviving S3 backend and compare
exact digests. Separately PUT a fresh unique object and GET its exact bytes;
verify its native allocation is `001` on two Ready surviving nodes. Record
request timing relative to the actual hold, per-chunk file IDs/locations and
S3/filer Pod UIDs. A gateway refresh during this test invalidates the intended
acceptance; do not silently reset one to obtain a passing read.
Require the GET and fresh-write client to use the reviewed concrete S3 Pod
IP/UID endpoint, with the IP-to-UID join verified before and after each Job.
A balanced Service response does not establish which backend served the bytes.

Immediately uncordon on a read/write failure or hold deadline, then verify full
Seaweed/Harbor/Loki, node/etcd, Longhorn and Flux recovery. Drain exit alone is
not recovery. Remove only exact temporary Jobs/Pods, the client/ledger ConfigMap,
both egress NetworkPolicies and exact S3 fixture keys; confirm each is absent and restore
every controller, suspension state, replica count
and the approved vacuum state. Keep source data, PVCs, normal credentials and the execution
ledger. Observe stable readiness and the known retry window before closing.

For raw Job deletion, set `DeleteOptions.propagationPolicy` to `Background`
and include exact UID/resourceVersion preconditions. Verify the Job and its
recorded Pods are absent; a successful Job DELETE alone is insufficient.
If completed Pods were orphaned, join their run label and controller UID to
the recorded Job before deleting those exact Pods with UID/resourceVersion
preconditions. Keep the ConfigMap and
egress policies until no test Pod remains.

## Stop and rollback

Before a destination exists, an exact single-source VID can be restored to its
original `000` metadata and writable state with writers still fenced. Once two
copies exist, retain their verified `001` placement; do not downgrade while
both remain registered or delete the new copy to simulate rollback. Reverting
the Git default only affects future allocations.

On an ambiguous copy or mismatched hash, stop new work, retain all files and
keep the affected VID read-only. Inspect the source/target and report exact
state; never blindly retry `volume.copy`, because it can replace destination
files. On a pilot/budget abort, restore untouched single-source VIDs to their
original `000` metadata and original writability after proving no destination
exists. Restore both members of completed verified `001` pairs to the original
writability; retain those pairs. Only ambiguous VIDs stay read-only. Then restore
the service owners. An uncertain VID remains an explicit recovery exception,
blocks the drain and needs a reviewed repair. No force deletion, truncation,
bucket deletion, replica deletion, garbage collection or policy bypass is part
of this plan.
