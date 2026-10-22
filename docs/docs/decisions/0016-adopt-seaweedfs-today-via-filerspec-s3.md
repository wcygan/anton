---
status: Superseded-by 0019
date: 2026-04-18
deciders: ['@wcygan']
affects: storage
intent: concrete-need
supersedes: [0006]
superseded-by: 0019
retrospective: false
edition: condensed-public
slug: /decisions/0016-adopt-seaweedfs-today-via-filerspec-s3
---

# 0016 — Adopt SeaweedFS using embedded filer S3

> Proceed with SeaweedFS through the embedded `FilerSpec.S3` field rather than wait for standalone S3 support.

_Public edition condensed on 2026-10-21; original decision date and meaning retained._

:::caution Superseded
Replaced by [ADR 0019](0019-seaweedfs-on-canonical-spec-s3.md). Read it before applying this decision.
:::

## Context

[ADR 0006](0006-adopt-seaweedfs-for-object-storage.md) had waited for a SeaweedFS chart that exposed standalone S3 configuration. The release date looked uncertain, and Harbor needed an object backend.

## Decision

Proceed with the SeaweedFS chart then available, using the embedded `FilerSpec.S3` path. Keep SeaweedFS as the in-cluster object store on Longhorn volumes, with SeaweedFS replication disabled because Longhorn provides block durability. Harbor is the named consumer. Filer high availability remained an open test requirement.

## Alternatives considered

- **Keep waiting for standalone S3:** an indefinite delay with a consumer waiting.

## Consequences

The decision accepted a deprecated field and a future migration cost to avoid waiting. It was superseded by [ADR 0019](0019-seaweedfs-on-canonical-spec-s3.md) before installation, when the canonical `spec.s3` path shipped, so its chart and field choices are not deployment guidance. The filer HA question stayed open after the interface change.
