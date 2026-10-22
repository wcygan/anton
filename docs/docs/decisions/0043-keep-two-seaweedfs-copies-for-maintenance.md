---
status: Superseded-by 0044
date: 2026-10-19
deciders: ['@wcygan']
affects: storage
intent: concrete-need
supersedes: ['0019']
superseded-by: 0044
retrospective: false
slug: /decisions/0043-keep-two-seaweedfs-copies-for-maintenance
---

# 0043 — Keep two SeaweedFS copies for node maintenance

> Store each SeaweedFS volume on two serving nodes, so planned maintenance does not wait for one volume server to return; migrate existing data separately.

_Public edition prepared on 2026-10-21 from the original record; decision date and meaning retained._

:::caution Superseded
[ADR 0044](0044-use-stock-shared-s3-with-planned-downtime.md) retired this decision's uninterrupted-maintenance goal. The two-copy placement it introduced remains in place.
:::

## Context

With replication `000`, each SeaweedFS volume is served by one process. Longhorn replicates the block device underneath, but cannot serve SeaweedFS requests while that process is down, so cold reads stop for the whole time a node is in maintenance. An October 19 audit found all 20 native volumes at `000`, with one active copy each. Two Ready S3 gateways do not show that the data is available.

The data used 20 of 60 logical-volume slots and about 28.1 GiB of reported volume data across three 120Gi PVCs, leaving room for a second copy. [ADR 0019](0019-seaweedfs-on-canonical-spec-s3.md) had avoided that cost; the new maintenance goal outweighed it.

## Decision

Use placement `001`: two copies on different volume servers. Hard hostname anti-affinity keeps one volume server per node, so the copies land on different nodes. Set this as the master default, and grow one two-copy volume at a time.

Migrate existing volumes as a separate, approved operation. Preserve every file ID, PVC identity, and source copy. Before restoring writability, require a rehearsed writer-quiescence gate, a read-only source, an empty destination, a native targeted copy, and matching file hashes on source and target. A read-only flag alone is not enough: SeaweedFS 4.40 can still process operations admitted before the flag.

Gateway cache preparation and a real one-node maintenance hold are acceptance gates. A placement audit does not show S3 behavior; only a cold read with the owning server absent tests the path. These are planned-maintenance checks, not a promise of general failover, disaster recovery, or uninterrupted requests.

## Alternatives considered

- **Keep `000`:** cheapest, but data on the absent server is unavailable during maintenance.
- **Relax volume pod anti-affinity:** cold reads still wait for detach, attach, and startup, and placement may need restoring afterward.
- **Evacuate volumes before each drain:** moves a node's data every time, and still leaves one copy.
- **Three copies:** fills every current slot before growth, and a one-node hold would block new allocations.

## Consequences

The second copy adds about 28.1 GiB of reported data plus metadata at this baseline, using 40 of 60 slots, and Longhorn replicates that copy too. Writes during a one-node hold need capacity on both surviving servers. Never downgrade a volume to `000` while two copies remain, because later writes could diverge. To abort, keep the source and any completed pairs rather than deleting a copy; reverting the default affects only future volumes.
