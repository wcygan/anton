---
status: Accepted
date: 2026-04-12
deciders: ['@wcygan']
affects: observability
intent: concrete-need
supersedes: []
superseded-by: null
retrospective: false
edition: condensed-public
slug: /decisions/0007-adopt-kube-prometheus-stack
---

# 0007 — Adopt kube-prometheus-stack for metrics

> Adopt kube-prometheus-stack for metrics only, sized for a small cluster.

_Public edition condensed on 2026-10-21; original decision date and meaning retained._

## Context

The cluster needed a health view and historical metrics; live-only metrics could not support diagnosis after the fact. [ADR 0003](0003-defer-monitoring-stack-pending-storage.md) had tied the monitoring decision to object storage arriving.

## Decision

Adopt kube-prometheus-stack for metrics only, using ServiceMonitor and PodMonitor discovery.

- Run Prometheus, Alertmanager, and Grafana as single replicas.
- Persist state on Longhorn.
- Expose Grafana internally only, and manage dashboards in Git.
- Leave alert routes disabled until a real destination exists.

This decouples metrics from the SeaweedFS trigger in [ADR 0006](0006-adopt-seaweedfs-for-object-storage.md): storage should not drive observability scope.

## Alternatives considered

- **VictoriaMetrics:** lighter, but needs a parallel scrape-resource model or translation.
- **Grafana LGTM:** adds logs and traces with no demonstrated need.
- **Live metrics only:** cannot answer historical questions.

## Consequences

The chart costs more memory and surface area than a minimal metrics store, and 15-day retention limits historical queries. Alertmanager without routes sends no notifications. Review major chart upgrades.

Logs and traces stay deferred behind operational triggers, later described in [ADR 0008](0008-opentelemetry-logs-and-traces-roadmap.md). Revisit:

- retention, when older data is needed;
- logging, when ad-hoc queries fail to answer a real question;
- tracing, when an OTLP workload and a diagnostic need coincide;
- alert routing, when a destination is chosen.

Re-verify versions and resource assumptions before implementing.
