---
status: Accepted
date: 2026-06-03
deciders: ['@wcygan']
affects: observability
intent: learning
supersedes: []
superseded-by: null
retrospective: false
review-by: 2026-08-02
edition: condensed-public
slug: /decisions/0028-clickstack-learning-experiment
---

# 0028 — Run ClickStack as a time-boxed observability experiment

> Run ClickStack for 60 days as a contained experiment in logs and traces; Prometheus stays the only metrics store.

_Public edition condensed on 2026-10-21; original decision date and meaning retained._

## Context

[ADR 0007](0007-adopt-kube-prometheus-stack.md) keeps metrics on Prometheus, and [ADR 0008](0008-opentelemetry-logs-and-traces-roadmap.md) deferred a shortlist of log and trace backends. ClickStack combines ClickHouse, OpenTelemetry, and HyperDX, and challenged earlier concerns about resource cost and a separate interface. The question was worth exploring as contained learning, not as a production need.

## Decision

Run ClickStack in its own namespace as a 60-day experiment, reviewed by 2026-08-02.

- Evaluate logs and traces only. Prometheus stays the sole metrics and alerting store, and no Prometheus metrics are bridged into ClickHouse.
- Use deliberately chosen test logs and traces, credentials from External Secrets, bounded resources, and an internal-only HyperDX route.
- Nothing else may depend on the experiment.

The review must answer three questions:

1. Does ClickHouse improve broad log queries?
2. Are its operating and resource costs acceptable?
3. Does HyperDX justify a second observability front door?

Then either write a successor decision that re-ranks ADR 0008's backends, or execute the exit plan. The deployment is disposable, and teardown must remove its cluster-scoped operators and CRDs.

## Alternatives considered

- **Wait for ADR 0008's triggers:** produces no hands-on evidence.
- **Adopt ClickStack for production:** adds a second metrics store with no concrete need.

## Consequences

The experiment adds several operators, charts, upgrades, and two UIs. The fixed review date and isolation are essential; letting the timebox lapse silently would turn learning into unreviewed platform debt. This experiment does not supersede ADR 0007 or 0008.
