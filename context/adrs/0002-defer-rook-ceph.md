---
status: Deferred
date: 2026-04-10
deciders: ['@wcygan']
affects: storage
intent: concrete-need
supersedes: []
superseded-by: null
retrospective: false
removal-commits: ['889a9662']
---

# 0002 — Defer Rook-Ceph indefinitely (homelab footprint mismatch)

> Rook-Ceph is not part of the post-reset rebuild; distributed HA storage on 3 consumer nodes is the wrong tool regardless of intake discipline.

## Status

Deferred

## Context

Rook-Ceph operator + cluster were part of the April 2026 reset (see ADR 0001) and are the **only** previously-trialled component that is *not* eligible for standard re-adoption. The rest of the reset removals (observability stack, databases, registries, demos) were governance casualties — Rook-Ceph is the one component that was a genuine footprint mismatch.

Removed in commit `889a9662` (`chore(storage): remove rook-ceph operator and cluster`).

## Decision

Rook-Ceph will not return to anton under the current cluster shape. Distributed HA storage on 3 consumer-hardware nodes is the wrong tool independent of intake discipline:

- The operational surface — OSDs, mons, mgrs, PVC lifecycle, recovery rituals at 2am — is not justified by the availability benefit at this scale.
- The failure modes (slow recovery, write amplification under degradation, mon quorum loss) are *worse* on consumer hardware with consumer NVMe than on the kit Ceph is actually designed for.
- The HA story for anton lives at the *cluster* layer (Talos quorum, Flux GitOps, restorable manifests), not at the storage layer. Pushing HA into the storage layer doubles the failure surface without doubling the recovery options.

The current *baseline* for persistent storage on anton is **local-path provisioning + tested external backups** (rsync to off-cluster storage), but this ADR does **not** commit to that being the permanent answer. Object, Block, and File storage alternatives — Longhorn, OpenEBS, MinIO, Garage, SeaweedFS, JuiceFS, NFS-via-CSI, and others — are **explicitly in-scope for separate evaluation** under the standard `cluster-intake` flow. This ADR is narrowly about Rook-Ceph; it does not lock anton into local-path forever and it does not pre-judge any other storage candidate.

This ADR's status is `Deferred` rather than `Rejected` because the decision is contingent on the cluster shape — if the shape changes substantially, even Rook-Ceph itself might become reasonable again. See Re-adoption guidance.

## Alternatives considered

- **Re-adopt Rook-Ceph under standard intake (like the other reset removals)** — rejected. The other removals were governance failures; Rook-Ceph was a fit failure. Putting it on the standard re-adoption shortlist would imply the same path applies, which is misleading.
- **Reject Rook-Ceph outright** — rejected. "Reject" implies the component is unfit *full stop*, but Rook-Ceph is entirely fit for the environments it's designed for. The honest framing is "wrong tool for *this* cluster's current shape."
- **Longhorn, OpenEBS, MinIO, Garage, SeaweedFS, JuiceFS, NFS-via-CSI, or another homelab-appropriate Object/Block/File storage alternative** — **explicitly in-scope for separate evaluation under standard intake**, *not* rejected by this ADR. Several of these have meaningfully smaller operational footprints than Rook-Ceph and may be reasonable fits for anton's hardware shape; each deserves its own intake conversation when there's a concrete candidate to discuss. The reason this ADR doesn't endorse any specific alternative is that none has been concretely proposed yet — that's a future decision, and the storage exploration is one of the things the post-reset rebuild is *for*.
- **Local-path + tested backups as the current baseline** — accepted *as a baseline*, not as the permanent answer. The HA story moves to the cluster layer (Talos + Flux + restorable Git state) and storage stays simple while alternatives are evaluated.

## Consequences

### Accepted costs

- **No HA block storage** on anton until the cluster shape changes. Workloads that strictly require synchronous replication don't fit.
- **Backups are load-bearing.** With no replication at the storage layer, the backup-and-restore runbook is the *only* recovery path for stateful workloads. It must be tested, not folklore.
- **Some software is implicitly off-limits.** Anything whose deployment guide assumes RWX or replicated RWO won't work without a parallel storage story, which is the path this ADR is avoiding.

### What this preserves

- Operational simplicity. Storage failures are local-disk failures, not distributed-system failures. Recovery is "swap the disk, restore from backup," not "guess which OSD is lying."
- Predictable failure modes. The blast radius of a disk failure is one node, not a cluster-wide consistency problem.
- Headroom for the workloads anton actually runs (mostly stateless or single-instance stateful).

## Re-adoption guidance

**Scope reminder**: this section is about re-adopting **Rook-Ceph specifically**. Other storage candidates (Longhorn, OpenEBS, MinIO, Garage, SeaweedFS, JuiceFS, NFS-via-CSI, etc.) are not gated by this ADR — they go through standard `cluster-intake` like any other component.

This ADR can be revisited (re-adopting Rook-Ceph itself) under any of the following:

- **Cluster grows beyond 3 nodes**, with at least 5 nodes that have matching disks and a network capable of replication traffic without starving everything else. Three nodes is below the comfort floor for any distributed storage system.
- **Hardware substantially upgrades** — server-grade SSDs, ECC RAM, redundant networking. Consumer NVMe is *part* of the mismatch; replacing it removes one of several reasons.
- **A specific workload arrives that strictly requires replicated block storage** *and* has been running for >30 days demonstrating that the requirement is real, not aspirational. "I might add app X someday" is not enough; "app X has been running for a month and hits this limitation every week" is the bar.
- **Declared learning intake** — "I want to actually understand why Ceph didn't fit this hardware" is a valid contained-learning angle. It would still need timebox + exit plan + acknowledgement that the data is throwaway, and gates 1–5 of the contained-learning rubric must pass. The graveyard hit becomes the *reason* for the learning intake, not an obstacle.

None of those conditions are true today, so the status is `Deferred` and there is no scheduled revisit.

## Follow-ups

- [ ] Maintain a tested external-backup story for any stateful workload that lands on local-path storage. The decision above is only sustainable if this is real.
- [ ] Revisit if the cluster shape changes (node count, hardware tier) — add a follow-up ADR documenting whatever the new answer becomes.
