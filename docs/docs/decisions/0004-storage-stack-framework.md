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
slug: /decisions/0004-storage-stack-framework
---

# 0004 — Storage stack framework

> Choose storage per capability—block, object, and file—keeping it in-cluster and preferring the best tool for each.

_Public edition condensed on 2026-10-21; original decision date and meaning retained._

## Context

With Rook-Ceph deferred ([ADR 0002](0002-defer-rook-ceph.md)), Anton needed a way to choose storage. Workloads can need three distinct capabilities: replicated block volumes, in-cluster object storage, and shared file (RWX) storage.

## Decision

Evaluate storage by workload capability, treating replicated block, object, and file/RWX as separate needs. Prefer a best-of-breed system for each over one platform that spans all three, and keep storage in-cluster.

- Do not adopt Rook-Ceph under current constraints, consistent with [ADR 0002](0002-defer-rook-ceph.md).
- Defer file/RWX until a workload requires it.
- Choose each candidate in a later decision, once a consumer is named.

This framework does not install storage or choose every backend. The original candidate shortlists were research snapshots; verify upstream health and fit before acting on them.

## Alternatives considered

- **One broad platform:** would force every category choice before its workload existed.
- **External S3 or a LAN storage host:** less to operate, but breaks the self-hosted, in-cluster constraint.
- **Defer all research:** would discard useful evaluation already done.

## Consequences

The framework keeps options open and isolates failure domains, at the cost of more charts, namespaces, and upgrade streams. Replicated block storage over the network of the time was expected to slow rebuilds.

Replication does not protect against deletion, corruption, or cluster loss. A backup and restore plan is still required before irreplaceable data lives on the cluster. Recheck candidate status when selecting.
