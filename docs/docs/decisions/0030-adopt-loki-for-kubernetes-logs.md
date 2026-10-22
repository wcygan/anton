---
status: Superseded-by 0032
date: 2026-08-02
deciders: ['@wcygan']
affects: observability
intent: concrete-need
supersedes: [0008]
superseded-by: 0032
retrospective: false
edition: condensed-public
slug: /decisions/0030-adopt-loki-for-kubernetes-logs
---

# 0030 — Adopt Loki for Kubernetes logs

> Adopt single-binary Loki, fed by an OpenTelemetry Collector DaemonSet, as the durable store for Kubernetes pod logs.

_Public edition condensed on 2026-10-21; original decision date and meaning retained._

:::caution Superseded
Replaced by [ADR 0032](0032-honor-loki-stream-retention-minimum.md). Read it before applying this decision.
:::

## Context

[ADR 0008](0008-opentelemetry-logs-and-traces-roadmap.md) deferred a log backend behind an operational trigger, and the [ClickStack experiment](0028-clickstack-learning-experiment.md) reached its review.

## Decision

Use single-binary Loki as the durable backend for Kubernetes pod logs. An OpenTelemetry Collector DaemonSet reads pod log files, adds Kubernetes metadata, and sends OTLP/HTTP logs to Loki. Grafana queries Loki as an internal data source. Metrics stay on Prometheus; no trace backend or public log route is added.

### Deployment

- Pinned Loki chart and image, monolithic mode, TSDB schema v13.
- A bounded Longhorn volume, with SeaweedFS S3 for chunks and ruler data.
- During migration, the collector starts at the end of existing files and keeps checkpoints on bounded node-local storage.
- Indexed labels are limited to namespace, container, workload kind, and normalized severity. Pod, node, request, trace, user, and network identifiers stay in structured metadata or log content.

### Retention

| Severity | Retention |
| --- | --- |
| fatal, error | 30 days |
| warning | 14 days |
| info, unknown | 24 hours |
| debug, trace | 6 hours initially |

Loki retention is enabled. The implementation temporarily reuses an existing storage identity; a bucket-scoped identity is preferred later. Log content stays internal and may contain sensitive application data.

## Alternatives considered

- **ClickStack as the durable platform:** the experiment ended without being selected.

## Consequences

Loki fits the existing Grafana and object storage without adding databases or gateways. Both the PVC and SeaweedFS capacity need monitoring; retention policy is not a bucket quota.

[ADR 0032](0032-honor-loki-stream-retention-minimum.md) raised debug and trace retention to Loki's supported minimum of 24 hours. It supersedes only that setting; the rest of this design stands.
