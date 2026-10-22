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
edition: condensed-public
slug: /decisions/0002-defer-rook-ceph
---

# 0002 — Defer Rook-Ceph

> Defer Rook-Ceph because it does not fit the current three-node consumer hardware.

_Public edition condensed on 2026-10-21; original decision date and meaning retained._

:::note Deferred
This decision postponed a choice. It does not approve installing anything.
:::

## Context

Of the components removed in the reset, Rook-Ceph was the one judged a poor fit for the hardware and operations, rather than a casualty of missing governance. The decision applies to the three-node consumer-hardware cluster of the time.

## Decision

Defer Rook-Ceph for the current cluster shape. At this scale, Ceph's OSDs, monitors, managers, and recovery machinery are not justified, and degraded recovery or quorum problems could make failures harder to resolve. Anton's availability strategy belongs at the cluster layer: Talos quorum, Flux, and restorable configuration.

This does not reject other storage candidates or commit permanently to local-path storage; evaluate those separately. [ADR 0004](0004-storage-stack-framework.md) records the later storage framework.

## Alternatives considered

- **Re-admit Ceph through ordinary intake:** would hide the hardware-fit concern.
- **Reject Ceph outright:** would claim more than this cluster can show.

## Consequences

The local-storage baseline has no storage-level replication, so tested external backups stay essential. Workloads that need synchronous replicated storage do not fit until another suitable system is adopted.

### Revisit when

- the cluster grows to at least five suitably matched storage nodes with adequate networking,
- the hardware improves materially,
- a running workload shows a sustained need, or
- a declared, contained learning intake sets out to study Ceph on this hardware.

The decision did not claim any of these was met.
