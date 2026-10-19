---
status: Accepted
date: 2026-10-19
deciders: ['@wcygan']
affects: observability
intent: concrete-need
supersedes: ['0041']
superseded-by: null
retrospective: false
---

# 0042 — Bound numbered log confirmation deadlines

> Poll Loki for exact numbered stdout records and expose independent deadline metrics so missing canary records can page within five minutes.

## Status

Accepted

## Context

Rehearsal of ADR 0041 recovered all delivered records across overlapping restarts,
but upstream Loki canary's tail-missing counter can increase even when HTTP queries
find the record. Its confirmed-missing counter waits on queries whose error backoff
can exceed five minutes. Neither establishes the requested bounded HTTP visibility
signal without a false-positive tail interpretation. See the pinned
[reader](https://github.com/grafana/loki/blob/v3.7.8/pkg/canary/reader/reader.go) and
[comparator](https://github.com/grafana/loki/blob/v3.7.8/pkg/canary/comparator/comparator.go).

## Decision

Keep the upstream chart canary disabled. Add a small Python standard-library
emitter/checker inside the existing Loki Flux app. Emit a run ID plus contiguous
sequence every ten seconds on each node through stdout and the real OTel reader.
Poll Loki HTTP with a five-second timeout and ten-second pause. Match exact IDs,
accept duplicates/out-of-order delivery, and expose the oldest unconfirmed age
from an independent metrics server. Preserve existing index labels; pod identity
remains structured metadata and record IDs remain body fields.

Page at 180 seconds of missing confirmation, with 15-second evaluation/pending,
30-second scrape and 30-second initial Alertmanager grouping: 270 seconds worst
case when monitoring is healthy. Also page for stalled emission/query success
and missing DaemonSet-owned node coverage. The observability integration owns
these raw manifests alongside Loki; no new platform or chart is introduced.

## Alternatives considered

- **Upstream tail counter** — tail reconnects do not establish HTTP visibility loss.
- **Upstream HTTP counter** — query backoff can exceed the requested deadline.
- **Readiness/error alerts alone** — failed to detect prior silent record loss.

## Consequences

### Accepted costs

- Three stateless probes, each requesting 10m CPU/32Mi and limited to 100m/64Mi;
  about 26,000 small records and queries per day across three nodes.
- A bounded 512-record in-memory ledger per probe. Overflow latches the oldest
  failure until restart rather than hiding it. Probe restarts lose comparisons;
  preserve probe pods during collector/Loki tests. This verifies probe records,
  not every application record or long-term stored-data integrity.
- Visibility failures may be delay or query outage, not permanent loss. The
  five-minute budget depends on healthy Prometheus, Alertmanager and ntfy.
- The pinned Python runtime adds a Renovate image-review obligation. No PVC,
  secret, public endpoint or CRD is added. Revert the manifests/rules to remove it.

## Follow-ups

- Observe the first 24 hours for noise and query/resource cost before broader drills.
