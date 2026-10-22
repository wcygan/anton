---
status: Accepted
date: 2026-04-18
deciders: ['@wcygan']
affects: networking, storage
intent: concrete-need
supersedes: []
superseded-by: null
retrospective: false
edition: condensed-public
slug: /decisions/0017-adopt-multus-for-longhorn-storage-network
---

# 0017 — Adopt Multus for the Longhorn storage network

> Add Multus, chained with Cilium, so Longhorn can use the dedicated storage mesh.

_Public edition condensed on 2026-10-21; original decision date and meaning retained._

## Context

[ADR 0009](0009-10g-sfp-full-mesh-networking.md) built a dedicated SFP+ mesh for storage replication. Longhorn needs a second pod interface to use it.

## Decision

Adopt Multus in thick-plugin mode as a meta-CNI chained with Cilium. Longhorn attaches replica traffic to the mesh through a NetworkAttachmentDefinition. Longhorn is the only planned consumer; any other consumer needs its own intake.

This decision selects the mechanism. The NetworkAttachmentDefinition and Longhorn's storage-network wiring were left to execution work, and the decision itself does not show that replica traffic uses the mesh.

## Alternatives considered

- **Do nothing:** replication stays on the slower management network.
- **Replace the primary CNI:** a much larger blast radius than adding Multus to a healthy Cilium.
- **Thin-plugin Multus:** rejected in favor of the upstream-recommended thick-plugin DaemonSet.

## Consequences

Multus adds a cluster networking component and depends on the reference CNI plugins being present on every node. Validate secondary-interface addressing and pod-to-pod connectivity before sending storage traffic over it. Revisit if the mesh or the CNI architecture changes.
