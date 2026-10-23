---
status: Accepted
date: 2026-10-19
deciders: ['@wcygan']
affects: observability
intent: concrete-need
supersedes: ['0041']
superseded-by: null
retrospective: false
slug: /decisions/0042-bound-numbered-log-confirmation-deadlines
---

# 0042 — Bound numbered log confirmation deadlines

> Poll Loki for exact numbered stdout records and expose independent deadline metrics, so a missing canary record pages within five minutes.

_Public edition prepared on 2026-10-21 from the original record; decision date and meaning retained._

## Context

Rehearsing [ADR 0041](0041-adopt-loki-stdout-canaries.md) recovered every delivered record across overlapping restarts, but exposed two problems with the upstream canary. Its tail-missing counter can rise even when an HTTP query finds the record. Its confirmed-missing counter waits on queries whose error backoff can exceed five minutes. Neither gives a bounded visibility signal without false positives.

## Decision

Keep the upstream chart canary disabled. Add a small Python standard-library emitter and checker inside the existing Loki Flux app:

- Every ten seconds on each node, emit a run ID and a contiguous sequence number to stdout, through the real OTel reader.
- Poll Loki over HTTP with a five-second timeout and a ten-second pause. Match exact IDs, and accept duplicates and out-of-order delivery.
- Expose the age of the oldest unconfirmed record from an independent metrics server.
- Keep the existing index labels. Pod identity stays in structured metadata and record IDs stay in the log body.

Page when a record is unconfirmed for 180 seconds. With 15-second evaluation, a 30-second scrape, and 30-second initial grouping, the worst case is 270 seconds while monitoring is healthy. Also page for stalled emission, failing queries, and missing node coverage.

## Alternatives considered

- **The upstream tail counter:** tail reconnects do not show loss of HTTP visibility.
- **The upstream HTTP counter:** its backoff can exceed the deadline.
- **Readiness and error alerts alone:** they missed earlier silent loss.

## Consequences

Three small stateless probes (10m CPU and 32Mi requested each) produce about 26,000 small records and queries a day across the three nodes. Each probe keeps a bounded 512-record ledger in memory; an overflow latches the oldest failure until restart rather than hiding it. A probe restart loses its comparisons, so keep probe pods running during collector or Loki tests.

The probes verify their own records, not every application log or long-term storage integrity. A detection can mean delay or a query outage, not necessarily loss, and the five-minute budget assumes Prometheus, Alertmanager, and ntfy are healthy. The pinned Python image adds an update to review. No volume, secret, public endpoint, or CRD is added; reverting the manifests and rules removes it.
