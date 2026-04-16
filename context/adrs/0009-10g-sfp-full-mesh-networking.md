---
status: Accepted
date: 2026-04-15
deciders: ['@wcygan']
affects: networking
intent: concrete-need
supersedes: []
superseded-by: null
retrospective: false
---

# 0009 — Adopt 10 Gbit SFP+ full-mesh networking for storage replication

> Three passive DAC cables form a direct 10 Gbit full mesh between the MS-01 nodes, removing the 2.5 GbE network as the storage-replication bottleneck for Longhorn (ADR 0005) and future monitoring TSDB writes (ADR 0007).

## Status

Accepted

## Context

ADR 0005 adopted Longhorn with 2-replica block storage and documented the binding network constraint: *"1 Gbit network is the performance floor. Rebuilds saturate the link for tens of minutes."* The actual RJ45 ceiling is 2.5 Gbit, but real-world throughput with protocol overhead is ~250–300 MB/s — roughly 3× slower than the WD_BLACK SN7100 data drives' sustained sequential write floor (~850 MB/s post-SLC-cache). The network, not the drives, is the replication bottleneck.

With kube-prometheus-stack adopted (ADR 0007), Prometheus TSDB compaction and write-ahead log traffic will add continuous inter-node replication load on top of Longhorn's existing replica sync. Two storage-heavy workloads sharing a 2.5 Gbit link is the scenario ADR 0005 flagged as degraded.

Each MS-01 chassis ships 2× 10G SFP+ ports on an Intel X710 NIC (see `context/hardware.md`). These ports are currently unused — all cluster traffic runs over a single 2.5 GbE RJ45 per node on the 192.168.1.0/24 management subnet. With 3 nodes and 2 SFP+ ports each, a **full mesh** (each node directly cabled to every other node) uses exactly the available ports with no switch required.

The routing mechanism is standard Linux subnet-based routing: each SFP+ interface gets an IP on a dedicated subnet (separate from the 192.168.1.0/24 RJ45 network), and the kernel routing table sends packets to whichever interface's subnet matches the destination IP. The SFP+ interfaces carry no default route, so only traffic explicitly destined for the SFP+ subnets traverses them — management traffic stays on RJ45 automatically. Making Longhorn *use* those subnets requires Multus, which gives Longhorn engine and replica pods a second network interface with an IP on the SFP+ subnet. Longhorn's `storageNetwork` setting tells it to replicate via those second interfaces, so replica traffic hits the SFP+ routing entries and goes out the 10G links.

The practical speed improvement is ~2.8×, not the theoretical 4×. Wire speed rises from 2.5 Gbit to 10 Gbit, but the WD_BLACK SN7100's post-SLC-cache sustained write floor (~850 MB/s) becomes the bottleneck before the 10G link saturates (~1.1 GB/s real-world). So sustained Longhorn rebuild throughput goes from ~300 MB/s (network-limited) to ~850 MB/s (drive-limited). The bottleneck moves from a shared resource (one network link) to per-node resources (individual drives), which is architecturally healthier — one node's rebuild no longer starves another node's writes.

k8s-2 note: the SFP+ ports are on the Intel X710 (PCIe device), unrelated to the DIMM slot timing issue and the absent second NVMe documented in the talos-operator RCA. Both SFP+ ports on k8s-2 are expected to function normally.

## Decision

Anton adopts a **10 Gbit SFP+ full-mesh** network as a dedicated storage-replication overlay:

- **Cables**: 3× [Cable Matters 10Gbps DAC Twinax SFP Cable](https://www.amazon.com/dp/B00U8BL09Q) — 10GBASE-CU Passive Direct Attach Copper, 1m / 3.3ft. Passive DAC: no transceivers, no power, no firmware.
- **Topology**: full mesh — k8s-1↔k8s-2, k8s-1↔k8s-3, k8s-2↔k8s-3. Each node uses both SFP+ ports.
- **IP addressing**: point-to-point /31 subnets on a dedicated range. Each of the 3 links gets its own /31 (6 IPs total). Exact addresses assigned at cabling time after discovering SFP+ MAC addresses via `talosctl get links`.
- **MTU**: 9000 (jumbo frames) on all SFP+ interfaces. Point-to-point links with no intermediate switch — no MTU negotiation risk.
- **Talos config**: additional `networkInterfaces` entries in `talconfig.yaml` per node, selected by `hardwareAddr`. Static IPs, no DHCP, no default route (storage overlay only).
- **Existing network unchanged**: the 192.168.1.0/24 RJ45 network continues to carry API server, Cilium, DNS, Tailscale, and all non-storage traffic. The VIP (192.168.1.101) stays on RJ45.
- **Longhorn binding**: Longhorn's `storageNetwork` directs replica traffic onto the SFP+ mesh via Multus (see routing mechanism in Context). Requires a Multus install and a `NetworkAttachmentDefinition` — both are follow-ups gated on this ADR's physical assembly.

## Alternatives considered

- **Do nothing** — keep all traffic on 2.5 GbE RJ45. Longhorn rebuilds remain bottlenecked at ~300 MB/s. Rejected: the SFP+ hardware already exists in every node; the only cost is $30 in cables to unlock a 4× throughput improvement.
- **10G managed switch** (e.g., Mikrotik CRS305-1G-4S+IN) — star topology, VLAN tagging, future expandability. Rejected: $200+ for a switch serving 3 nodes; adds a single point of failure and a power draw; the full mesh uses the existing ports with zero additional hardware.
- **Daisy chain** (k8s-1↔k8s-2↔k8s-3) — 2 cables, 1 free port per end node. Rejected: k8s-1↔k8s-3 traffic traverses k8s-2, adding latency and making k8s-2 a single point of failure for that path. Asymmetric topology complicates Longhorn placement.
- **Bond SFP+ with RJ45** — aggregate 10G and 2.5G links. Rejected: bonding different-speed interfaces has well-known load-balancing problems; separate networks (management on RJ45, storage on SFP+) is operationally cleaner.

## Consequences

### Accepted costs

- **$30 one-time** for 3 DAC cables. Zero recurring cost — passive copper, no optics to fail.
- **Talos config complexity increases.** Each node goes from 1 `networkInterfaces` entry to 3 (one RJ45 + two SFP+). Manageable: `talconfig.yaml` is the single source of truth, `task configure` validates.
- **Multus required for Longhorn storageNetwork.** Multus is a thin meta-CNI that delegates to Cilium for primary networking. Its intake is a follow-up. Without Multus, the SFP+ links are up and verifiable with iperf3 but Longhorn won't automatically bind replica traffic to them.
- **SSD write floor becomes the new ceiling.** As detailed in Context, sustained throughput improves ~2.8× (300 MB/s → 850 MB/s) before the SN7100 drive becomes the bottleneck. Enterprise SSD upgrade (e.g., Micron 7450 Pro) is a separate future decision if that ceiling needs to move.
- **Physical cabling required.** Operator must be onsite. Not remotely executable.
- **Jumbo frame boundary.** SFP+ at MTU 9000 vs RJ45 at MTU 1500. Mitigated: separate subnets, no cross-routing, no shared default route.

### What this preserves

- **Existing 2.5 GbE is untouched.** API server, Cilium, DNS, Tailscale, and all management traffic are unaffected. The SFP+ mesh is additive.
- **Full rollback in 15 minutes.** Unplug cables, remove Talos interface config, re-apply. No data migration.
- **ADR 0005's Longhorn shape is enhanced, not changed.** Same 2-replica, same `dataLocality: best-effort`, faster replica sync.
- **ADR 0005 supersession trigger #2** ("≥10 Gbit networking") moves closer to firing for the Mayastor re-evaluation, though the other conditions (≥5 nodes, dedicated storage nodes) remain unmet.

## Follow-ups

- [ ] **Buy cables**: 3× Cable Matters 10Gbps DAC Twinax SFP Cable, 1m, 10GBASE-CU passive.
- [ ] **Physical assembly (onsite)**: plug cables in full-mesh pattern. Discover SFP+ MAC addresses via `talosctl get links`. Record MACs in `context/hardware.md`.
- [ ] **Talos config**: add SFP+ `networkInterfaces` to `talconfig.yaml` — select by `hardwareAddr`, assign /31 IPs, MTU 9000, no default route. Apply via `task talos:apply-node` one node at a time.
- [ ] **Verify links**: `talosctl get links` (confirm UP), `iperf3` between each pair (expect ~9.4 Gbit/s with jumbo frames).
- [ ] **Multus intake**: run `/cluster-intake` for Multus as a Longhorn storageNetwork dependency.
- [ ] **Longhorn storageNetwork**: after Multus, create a `NetworkAttachmentDefinition` and configure Longhorn's `storageNetwork`. Verify replica traffic via node-exporter interface byte counters.
- [ ] **Update `context/hardware.md`**: add SFP+ MACs, link topology, and cable part numbers.
- [ ] **SSD upgrade evaluation**: once 10G + Longhorn are both live, benchmark sustained writes. If the SN7100's ~850 MB/s floor is the measured bottleneck, evaluate enterprise NVMe as a separate ADR.
