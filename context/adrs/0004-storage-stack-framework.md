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

# 0004 — Storage stack framework: best-of-breed, no Rook, no external S3

> Anton commits to a best-of-breed storage shape — replicated block via a Longhorn-class CSI, in-cluster S3 from a small shortlist, file RWX deferred — without selecting a concrete tool today. Successor ADRs adopt individual candidates as workloads arrive.

## Status

Accepted

## Context

Three previous decisions converge on the need for this framework:

- **ADR 0001** ("cluster reset and structured rebuild") established that the cluster's failure mode is *completionism*, not the components themselves. The sentence "every real cluster has X" produced almost every removal in the historical graveyard. Any storage decision must be anchored in either a named workload or honestly-declared learning intake, never aspiration.
- **ADR 0002** ("defer Rook-Ceph") indefinitely ruled out Rook on 3 consumer-hardware nodes. Critically, it also drew the architectural line: *"the HA story for anton lives at the cluster layer (Talos quorum, Flux GitOps), not the storage layer."* This does not forbid replication entirely — it forbids the operational complexity of distributed-storage recovery rituals. Lightweight replication that survives `node reboot` without summoning a recovery quorum is a different shape and remains in scope.
- **ADR 0003** ("defer monitoring stack pending object storage") deferred all three observability candidates with the primary re-adoption trigger *"object storage lands on anton for another reason."* The operator has now confirmed that the eventual monitoring stack is the concrete-need anchor for storage. ADR 0004 therefore exists in part to unblock ADR 0003 — but transitively, not directly: 0003 lifts when an object backend is *installed*, not when a framework declares the shortlist.

The cluster shape this framework must fit — verified by interview on 2026-04-11, since `talconfig.yaml` only declares the install disk:

| Item | Reality |
|---|---|
| Nodes | 3 control-plane, no workers, all colocated, consumer hardware |
| Per-node disks | 1× ~500 GB internal install disk (Talos OS), **2× 1 TB SSDs currently unused and undeclared in Talos config** |
| Cluster spare capacity | ~6 TB raw, undeclared |
| RAM per node | 16 GiB minimum (per repo README) |
| Network | Single 1 Gbit NIC per node, MTU 1500, no bonding, no VLANs |
| System extensions installed | None (no iscsi-tools, no util-linux-tools, no nut-client) |
| Currently-installed storage stack | None beyond Talos defaults — no CSI, no StorageClass, no PVCs, no operators |
| Currently-installed backups | None (ADR 0002 listed external rsync as the baseline; tooling is still a follow-up) |

The interview also fixed five hard constraints that the framework must honor. They are recorded explicitly so future ADRs do not re-litigate them by accident:

1. **Self-hosted, in-cluster only for Object.** Backblaze B2, Cloudflare R2, Hetzner Object Storage, AWS S3, and a separate LAN-resident "S3 box" (versitygw on a NAS, etc.) are all out of scope. The only acceptable Object backends are Pods running inside this cluster.
2. **Replicated block, not LocalPV.** A PVC must survive a single node going away long enough that the pod can reschedule. The exact replica count (2 vs 3) and whether replication is per-PVC or cluster-wide is deferred to the successor ADR. Pure LocalPV variants (OpenEBS LocalPV-LVM, OpenEBS LocalPV-ZFS, TopoLVM, the existing local-path-provisioner) do not meet this bar on their own.
3. **File RWX is in scope but deferred,** and when adopted must also live in-cluster. There is no LAN NAS to mount, and the operator does not want to introduce one.
4. **No speculative Talos extension installs.** Several block CSIs require Talos system extensions (Longhorn wants `iscsi-tools` + `util-linux-tools`; Mayastor wants hugepages and specific kernel config). The framework documents the cost per candidate but does not pre-install anything. The successor ADR that picks a candidate is what triggers the rolling Talos image rebuild via the `talos-operator` subagent.
5. **Backups are out of scope of this ADR.** Replicated block storage protects against node loss, not against accidental delete, app corruption, ransomware, or cluster rebuild. The operator has explicitly chosen to handle backups in a separate ADR rather than gate every storage candidate on a backup story. This is recorded as an accepted risk in Consequences.

The intent declared for this ADR is **concrete-need (monitoring stack pending) + honest learning (anton is partly a learning cluster)**. The frontmatter `intent` field records `concrete-need` because that is the binding rubric; learning is the secondary motivator that informs which of multiple passing candidates wins when the successor ADRs run.

## Decision

Anton adopts a **best-of-breed storage stack framework** with the following architectural principles. Concrete tool selection is deferred to per-category successor ADRs.

### Principles

1. **Two tools, not one.** Block storage and Object storage are picked from separate projects, each doing what it is best at, rather than picking a single multi-category tool (e.g. SeaweedFS-for-everything). File RWX, when adopted, may ride on either tool depending on which is operationally lighter at that point — likely the Block tool's RWX gateway. This trades a small amount of duplicated machinery for clearer per-category swap-out paths.
2. **Replicated block via a Longhorn-class CSI.** "Longhorn-class" means: replicates volumes across 2+ nodes at the storage layer, presents standard PVCs and StorageClasses, supports per-PVC replica count, does not require a Ceph-grade quorum recovery ritual, does not require dedicated storage nodes. Longhorn itself is the canonical example and the current frontrunner; equivalent options remain in the shortlist below.
3. **In-cluster S3 from a yellow-flagged shortlist.** All viable self-hosted in-cluster S3 options today carry caveats (stale upstream, pre-1.0 operator, archived parent project). This is acknowledged up front. The shortlist is small, and the successor ADR picks the least-bad option at the moment of adoption rather than the framework picking a winner whose status may have shifted by then.
4. **File RWX deferred and rides on the Block tool when adopted.** The eventual File answer is "Longhorn RWX via its NFS gateway" or "SeaweedFS filer" depending on which Block tool is in place. There is no separate File installation today.
5. **No external S3, no LAN-NAS escape hatch, no Rook re-litigation.** ADR 0002's reasoning binds; the operator has explicitly added the external/LAN exclusions on top. These are not re-arguable inside this framework.
6. **Talos system extensions are added on demand, not speculatively.** Each per-category successor ADR that picks a CSI needing extensions is responsible for the rolling Talos image rebuild. Until then, the cluster's stock Talos installer image is unchanged.
7. **Backups are out of this ADR's scope.** Acknowledged as an open follow-up risk; tracked separately.

### Per-category framework

#### Block storage

**Required shape**: replicated PVCs surviving a single node loss, presented as a standard StorageClass, claimable on the 2× 1 TB SSDs already present per node.

**Active shortlist** (none selected today; successor ADR picks):

| Candidate | Replication model | Talos extensions needed | Network constraint on 1 Gbit | Maturity | Notes |
|---|---|---|---|---|---|
| **Longhorn** | Per-PVC, 2 or 3 replicas, async or sync | `iscsi-tools` + `util-linux-tools` | Rebuilds saturate 1 Gbit; degraded reads OK | Mature, CNCF Incubating | Frontrunner. Native RWX via internal NFS gateway covers the future File category. Operationally the simplest of the three. |
| **OpenEBS Mayastor (Replicated PV)** | NVMe-oF over IP, 1-3 replicas | hugepages + NVMe-oF kernel modules + specific kernel config | Designed for ≥10 Gbit; **likely a poor fit on 1 Gbit** | Mature core, complex install | Strongest performance ceiling but the network is the bottleneck here. Documented for completeness, not currently recommended. |
| **Piraeus / Linstor (DRBD)** | Per-PVC DRBD replication | `drbd` kernel module (Talos extension) + Linstor satellite per node | Rebuilds heavy on 1 Gbit | Mature core, heaviest operational surface | The most "enterprise" option. Considered if Longhorn fails for an unforeseen reason. |

**Explicitly excluded under principle 2**: OpenEBS LocalPV-LVM, OpenEBS LocalPV-ZFS, TopoLVM, native local-path-provisioner. These are LocalPV-only and would require an app-layer replication story for every stateful workload.

**Capacity math** (per node, 2× 1 TB SSDs = 2 TB raw): at 2-replica that's effectively 1 TB usable cluster-wide once a single PVC's data lives on two nodes; at 3-replica it's ~666 GB usable. Sufficient for the monitoring stack's TSDB / chunk needs and a comfortable margin for early adopters.

**Network reality**: 1 Gbit per node means initial replica builds and full-node rebuilds will saturate the link for tens of minutes. Acceptable on a homelab cluster; not acceptable for production-grade SLAs. This is one of the implicit reasons Mayastor is documented but not preferred.

#### Object storage

**Required shape**: an S3-API-compatible endpoint backed by PVCs from the chosen Block CSI (or by raw spare disk if the candidate supports a direct backend), exposed inside the cluster, optionally exposed via HTTPRoute on `envoy-internal` or `envoy-external`.

**Active shortlist** (none selected today; successor ADR picks):

| Candidate | Upstream status (verified 2026-04-11) | Storage backend | Operator quality | Notes |
|---|---|---|---|---|
| **Garage** | `main-v2` last commit 2024-12-17 (~16 months stale), 88 tags, AGPL-3 | PVC-backed, single binary | In-repo Helm chart at `script/helm` (minimal but present) | Smallest operational surface. Architectural simplicity is the main appeal. Stale upstream is the main risk; community fork activity is the trigger to revisit. |
| **SeaweedFS S3-gateway-only mode** | Core repo very active (31.5k★) | PVC-backed filer + S3 gateway | `seaweedfs-operator` v0.1.13 (2026-02-03), pre-1.0, README "Maintenance and Uninstallation: TBD" | Core is healthy; the operator and uninstall story are the yellow flags. Use the gateway-only deployment, not the full filer-as-everything pattern, to keep scope contained. |
| **MinIO standalone server (NOT the operator)** | Server binary still released; **operator archived 2026-03-20** (`minio/operator` v7.1.1 was the last release, 2025-04); **`minio/minio` parent archived 2026-02-13** | PVC-backed | N/A — deployed via plain Helm chart, no operator | Documented as a fallback only. The parent project is archived, which is a strong signal even if the binary still works. Picked only if Garage and SeaweedFS both regress further. |

**Explicitly excluded** under hard constraint 1 and ADR 0002:
- External providers (Backblaze B2, Cloudflare R2, Hetzner Object Storage, AWS S3) — operator's self-hosted in-cluster requirement.
- LAN-resident self-hosted S3 (versitygw on a NAS, MinIO on a separate mini-PC) — same requirement; "in-cluster" means inside k8s, not "on-premises."
- Rook-Ceph RGW — ADR 0002 indefinitely defers any Rook-based deployment shape.
- Zenko (multi-cloud controller, wrong tool for self-hosted single-cluster).
- OpenEBS-as-S3 (does not exist as a supported pattern).

**Selection trigger**: the first ADR in the monitoring-stack family that names the Object backend it needs. Most likely candidate: a successor to ADR 0003 selecting Grafana LGTM (Loki, Mimir, Tempo all want object) or VictoriaMetrics-Logs (which would also want object for log storage long-term). The successor ADR is responsible for installing both the object backend and the monitoring stack — not 0004.

#### File storage (RWX)

**Status**: deferred. No candidate selected, no installation planned, no successor ADR queued.

**Required shape when adopted**: ReadWriteMany PVCs that multiple pods on different nodes can mount simultaneously, served from inside the cluster (no LAN NAS allowed).

**Documented shortlist for the eventual successor ADR**:

| Candidate | Pattern | Depends on | Notes |
|---|---|---|---|
| **Longhorn RWX gateway** | Internal NFS server pod sidecar that re-exports a Longhorn block volume as RWX | Longhorn (Block category already chosen) | The cleanest path *if* Block is Longhorn. Single tool handles two categories with minimal extra installation. |
| **SeaweedFS filer + CSI** | Filer pods + CSI driver mount paths from the filer namespace | SeaweedFS (Object category already chosen) | Cleanest path *if* Object is SeaweedFS. Re-uses the deployment that's already running for S3. |
| **JuiceFS** | POSIX filesystem on top of an S3 backend + a metadata engine (Postgres / Redis / etc.) | Object category + metadata DB | Architecturally interesting but adds a second dependency (the metadata engine) to a category we're trying to keep simple. Documented but unlikely to be chosen. |

**Excluded**:
- NFS-via-CSI against a LAN NAS — operator's hard constraint, no NAS exists.
- GlusterFS, MooseFS — both unmaintained / declining, no upstream Helm story worth adopting.
- CephFS — would re-introduce Rook (ADR 0002).

**Trigger to revisit**: the first workload whose operational story actually requires RWX. Likely candidates if/when they arrive: a media stack (Jellyfin + *arr applications sharing a media library), Nextcloud, an ML workload sharing model weights across pods. Until then, the framework explicitly does not install or pre-pick anything for File.

## Alternatives considered

### Alternative 1 — Single-tool stack (SeaweedFS for Block + Object + File)

SeaweedFS is one of the few projects that can plausibly serve all three categories: S3 for Object, filer + CSI for File, and a CSI driver for Block (volumes carved out of the filer namespace). This would minimize the number of installs to one stack and one set of CRDs.

- **Why considered**: lowest total operational surface in the "happy path." High learning value as one architecture to understand end-to-end.
- **Why rejected**: SeaweedFS-as-block is not its native role and is unusual at production scale; the `seaweedfs-operator` is pre-1.0 with an explicit "Maintenance and Uninstallation: TBD" note in its README; the failure mode of a single-tool stack is that *all three categories fail at once* if the tool regresses. Best-of-breed isolates the failure surface even though it doubles the install count. Operator preference, recorded during the interview, is best-of-breed.

### Alternative 2 — All three categories standardized in one ADR with concrete winners picked today

An earlier framing of this ADR would have picked Longhorn for Block, Garage *or* SeaweedFS for Object, and a placeholder for File, all in 0004 directly. This is the "lock everything in" shape.

- **Why considered**: stronger architectural statement, less ambiguity when a workload arrives.
- **Why rejected**: every concrete pick made today is a pick made before the workload that needs it has been named. ADR 0001's "completionism is the failure mode" lesson explicitly warns against this. The framework approach defers the irreversible decisions to the moment they actually pay rent.

### Alternative 3 — External S3 for Object (Backblaze B2, Cloudflare R2, Hetzner Object Storage)

For ~$5–10/month in typical homelab volumes, external S3 dodges every k8s-native S3 candidate's yellow flags entirely.

- **Why considered**: operationally simpler than any in-cluster S3 today; no upstream-archived risk; backups for free as a side effect.
- **Why rejected**: operator's hard constraint, recorded explicitly during the interview. Self-hosted in-cluster is non-negotiable for this ADR. A future ADR may relax this if circumstances change (e.g., a long-running outage of an in-cluster S3 candidate makes the trade-off lopsided), but it would have to do so explicitly.

### Alternative 4 — LAN-resident self-hosted storage (versitygw on a NAS, MinIO binary on a separate mini-PC)

The blog post that triggered this whole intake (https://blog.feld.me/posts/2026/04/i-just-want-simple-s3/) recommends versitygw running directly on a host filesystem. This is "self-hosted" but not "in cluster."

- **Why considered**: dodges every k8s-native operator-quality concern, very fast on LAN, trivial to install on a dedicated box.
- **Why rejected**: same hard constraint as Alternative 3 — operator explicitly required in-cluster, and there is no NAS/spare host to put it on.

### Alternative 5 — Defer all three categories indefinitely (no framework, just principles)

ADR 0004 could be even smaller: just the principles section, no per-category shortlists, no explicit candidates.

- **Why considered**: maximum cautiousness, smallest immutable doc, smallest re-litigation surface.
- **Why rejected**: the per-category shortlists are the actual *value* of a framework ADR — they capture the work that has already been done (the S3 evaluation memory at `.claude/agent-memory/cluster-intake-gatekeeper/project_s3_shortlist_apr2026.md`, the Talos extension survey, the capacity math) so the next intake does not redo it. Stripping them out wastes that work.

## Consequences

### Accepted costs

- **Monitoring blindness continues** until a successor ADR actually installs an object backend and unblocks ADR 0003. The framework alone changes nothing about today's diagnosability — `kubectl logs` and `kubectl top` remain the only options.
- **No backup story.** Replicated block protects against node loss only. Accidental delete, app corruption, ransomware, and full cluster rebuild are unprotected. This is an explicit trade-off the operator has chosen to handle in a separate (not-yet-written) ADR. **A future stateful workload that holds irreplaceable data should not be installed before that backup ADR exists** — flagged in Follow-ups.
- **The shortlists will decay.** Every "verified upstream status (2026-04-11)" claim in this document is fresh today and will be stale within months. Garage's commit cadence, MinIO's archival, and SeaweedFS-operator's pre-1.0 status are all moving targets. The successor ADR that actually picks a candidate is responsible for re-verifying upstream status at that point — this framework's shortlists are guidance, not a guarantee.
- **Best-of-breed costs two installs instead of one.** Two HelmReleases, two namespaces, two upgrade cadences, two Renovate PR streams. Worth it for failure-surface isolation; documented so a future-self does not "simplify by consolidating" without re-running this comparison.
- **Talos extensions remain unbuilt.** When Longhorn is eventually picked, the Talos installer image will need to be rebuilt with `iscsi-tools` and `util-linux-tools` and rolled to all three nodes. This is a non-trivial high-stakes operation handed off to the `talos-operator` subagent. Budget half a day for that step inside the successor ADR's implementation.
- **1 Gbit network is the floor, not a target.** Replicated block over 1 Gbit means rebuilds saturate the link. This is acceptable for a homelab but rules Mayastor out by default and means the successor ADR should test rebuild behavior under realistic load before declaring the install successful.

### What this preserves

- **Optionality across all three categories.** No premature lock-in. Each successor ADR runs its own intake against fresh upstream status.
- **The work already done is captured.** The S3 evaluation, the Talos extension survey, the hardware reality, the capacity math, the architectural principles — all of it is now in one immutable place that the next interview can start from.
- **ADR 0002's architectural line is honored.** No Rook, no distributed-storage recovery rituals, no betting cluster availability on the storage layer.
- **Anti-completionism discipline holds.** Nothing is installed for "we might need this someday" reasons. Every successor ADR will need to name a workload.

## Re-adoption guidance

This ADR is `Accepted`, not `Reverted` — re-adoption guidance does not apply in the standard MADR sense. However, the framework itself can be **superseded** under any of the following:

1. **A successor category-specific ADR is written** that adopts a concrete candidate. The framework remains in force; only that category moves from "shortlisted" to "selected." The successor ADR cites this one in its Context.
2. **The hardware shape changes** (more nodes, more disks, faster network, ECC RAM, etc.) such that ADR 0002's "wrong tool for 3 consumer nodes" reasoning no longer binds. At that point, both 0002 and 0004 should be revisited together.
3. **A hard constraint relaxes.** If the operator decides external S3 is acceptable after all, or that a LAN NAS is on the table, or that backups must be folded into 0004, the framework needs a successor ADR that records the change explicitly. Edits to this body are forbidden.
4. **Best-of-breed proves wrong in practice.** If the eventual successor ADRs land Longhorn + Garage and the operational reality is that two tools are too much, a successor ADR can switch to single-tool (SeaweedFS-for-everything) — but only with concrete evidence from the dual-stack experience, not as a fresh aesthetic choice.

## Follow-ups

- [ ] **Successor ADR for Block** — picked when the monitoring stack (or any other stateful workload) is ready to install. Will include the Talos image rebuild as an in-scope step. Likely Longhorn unless upstream status has shifted.
- [ ] **Successor ADR for Object** — paired with the Block ADR or written separately, depending on which workload lands first. Re-verify Garage, SeaweedFS, MinIO upstream status at the moment of writing.
- [ ] **Successor ADR for backups** — entirely separate concern, not blocked by 0004 but **morally required** before any workload holding irreplaceable data is installed. This ADR should be written *before* the second stateful workload, not after.
- [ ] **Successor ADR for File RWX** — only when a workload demands it. No need to write speculatively.
- [ ] **Update ADR 0003's Re-adoption section** — once an Object successor ADR actually installs a backend, ADR 0003's primary trigger fires and a 0003-successor selecting the monitoring stack becomes writeable. Do not edit 0003 itself; write a new ADR that supersedes it.
- [ ] **Re-verify upstream status of all shortlisted candidates** at the moment any successor ADR is written. Treat the dates in this document as decaying.
- [ ] **Document the spare-disk hardware reality in `nodes.yaml` or `talconfig.yaml`** at some point — currently the 6× 1 TB SSDs only exist in interview transcripts and this ADR. The first Block successor ADR must declare them in Talos config as part of the install.
