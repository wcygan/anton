---
status: Superseded-by 0030
date: 2026-04-12
deciders: ['@wcygan']
affects: observability
intent: concrete-need
supersedes: []
superseded-by: 0030
retrospective: false
edition: condensed-public
slug: /decisions/0008-opentelemetry-logs-and-traces-roadmap
---

# 0008 — OpenTelemetry logs and traces roadmap

> Plan on the OpenTelemetry Collector as the shared foundation for logs and traces, without installing anything yet.

_Public edition condensed on 2026-10-21; original decision date and meaning retained._

:::caution Superseded
Replaced by [ADR 0030](0030-adopt-loki-for-kubernetes-logs.md). Read it before applying this decision.
:::

## Context

[ADR 0007](0007-adopt-kube-prometheus-stack.md) chose metrics first and deferred logs and traces until they could answer real operational questions.

## Decision

Use the OpenTelemetry Collector, deployed through its operator, as the intended vendor-neutral collector for both logs and traces. This roadmap does not authorize installation.

- **Logs:** consider when cross-pod or cross-namespace queries over a meaningful window fail to answer a real question.
- **Traces:** require both a workload that emits OTLP and a question that metrics and logs cannot answer.

The backend shortlist—VictoriaLogs or Loki for logs, Jaeger or Tempo for traces—was a research snapshot. Re-verify upstream health, storage modes, and fit at intake.

## Alternatives considered

- **Leave the collector undecided:** invites repeated architecture debates each time a signal is needed.

## Consequences

Choosing the collector early kept backend choice open, at the cost of a time-sensitive dependency on the operator's CRDs and release health. Do not install a collector without a consumer. Revisit the choice if the project stalls or its Kubernetes integration changes materially.

[ADR 0030](0030-adopt-loki-for-kubernetes-logs.md) superseded this roadmap for logs; read any remaining direction in that light. A trace backend remains deferred until its trigger fires.
