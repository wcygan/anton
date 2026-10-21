---
status: Accepted
date: 2026-04-15
deciders: ['@wcygan']
affects: networking
intent: concrete-need
supersedes: []
superseded-by: null
retrospective: false
edition: condensed-public
slug: /decisions/0009-10g-sfp-full-mesh-networking
---

# 0009 — 10 Gbit SFP+ full-mesh storage networking

> Connect the three nodes in a direct 10 Gbit SFP+ full mesh dedicated to storage replication.

_Public edition condensed on 2026-10-21; original decision date and meaning retained._

## Context

The existing 2.5 Gbit links were expected to bottleneck replicated block rebuilds and monitoring storage writes.

## Decision

Build a direct 10 Gbit full mesh between the three nodes as a dedicated storage-replication network:

- one point-to-point link between each pair of nodes;
- static addresses on a dedicated subnet;
- no default route.

Management and ordinary cluster traffic stay on the existing network. The storage CSI is meant to use the mesh through Multus and a network attachment definition; that wiring was follow-up work, not part of the cabling decision.

## Alternatives considered

- **Managed switch:** adds cost, power, and a failure point.
- **Daisy chain:** makes paths asymmetric and turns one node into a transit point.
- **Bond unlike link speeds:** complicates behavior.

The direct mesh uses interfaces the nodes already have.

## Consequences

The mesh adds Talos network configuration and operational complexity. Jumbo MTU and interface selection must be consistent along every path. Verify link health and real throughput before relying on the expected gain. [ADR 0017](0017-adopt-multus-for-longhorn-storage-network.md) records the Multus attachment decision.
