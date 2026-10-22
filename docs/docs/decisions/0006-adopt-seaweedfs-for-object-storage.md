---
status: Superseded-by 0016
date: 2026-04-11
deciders: ['@wcygan']
affects: storage
intent: concrete-need
supersedes: []
superseded-by: 0016
retrospective: false
edition: condensed-public
slug: /decisions/0006-adopt-seaweedfs-for-object-storage
---

# 0006 — Adopt SeaweedFS for object storage

> Select SeaweedFS as Anton's in-cluster object storage.

_Public edition condensed on 2026-10-21; original decision date and meaning retained._

:::caution Superseded
Replaced by [ADR 0016](0016-adopt-seaweedfs-today-via-filerspec-s3.md). Read it before applying this decision.
:::

## Context

[ADR 0004](0004-storage-stack-framework.md) called for in-cluster object storage, chosen separately from block storage ([ADR 0005](0005-adopt-longhorn-for-block-storage.md)).

## Decision

Select SeaweedFS for object storage, initially in a gateway-oriented shape with no filer or RWX requirement. The original release gate and implementation details are historical.

[ADR 0016](0016-adopt-seaweedfs-today-via-filerspec-s3.md) superseded this decision, and [ADR 0019](0019-seaweedfs-on-canonical-spec-s3.md) later superseded that one with the canonical S3 interface now in use.

## Alternatives considered

- **Garage** and **MinIO:** research at the time favored SeaweedFS, while recognizing its operator was pre-1.0 and its releases were still evolving.
- **Ceph or an external provider:** excluded by earlier decisions.

A standalone S3 shape kept a future backend swap manageable.

## Consequences

Consumers come to depend on an in-cluster object service. Durability settings and Longhorn backing do not replace backups. Operator health, storage behavior, and consumer integration needed verification before production use. Filer high availability and backup coverage remained open; later decisions carry that work forward.
