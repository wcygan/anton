---
status: Accepted
date: 2026-04-11
deciders: ['@wcygan']
affects: storage
intent: concrete-need
supersedes: []
superseded-by: null
retrospective: false
---

# 0005 — Adopt Longhorn as replicated block storage CSI

> Longhorn is anton's Block-category pick under the ADR 0004 framework: 2-replica default, `dataLocality: best-effort`, on the 6× 1 TB spare SSDs. Install and Talos image rebuild are gated on the monitoring-stack successor to ADR 0003 so the consumer and the backend arrive together.

## Status

Accepted

## Context

ADR 0004 ("storage stack framework") committed anton to a best-of-breed shape — a Longhorn-class CSI for replicated Block, an in-cluster self-hosted S3 for Object, File RWX deferred — but explicitly deferred the concrete Block choice to a successor ADR. This is that successor.

Community research on 2026-04-11 confirmed Longhorn is the dominant homelab pick for replicated block in 2025–2026 (~50–60% share in Reddit/HN/blog discussions scoped to k8s homelab), with the Talos community having converged on the `iscsi-tools` + `util-linux-tools` extension path. The alternatives that ADR 0004 shortlisted:

- **OpenEBS Mayastor** — strong benchmarks (Onidel 2025: 45–60k IOPS vs Longhorn 15–20k), but its design target is ≥10 Gbit networking with NVMe-oF and dedicated hugepages. Community reports on consumer 1 Gbit hardware are thin and mostly negative. Clashes with Talos's immutability philosophy via hugepage + specific-kernel demands.
- **Piraeus / Linstor (DRBD)** — actively courted by LINBIT for homelab use (nanibot.net June 2025 confirms it works on Talos), but the DRBD kernel module is a second-class Talos extension path vs `iscsi-tools`. Retained as a runner-up.
- **LocalPV variants** (OpenEBS LocalPV-LVM/ZFS, TopoLVM, local-path-provisioner) — excluded by ADR 0004's principle 2 (replication required).

The binding 1 Gbit constraint drove the replica count: cwiggs (2024-12-26) published a fio benchmark and the finding that *"1 Gbps network will only be able to serve 3 volumes if all of those volumes are running a high intensive workload."* The community pattern on 1 Gbit is **2-replica + `dataLocality: best-effort`**, not 3-replica. Every successor ADR that touches Longhorn performance will cite this finding.

Known 2025 regressions that shape the install plan (discovered during research):

- **longhorn/longhorn#10181** — longhorn-manager CrashLoopBackOff on upgrade if any "error" backup exists; manual CR cleanup required.
- **longhorn/longhorn#10429** — v1.7→v1.8 upgrade friction under specific volume states.
- **siderolabs/talos#11740** — `ext-iscsid` reports unhealthy because default `iscsid.conf` is missing, despite iSCSI working. Noisy but non-fatal on Talos.

The practical implication is that Longhorn is the **safe** pick, not the **painless** pick: pin a specific patch version and test upgrades in a scratch namespace before applying them.

## Decision

Anton adopts **Longhorn** as its replicated block storage CSI with the following defaults:

- **Version**: pinned to a specific v1.8.x patch at install time, re-verified against upstream at the moment the successor app is scaffolded. The framework is not locked to a specific patch number — the scaffold step picks the then-current stable.
- **Default StorageClass**: `longhorn` with `numberOfReplicas: 2`, `dataLocality: best-effort`, `staleReplicaTimeout: 2880` (Longhorn defaults otherwise).
- **Backing disks**: the 2× 1 TB SSDs per node, declared in `talconfig.yaml` as dedicated disks (not shared with the Talos install disk), mounted under `/var/mnt/longhorn/disk1` and `/var/mnt/longhorn/disk2` following the Andrei Vasiliu (2026-02-14) Talos + Longhorn pattern.
- **Talos system extensions**: `iscsi-tools` and `util-linux-tools` added to the Talos installer image. Rolling reinstall across all 3 nodes handled by the `talos-operator` subagent, one node at a time, etcd-quorum-gated.
- **Install timing**: **Accepted-but-deferred install**. The HelmRelease, flux app scaffolding, and Talos image rebuild all fire only when the monitoring-stack successor to ADR 0003 names a concrete consumer. This keeps anton's anti-completionism discipline: no storage installed waiting for a workload that does not yet exist.
- **Upgrade discipline**: every Longhorn minor upgrade is tested in a scratch namespace / separate StorageClass with a throwaway PVC before promoting to the default StorageClass. Version bumps come via Renovate PRs reviewed by the `upgrade-auditor` subagent.

## Alternatives considered

- **OpenEBS Mayastor** — rejected. Designed for ≥10 Gbit NVMe-oF networks; hugepage + kernel prerequisites clash with Talos immutability; consumer hardware community signal is thin and negative. Revisit only if the cluster moves to ≥10 Gbit networking and dedicated storage nodes.
- **Piraeus / Linstor** — retained as a runner-up, not the pick. DRBD-on-Talos extension path is more fragile than `iscsi-tools`, and Longhorn's operational surface is smaller. Revisit if Longhorn v1.8→v1.9 upgrades keep regressing or if DRBD-on-Talos gets a first-class extension.
- **3-replica Longhorn** — rejected. On 1 Gbit, three replicas saturate the cluster's network during rebuilds and give only a marginal durability gain over 2-replica (both survive a single node loss). The 2-replica choice is directly backed by community evidence (cwiggs 2024-12-26).
- **1-replica default + opt-in 2-replica StorageClass** — considered. Offers more flexibility but doubles the StorageClass count to maintain and pushes the replication decision onto every application author. Rejected in favor of a single "safe by default" StorageClass; workloads that need different semantics can opt in via a second StorageClass later.
- **Install now** — rejected. ADR 0004's anti-completionism principle and the absence of any current stateful workload argue for deferring the install until the monitoring stack picks its successor. "Installed and unused" is exactly the pattern that produced the cluster-reset ADR 0001.
- **democratic-csi against TrueNAS** — rejected under ADR 0004's "self-hosted in-cluster" constraint. Also requires a separate TrueNAS box that does not exist.

## Consequences

### Accepted costs

- **Talos image rebuild required before install.** The installer image is rebuilt with `iscsi-tools` and `util-linux-tools` system extensions via factory.talos.dev, and all 3 nodes are rolling-reinstalled one at a time by the `talos-operator` subagent. Budget ~half a day for this step when it fires. This is a non-trivial high-stakes operation and is the single largest cost of this decision.
- **`talconfig.yaml` gains disk declarations** for the 2× 1 TB SSDs per node. Currently undeclared — they only exist in the interview transcript and ADRs 0004/0005. The first-install step writes them into talconfig.
- **Upgrade regressions are a real risk.** Known 2025 issues (#10181, #10429, #11740 above) require scratch-namespace testing before every Longhorn upgrade. This is a recurring operational tax on the cluster, not a one-time cost.
- **1 Gbit network is the performance floor.** Rebuilds saturate the link for tens of minutes. Degraded reads continue during rebuild, but write throughput to any volume mid-rebuild is bottlenecked. Acceptable for homelab; documented so future-self knows what "slow" means here.
- **~3 TB usable capacity** (6 TB raw ÷ 2 replicas) — generous today, enough for the eventual monitoring TSDB/chunks plus a comfortable margin, but not enough to absorb every future stateful workload without rethinking replica count or adding disks.
- **Renovate PR tax.** One more chart tracked, upgrade cadence roughly quarterly at Longhorn's current release rate. Adds to the `upgrade-auditor` subagent's weekly budget.
- **Longhorn becomes a Tier-0 dependency** once installed. A broken Longhorn = every PVC-using workload is broken. This is the cost of moving up from local-path; documented so a future "simplify by removing Longhorn" instinct is measured against the consumer workloads by then.
- **No RWX today.** Longhorn supports RWX via an internal NFS gateway but that is explicitly out of scope per ADR 0004's File-deferred framing. When File is picked, Longhorn's RWX gateway is the frontrunner path.

### What this preserves

- **ADR 0002's architectural line** — replication lives per-PVC on a CSI that does not require Ceph-grade quorum recovery rituals. "HA at the cluster layer, not the storage layer" still holds.
- **Anti-completionism discipline** — the install is gated on a real consumer; nothing ships early.
- **Best-of-breed shape** — Longhorn owns only Block (and eventually File via its gateway). Object remains a separate decision; a regression in Longhorn does not take Object down with it.
- **Optionality for Object** — the Object successor ADR is independent of 0005 and can be written in whatever order makes sense.
- **Upgradeability** — Longhorn's upgrade path is the most documented of the replicated-block candidates. Regressions are visible upstream and the community has runbooks.

## Re-adoption guidance

Not applicable — this ADR is `Accepted`, not `Reverted`. Supersession conditions (the closest equivalent for a forward decision):

1. **Longhorn upgrade regressions become unmanageable** — e.g., two consecutive minor releases fail scratch-namespace testing. Write a successor ADR that picks Piraeus or revisits Mayastor given hardware at that time.
2. **Hardware shape changes** — cluster grows to ≥5 nodes with ≥10 Gbit networking and dedicated storage nodes. Mayastor becomes viable; write a successor ADR.
3. **ADR 0002 is reopened** — if a successor to 0002 relaxes the "no distributed storage" posture, Rook-Ceph returns to the shortlist and 0005 may be reassessed against it.

## Follow-ups

- [ ] **Gate**: wait for the monitoring-stack successor to ADR 0003 to pick a concrete consumer. Do not execute the remaining follow-ups until that decision lands.
- [ ] **Talos image rebuild** — hand off to `talos-operator` subagent. Add `iscsi-tools` and `util-linux-tools` to the factory.talos.dev image URL. Rolling reinstall one node at a time, etcd-quorum-gated, verify each node rejoins before proceeding.
- [ ] **Declare the 6× 1 TB SSDs in `talconfig.yaml`** — per-node disk selectors or user volumes, with wipe and partition handled by talos-operator during the rolling reinstall. Mount at `/var/mnt/longhorn/disk1` and `/var/mnt/longhorn/disk2`.
- [ ] **Scaffold the Longhorn Flux app** — hand off to `flux-app-author` subagent. 3-file pattern (`namespace.yaml` + `ks.yaml` + `helmrelease.yaml`), pin to the then-current v1.8.x patch, bind-mount `/var/mnt/longhorn`, disable the broken `preUpgradeChecker` job per Andrei Vasiliu's Talos + Longhorn writeup, set the default StorageClass with `numberOfReplicas: 2` and `dataLocality: best-effort`.
- [ ] **Re-verify Longhorn upstream status** at install time — known issues #10181, #10429, #11740 and any newer regressions. If new showstoppers exist, pause install and triage.
- [ ] **Post-install smoke test** — scratch namespace with a throwaway PVC, write/read test, controlled node reboot to verify replica failover, capture timings. Document in `docs/` as the baseline the next upgrade must not regress against.
- [ ] **Upgrade discipline policy** — every Longhorn minor version bump is tested in a scratch namespace before promoting to the default StorageClass. Renovate PRs for Longhorn are labeled as requiring `upgrade-auditor` review before merge.
- [ ] **Backup ADR remains outstanding** — not blocked by 0005 but **morally required** before any workload holding irreplaceable data is installed. Longhorn replication is node-loss protection, not app-corruption or ransomware protection.
- [ ] **Object successor ADR** — tracked separately. The Object decision does not block this Block decision; they proceed independently.
