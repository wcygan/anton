---
status: Accepted
date: 2026-10-19
deciders: ['@wcygan']
affects: storage
intent: concrete-need
supersedes: [0019]
superseded-by: null
retrospective: false
---

# 0043 — Keep two SeaweedFS copies for node maintenance

> Keep object data on two serving nodes so planned maintenance does not depend on the sole volume server returning; migrate existing data separately from the new-volume default.

## Status

Accepted by the operator with the exact conditional rollout, migration and
drill in PR 519. This supersedes ADR 0019's native-replication choice; the
canonical standalone S3 path, filers and Longhorn-backed PVCs remain.
Execution and acceptance evidence are maintained in the linked plan and record.

## Context

SeaweedFS `000` stores each native volume on one serving process. Longhorn
replicates its block device, but cannot serve SeaweedFS requests while that
process is absent. Stable volume-server DNS improved replacement recovery;
it cannot keep cold reads available throughout a cordoned node's maintenance.
An October 19 audit finds all 20 native volumes at `000` with one active copy.
Two S3 gateways being Ready does not establish data availability.

The corpus occupies 20/60 logical-volume slots and about 28.1 GiB of reported
volume data across three 120Gi PVCs. These are reported file sizes, including
obsolete contents, rather than live object or allocated-disk measurements.
Longhorn has two block replicas per PVC. There is room for another SeaweedFS
copy, with a recurring application-level write/network cost. The older ADR's
choice to avoid that cost now conflicts with the concrete maintenance goal.

Local testing must distinguish never-read objects from S3 gateway body-cache
hits, exact per-chunk placement from aggregate replica counts, and fresh writes
from reads. The existing-data copy and gateway location caches have separate
safety and convergence requirements.

## Decision

Use native placement `001`: two copies on distinct volume servers in the
current single rack. Retain hard hostname anti-affinity and one volume server
per Kubernetes node, so those servers occupy distinct nodes. Set the master
default for future allocations and `WEED_MASTER_VOLUME_GROWTH_COPY_2=1` to
allocate one two-copy logical volume per growth event.

Migrate all existing native volumes separately. Preserve the empty collection,
Harbor, Loki and read-probe data, all file IDs, PVC identities and source copies.
The default alone is not an existing-data migration. Require a rehearsed
writer-quiescence gate, persistent read-only source state, an exact empty
destination, native targeted copy and source/target file hashes before restoring
writability. A read-only flag alone is insufficient: SeaweedFS 4.40 can have
already-admitted operations queued past that flag.

Treat gateway cache preparation and an actual one-node maintenance hold as
acceptance gates. A placement audit does not establish S3 read/write behavior.
Query every filer backend's `LookupVolume` for both locations before starting
fresh S3 processes. Those processes have independent lookup caches. The master
stream has no snapshot-complete marker, and a healthy GET can use a warm body
cache; only the actual owner-absent cold GET establishes the tested path.
These are planned-maintenance checks, not a general failover guarantee.
This proposal does not promise uninterrupted in-flight requests, general node
failure tolerance, disaster recovery or a solution to filer metadata recovery.
It does not reintroduce the retired lakehouse workloads.

## Alternatives considered

- **Keep `000`** — retains the lowest write/network cost, but data on the absent
  serving process remains unavailable during the maintenance hold.
- **Relax volume Pod anti-affinity** — permits the same Longhorn PVC to reattach
  on another node, but cold reads still wait for detach/attach/startup. It can
  leave two serving Pods on one node after uncordon and needs another move to
  restore placement.
- **Evacuate native volumes before every drain** — avoids permanent double
  SeaweedFS writes, but transfers the node's data on every maintenance window.
  The native move deletes the source after copying/tailing, and allocation on
  the draining server needs its own reliable fence. It leaves one serving copy.
- **Three native copies** — consumes all 60 current slots for the existing
  corpus before growth and adds more write traffic. New three-copy allocations
  would also require the absent third server during a one-node hold.

## Consequences

### Accepted costs

- A second SeaweedFS copy adds about 28.1 GiB of reported file data plus
  indexes/metadata for this baseline; 40/60 slots before new allocations.
  Longhorn still replicates each backing PVC, so the extra application copy
  also incurs block replication. No throughput improvement is claimed.
- New writes during a one-node hold require capacity on both surviving servers.
  Reserve headroom and bound the maintenance window; two existing copies alone
  do not establish write availability.
- A one-time existing-data migration needs a separately approved maintenance
  outage and exact recovery plan. Never downgrade a volume to `000` while two
  registered copies remain: later writes can diverge.
- Abort by retaining source and completed `001` pairs, not by deleting a copy.
  Reverting the Git default affects future allocations and cannot undo copying.
- Existing static credentials, internal exposure, filer metadata architecture
  and the disposable-data/backup policy remain under their existing decisions.

## Follow-ups

Pinned local migration and availability tests passed on 4.40 and 4.48 with
independent review. Track the applied configuration, actual allocations,
existing-volume hashes, cache preparation, approved node hold, recovery and
temporary-resource cleanup in [plan 0027](../plans/0027-improve-cluster-operational-outcomes.md)
and the maintenance record. This decision does not itself mark those live
acceptance gates complete.

## Evidence

- [Maintenance investigation](../notes/2026-10-19-seaweedfs-maintenance-availability.md).
- [Pinned readonly/configuration implementation](https://github.com/seaweedfs/seaweedfs/blob/875cd1f67ea25e8965a4f5ba1e6aaf501ba6b6fa/weed/server/volume_grpc_admin.go).
- [Pinned copy implementation](https://github.com/seaweedfs/seaweedfs/blob/875cd1f67ea25e8965a4f5ba1e6aaf501ba6b6fa/weed/server/volume_grpc_copy.go).
- [Pinned write admission and async queue](https://github.com/seaweedfs/seaweedfs/blob/875cd1f67ea25e8965a4f5ba1e6aaf501ba6b6fa/weed/storage/volume_write.go).
