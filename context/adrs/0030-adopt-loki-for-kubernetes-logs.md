---
status: Accepted
date: 2026-08-02
deciders: ['@wcygan']
affects: observability
intent: concrete-need
supersedes: [0008]
superseded-by: null
retrospective: false
---

# 0030 — Adopt Loki for Kubernetes pod logs

## Decision

Anton will use a small, single-binary Loki deployment as the durable backend
for Kubernetes pod logs. An OpenTelemetry Collector DaemonSet reads each
node's `/var/log/pods` files and sends OTLP/HTTP logs to Loki. The existing
kube-prometheus-stack Grafana is provisioned with Loki as an internal data
source. This decision supersedes the deferred Loki/VictoriaLogs roadmap in
ADR 0008.

The source of truth pins Grafana Loki chart `18.7.1` (Loki `3.7.4`) and the
OpenTelemetry Collector chart `0.165.0` (collector `0.156.0`). Loki runs in
monolithic mode with one replica, TSDB/v13 schema, a bounded 20 GiB Longhorn
PVC, and existing SeaweedFS S3 object storage. The collector starts at the
end of existing files during migration, stores checkpoints on a bounded
node-local hostPath, and enriches records with Kubernetes metadata.

## Contracts

- Indexed Loki labels are limited to namespace, container, workload-kind
  names (deployment/statefulset/daemonset/job/cronjob), and normalized
  severity. Pod UID, pod name, node, request/trace/user IDs, IPs, and similar
  high-cardinality fields remain structured metadata or log content.
- Severity is normalized to `fatal`, `error`, `warn`, `info`, `debug`, or
  `trace`; missing or unrecognized severity is treated as `info` by the
  collector.
- Retention targets are fatal/error 30 days, warn 14 days, info/unknown 24
  hours, and debug/trace 6 hours. Loki compactor retention is enabled.
- Loki writes chunks and ruler data to the existing SeaweedFS S3 service in
  bucket `loki`; a source-managed bucket check creates the bucket if needed.
  The current source-of-truth only exposes the existing SeaweedFS admin
  identity through ESO, so that identity is reused temporarily. A future
  storage-scoped identity should replace it without changing the data path.
- Grafana access is through the in-cluster service URL only. No public route,
  tailnet hostname, or manual Grafana state is part of this decision.

## Why Loki

Loki fits this homelab's operational shape: it has a supported OTLP ingestion
path, native LogQL in the existing Grafana, object-storage support, and a
monolithic mode that avoids additional databases, gateways, and replicas.
VictoriaLogs remains a reasonable future evaluation, but adopting it now
would add a different query and provisioning path. The ClickStack experiment
(ClickHouse, Keeper, MongoDB, HyperDX, and its homepage-only collector) was
useful as a time-boxed evaluation but is not the durable platform choice.

## Non-goals and consequences

This first cut does not add a gateway collector, a trace backend, a metrics
replacement, a public log route, per-tenant auth, or a large dashboard suite.
The separate temporary Talos log sink remains separate and is not replaced.
Retention is logical and bounded by policy plus the 20 GiB Loki PVC; SeaweedFS
does not currently have a bucket quota in this source of truth, so operators
must monitor both Loki and SeaweedFS capacity. Logs can contain sensitive
application data and must remain internal to the tailnet.

Rollout and ClickStack teardown are deliberately operator-only actions. See
`docs/docs/runbooks/kubernetes-logs-loki.md` for rollout order, queries,
failure diagnosis, and the approved teardown sequence.

ClickStack-specific Longhorn helper resources are no longer managed by the
source of truth. Any live ClickStack PVC cleanup remains an operator-only
teardown step.
