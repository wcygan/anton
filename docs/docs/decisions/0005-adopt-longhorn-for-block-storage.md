---
status: Accepted
date: 2026-04-11
deciders: ['@wcygan']
affects: storage
intent: concrete-need
supersedes: []
superseded-by: null
retrospective: false
edition: condensed-public
slug: /decisions/0005-adopt-longhorn-for-block-storage
---

# 0005 — Adopt Longhorn for replicated block storage

> Adopt Longhorn as the replicated block storage CSI, defaulting to two replicas.

_Public edition condensed on 2026-10-21; original decision date and meaning retained._

## Context

[ADR 0004](0004-storage-stack-framework.md) called for a replicated block storage system chosen on its own merits.

## Decision

Select Longhorn as Anton's replicated block CSI. Default to two replicas with best-effort data locality.

Installation was accepted but deferred until a real consumer was chosen. It requires Talos system extensions for iSCSI and utility tools, dedicated data disks, and a controlled node-by-node rollout. Pin and verify the chart version at implementation time, and test upgrades in isolation before promoting them.

## Alternatives considered

- **Three replicas:** the 1 Gbit network of the time would be heavily loaded during rebuilds, for little extra tolerance of single-node loss.
- **One replica by default:** would push durability choices onto every application.
- **Mayastor:** its network and kernel requirements did not fit the hardware.
- **Piraeus/Linstor:** the runner-up, with a less direct Talos path.
- **Local-only volumes:** do not meet the framework's replication requirement.

## Consequences

Once installed, Longhorn becomes a critical dependency for every PVC workload. Its operational surface, history of upgrade regressions, bandwidth-limited rebuilds, and lack of file/RWX by default were accepted costs.

Replication protects against node loss, not application corruption, accidental deletion, or ransomware. A tested backup and restore plan is still outstanding before irreplaceable data is stored.

Reconsider if upgrades fail repeatedly, the hardware or network changes materially, or the Ceph deferral is revisited.
