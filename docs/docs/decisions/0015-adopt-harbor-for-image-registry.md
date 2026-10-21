---
status: Accepted
date: 2026-04-18
deciders: ['@wcygan']
affects: registries
intent: concrete-need
supersedes: []
superseded-by: null
retrospective: false
edition: condensed-public
slug: /decisions/0015-adopt-harbor-for-image-registry
---

# 0015 — Adopt Harbor as the in-cluster image registry

> Restore Harbor as the in-cluster OCI registry, for a real image workflow and for learning.

_Public edition condensed on 2026-10-21; original decision date and meaning retained._

## Context

Harbor had hosted personal application images before the reset. Removing it left that workflow without a registry.

## Decision

Restore Harbor as an in-cluster OCI registry, both for that consumer and for the declared learning value of running image distribution through GitOps.

- Store image blobs in SeaweedFS S3 ([ADR 0019](0019-seaweedfs-on-canonical-spec-s3.md)).
- Put database and cache volumes on Longhorn ([ADR 0005](0005-adopt-longhorn-for-block-storage.md)), managed by the CloudNativePG and Dragonfly operators.

The original shape included multiple Harbor replicas, authenticated pushes, anonymous pulls over the private LAN and tailnet, and Spegel mirror integration. Trivy scanning was disabled under the then-stated trusted-source threat model. The original also set a sequential dependency order; re-check the implementation details before use.

## Alternatives considered

- **Do nothing:** leaves a known workflow unmet.
- **Zot:** lighter.
- **A hosted registry:** less to operate.

Harbor was chosen knowingly for its learning value and continuity with the earlier workflow.

## Consequences

Harbor adds two operators and their upgrades, runs without vulnerability scanning, and creates a backup need for its metadata. Revisit if the learning value plateaus, the operating weight becomes excessive, or the threat model changes.
