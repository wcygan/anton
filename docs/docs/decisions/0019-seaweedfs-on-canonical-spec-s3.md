---
status: Superseded-by 0043
date: 2026-04-19
deciders: ['@wcygan']
affects: storage
intent: concrete-need
supersedes: [0016]
superseded-by: 0043
retrospective: false
edition: condensed-public
slug: /decisions/0019-seaweedfs-on-canonical-spec-s3
---

# 0019 — SeaweedFS with the canonical `spec.s3` interface

> Run SeaweedFS with the canonical top-level `spec.s3` interface and a separate S3 deployment.

_Public edition condensed on 2026-10-21; original decision date and meaning retained._

:::caution Superseded
[ADR 0043](0043-keep-two-seaweedfs-copies-for-maintenance.md) replaced the `000` replication choice with two-copy placement. The standalone S3 interface, filers, and Longhorn-backed volumes remain.
:::

## Context

A new SeaweedFS operator release added the canonical standalone S3 field. Installing the deprecated embedded field from [ADR 0016](0016-adopt-seaweedfs-today-via-filerspec-s3.md) and then planning a migration would add work for no benefit.

## Decision

Use top-level `spec.s3` with a separate S3 deployment, and keep the filer. The selected shape:

| Component | Setting |
| --- | --- |
| S3 | 2 replicas |
| Filer | 2 replicas |
| Master | 3 replicas |
| Volume servers | Longhorn-backed |
| SeaweedFS replication | `000` |
| Exposure | Internal only |
| First consumer | Harbor |

Version numbers and values in the original are historical; verify chart support and the repository before implementing.

## Alternatives considered

- **Keep the embedded `FilerSpec.S3` path:** a deprecated field and a guaranteed migration.

## Consequences

This was the cluster's first use of the standalone S3 path, so it needed scratch validation before production. Filer HA with embedded LevelDB was still unresolved; the interface change did not settle it.

SeaweedFS is a critical dependency for its S3 consumers, and Longhorn replication is not a backup. The pending validation and backup work remain open.
