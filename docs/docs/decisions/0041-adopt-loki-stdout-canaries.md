---
status: Superseded-by 0042
date: 2026-10-19
deciders: ['@wcygan']
affects: observability
intent: concrete-need
supersedes: []
superseded-by: 0042
retrospective: false
slug: /decisions/0041-adopt-loki-stdout-canaries
---

# 0041 — Adopt Loki stdout canaries

> Use the Loki chart's per-node stdout canaries to detect missing log records within five minutes through the real collector pipeline.

_Public edition prepared on 2026-10-21 from the original record; decision date and meaning retained._

:::caution Superseded
Replaced by [ADR 0042](0042-bound-numbered-log-confirmation-deadlines.md). Read it before applying this decision.
:::

## Context

Collector restart tests lost records while every workload looked healthy. Persistent checkpoints and export queues repaired those windows, but readiness and error counters do not prove, continuously, that logs arrive. The operator asked for numbered-log detection within five minutes, verified through restart tests and real ntfy delivery.

## Decision

Enable the Loki 3.7.8 canary already shipped in Anton's pinned chart:

- stdout mode, one probe per node, read by the existing OTel collectors;
- match each record's numeric ID against the expected IDs;
- query with the indexed namespace and container labels plus a pod metadata filter, never adding pod names or record IDs to the index.

Page through the existing critical ntfy route for missing records, stalled emission or delivery, and missing node coverage. A two-minute missing deadline leaves room for evaluation and delivery inside five minutes. The canary lives inside the existing Loki app; no new chart or platform is added.

## Alternatives considered

- **Do nothing:** readiness and successful exports had already missed loss windows.
- **A direct-push canary:** bypasses the collector path whose durability matters.
- **A custom emitter and checker:** duplicates upstream matching, retries, and metrics.

## Consequences

Three small stateless probes (10m CPU and 32Mi requested each) emit one 100-byte record every ten seconds. IDs are timestamps, not a contiguous sequence; probes verify only their own records, and a canary restart loses in-flight comparisons. A detection can mean delayed delivery rather than permanent loss.

Rehearsal then showed the upstream counters could not give a bounded, false-positive-free signal, so [ADR 0042](0042-bound-numbered-log-confirmation-deadlines.md) replaced this approach.
