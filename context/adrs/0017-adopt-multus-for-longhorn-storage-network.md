---
status: Accepted
date: 2026-04-18
deciders: ['@wcygan']
affects: networking, storage
intent: concrete-need
supersedes: []
superseded-by: null
retrospective: false
---

# 0017 — Adopt Multus CNI for Longhorn storage network

> Adopt Multus (thick-plugin mode) as a meta-CNI chained to Cilium so Longhorn can attach replica traffic to the SFP+ full mesh via a NetworkAttachmentDefinition.

## Status

`Accepted`

## Context

ADR 0009 accepted a 10 Gbit SFP+ full mesh as anton's replicated-storage fabric. The mesh is physically cabled, link-up on all six X710 ports, and per-port MAC mapping was discovered on 2026-04-18 via ARP-probe + node-exporter RX-counter deltas (see `context/hardware.md`). Plan 0001 Phase 3's fio baseline confirmed Longhorn replica throughput is currently capped by the 2.5 GbE management path, which is the motivating pain ADR 0009 was written to fix.

Longhorn's `storageNetwork` feature routes replica traffic onto a secondary interface, but requires a Kubernetes `NetworkAttachmentDefinition` (NAD) — a CRD owned by Multus. Cilium alone cannot expose a NAD: secondary network attachments are not part of its API surface. The options for acquiring a NAD are (a) Multus as a meta-CNI chained after Cilium, (b) swap CNIs entirely, or (c) do nothing and leave Longhorn on the 2.5 GbE path indefinitely. ADR 0009 flagged Multus explicitly as an expected follow-up, gated on the `cluster-intake` rubric.

The intake gate ran on 2026-04-18 with intent `concrete-need`. All seven hard gates passed (permissive Apache-2.0 license; blast radius bounded to storage-network attachment; removable in <30 min via Helm uninstall + CRD delete; chains cleanly to Cilium rather than forking the CNI stack; no secrets surface; Longhorn is the only consumer at adoption and already has a restore path; honest need tied to plan 0001 fio data). Weighted soft score 25/34 cleared the 22 threshold. The do-nothing tiebreaker mechanically falls to 25 vs 28 (−3) because "do nothing" keeps everything symmetrical by definition — this is overridden here because Multus is a decided-ADR dependency, not speculative intake, and the tiebreaker exists to catch adds that accrete without a driver.

## Decision

We will adopt **Multus CNI in thick-plugin mode** as a meta-CNI chained to Cilium. Multus will be installed via its official Helm chart under `kubernetes/apps/network/multus/` using the anton 3-file Flux pattern (`flux-app-author` / `add-flux-app`). The NetworkAttachmentDefinition for the SFP+ mesh, and the Longhorn `storageNetwork` wiring that consumes it, are deferred to plan 0004 (execution plan for the ADR 0009 follow-up).

Longhorn will be the sole NAD consumer at adoption. Any future candidate to consume a second NAD is a separate intake.

## Alternatives considered

- **Do nothing** — leaves Longhorn replica traffic on the 2.5 GbE management path, permanently capping the storage fabric below what the cabled hardware can deliver. The whole point of ADR 0009 was to fix this; do-nothing voids that decision.
- **Swap CNIs to one that exposes secondary attachments natively** — strictly larger blast radius than adding Multus. Rip-and-replace of a healthy Tier-0 component to avoid a +1 DaemonSet is a bad trade.
- **Multus thin-plugin mode** — older deployment shape where the plugin runs in the kubelet's CNI dir rather than as a managed DS. Thick mode is the upstream recommendation for v4+; it scopes failures to the DS and keeps upgrades Flux-native.

## Consequences

### Accepted costs

- **+1 DaemonSet per node** (Multus controller/agent) and **+1 CRD** (`NetworkAttachmentDefinition v1`) — small, bounded footprint.
- **+1 Renovate cadence** — Multus chart releases join the monthly PR queue.
- **Operational coupling to CNI upgrades** — Cilium upgrades now need to co-verify Multus chain health. This is absorbed into the existing `upgrade-auditor` flow.
- **Longhorn restore-runbook obligation unchanged** — Multus does not itself own data; Longhorn's existing backup/restore path under plan 0001 continues to apply.

### Expected outcome

- Plan 0004 Phase 3 `iperf3` gate targets **≥9 Gbit/s** per link with jumbo frames enabled, vs the current 2.5 GbE baseline. If the gate misses, plan 0004 (not this ADR) is where we re-evaluate.

## Re-adoption guidance

N/A — status is `Accepted`, not `Reverted`.

## Follow-ups

- [ ] Scaffold `kubernetes/apps/network/multus/` via `flux-app-author` (3-file pattern + OCI HelmRepository + thick-mode values).
- [ ] Author plan 0004 (`0004-sfp-mesh-multus-storagenetwork.md`) covering: /31 Talos networkInterface config on all 3 nodes (rolling), iperf3 baseline gate, NAD creation, Longhorn `storageNetwork` wiring, replica-byte verification via node-exporter counters.
- [ ] Exit plan (for reference): `helm uninstall` Multus, delete `NetworkAttachmentDefinition` resources, delete the CRD, disable Longhorn `defaultSettings.storageNetwork`. Expected <30 min.
