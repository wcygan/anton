---
status: Deferred
date: 2026-04-11
deciders: ['@wcygan']
affects: observability
intent: unknown
supersedes: []
superseded-by: null
retrospective: false
edition: condensed-public
slug: /decisions/0003-defer-monitoring-stack-pending-storage
---

# 0003 — Defer monitoring stack pending object storage

> Do not install a monitoring stack yet; revisit once object storage exists for another reason.

_Public edition condensed on 2026-10-21; original decision date and meaning retained._

:::note Deferred
This decision postponed a choice. It does not approve installing anything.
:::

## Context

An earlier observability stack had been installed before there was anything to observe, and it used substantial memory without a concrete use. At decision time there was no named operational failure and no timeboxed learning intake, so intent was explicitly unknown. The aspiration was a Grafana-fronted stack for metrics, logs, and traces, with a weekly cluster-health view.

## Decision

Do not install monitoring yet. Keep three architectures open: kube-prometheus-stack, VictoriaMetrics, and Grafana LGTM.

Revisit when object storage is installed for an independent reason, since that lowers the cost of LGTM. The trigger starts a re-evaluation of the actual cluster and need; it does not authorize installing any candidate.

## Alternatives considered

- **Choose a stack now:** would lock in a choice before there were workloads worth observing.

Kube-prometheus-stack and VictoriaMetrics could run without object storage; the preferred LGTM shape needed it for production-grade storage. Live metrics and ad-hoc logs were enough until real workloads arrived.

## Consequences

Deferral saved resources and kept upgrades simple, but left no alerts, historical metrics, traces, or dashboards. The original candidate comparisons and resource estimates were time-sensitive; recheck them before use.
