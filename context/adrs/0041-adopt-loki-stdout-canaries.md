---
status: Superseded-by 0042
date: 2026-10-19
deciders: ['@wcygan']
affects: observability
intent: concrete-need
supersedes: []
superseded-by: null
retrospective: false
---

# 0041 — Adopt Loki stdout canaries

> Use the existing Loki chart's per-node stdout canaries to detect missing log records within five minutes through the real OTel pipeline.

## Status

Accepted

## Context

Collector restart tests exposed lost records despite healthy workloads. Persistent
checkpoints and export queues repaired those windows, but readiness and error
counters do not continuously prove delivery. The operator requested numbered-log
detection within five minutes, overlapping restart tests and verified ntfy delivery.

## Decision

Enable the upstream Loki 3.7.8 canary already supplied by Anton's pinned chart,
using stdout mode, one probe per node and the existing OTel readers and Loki
ServiceMonitor. Match each record's numeric nanosecond ID against expected IDs.
Use indexed namespace/container labels plus a pod metadata filter; do not add
pod names or record IDs to Loki's index.

Page through the existing critical ntfy route for missing records, stalled
emission/delivery or missing node coverage. A two-minute missing deadline leaves
headroom for evaluation and delivery inside five minutes. Outages can block
confirmation queries, so stalled delivery is a separate signal. Test locally
before publication and with a bounded one-record live negative control afterward.
The observability integration owns these changes inside the existing Loki app;
no standalone chart or platform is added.

## Alternatives considered

- **Do nothing** — readiness and successful exports missed prior loss windows.
- **Direct-push canary** — bypasses the collector path whose durability matters.
- **Custom emitter/checker** — duplicates upstream matching, retries and metrics.

## Consequences

### Accepted costs

- Three stateless probes, each requesting 10m CPU/32Mi and limited to 100m/64Mi;
  one 100-byte record per ten seconds, about 2.6MB/day before overhead.
- IDs are timestamps rather than contiguous application sequence numbers. Probes
  verify their own records, not all application logs. Expected IDs live in memory;
  a canary restart loses in-flight comparisons. Coverage is not a durable ledger.
- A visibility failure can be delayed delivery rather than permanent loss.
  Preserving collector checkpoints and Loki WAL remains the repair default.
- Image updates track Loki's version/digest through existing dependency maintenance.
  No PVC, credential, CRD, public endpoint or backup service is added. Disable the
  canary and remove its rule resource to reverse the addition.

## Follow-ups

- Observe the first 24 hours for detection noise and resource/query cost before
  considering broader fault drills.
