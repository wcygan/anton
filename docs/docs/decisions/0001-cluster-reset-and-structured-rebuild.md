---
status: Accepted
date: 2026-04-10
deciders: ['@wcygan']
affects: all
intent: concrete-need
supersedes: []
superseded-by: null
retrospective: true
edition: condensed-public
slug: /decisions/0001-cluster-reset-and-structured-rebuild
---

# 0001 — Cluster reset and structured rebuild

> Reset most workloads and rebuild Anton incrementally, with recorded decisions and an explicit intake gate.

_Public edition condensed on 2026-10-21; original decision date and meaning retained._

## Context

After a year of additions, Anton was maintaining components that had no concrete consumer. With no intake gate and no durable decision record, the same components were evaluated repeatedly and operating costs kept growing. The problem was governance, not defects in the software being removed.

## Decision

In April 2026, reset most workloads and rebuild incrementally. Record each decision, and pass every addition through an intake gate that classifies it as a concrete need, contained learning, or both.

Previously removed components may be reconsidered, except Rook-Ceph, which [ADR 0002](0002-defer-rook-ceph.md) defers specifically.

The original decision used agent skills and session hooks to make this governance discoverable. Those were its implementation at the time; current governance is harness-neutral and documented elsewhere.

## Alternatives considered

- **Do nothing:** components would keep accumulating.
- **Retrofit governance onto the existing cluster:** unexamined maintenance costs would remain.
- **Remove only selected components:** the same, for whatever stayed.

## Consequences

The reset temporarily reduced capability and required tooling work. Learning remains welcome when it has a timebox, a disposable-data agreement, and an exit plan. Re-adopting a component requires a fresh evaluation; prior installation is not a reason.
