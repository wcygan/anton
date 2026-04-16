# kube-prometheus-stack baseline — 2026-04-16

Acceptance artifact for [plan 0002 — Install kube-prometheus-stack](../../../context/plans/0002-install-kube-prometheus-stack.md) and [ADR 0007 — Adopt kube-prometheus-stack](../../../context/adrs/0007-adopt-kube-prometheus-stack.md). Documents the metrics-only stack at install time so future right-sizing, alert-rule work, or upgrade regressions have a reference line to compare against.

## Cluster shape at measurement time

- Chart `kube-prometheus-stack` **83.5.0** (HelmRepository fallback; OCI mirror stale at 41.7.4)
- Prometheus Operator `v0.90.1`, Prometheus `v3.7.3`, Alertmanager, Grafana `12.4.3`
- All workloads single-replica; state on Longhorn PVCs
- Namespace: `observability`
- Talos disables wired in: `kubeControllerManager`, `kubeScheduler`, `kubeProxy` off (Cilium replaces kube-proxy)
- Cluster-wide ServiceMonitor / PodMonitor discovery (all selectors nil)

## Pod placement and resource usage

Steady-state, ~50 min after install (from `kubectl top pod`):

| Pod | CPU | Memory | Node |
|---|---|---|---|
| prometheus-kube-prometheus-stack-prometheus-0 | 68m | 810Mi | k8s-1 |
| kube-prometheus-stack-grafana | 17m | 283Mi | k8s-1 |
| alertmanager-kube-prometheus-stack-alertmanager-0 | 5m | 33Mi | k8s-1 |
| kube-prometheus-stack-operator | 7m | 24Mi | k8s-1 |
| kube-prometheus-stack-kube-state-metrics | 5m | 22Mi | k8s-1 |
| node-exporter (×3, one per node) | 1–9m | 10–12Mi | k8s-1/2/3 |

**Prometheus TSDB head series: 199,326** — well inside the 50 GiB / 15 d retention envelope. Node-exporter is the only DaemonSet; everything else currently schedules on k8s-1 (no anti-affinity yet — fine for single-replica shape).

## Storage

| PVC | Size | StorageClass | Volume mode |
|---|---|---|---|
| prometheus-…-prometheus-0 | 50Gi | longhorn | Filesystem |
| alertmanager-…-alertmanager-0 | 2Gi | longhorn | Filesystem |
| kube-prometheus-stack-grafana | 5Gi | longhorn | Filesystem |

All three bound on Longhorn with 2-replica default and `best-effort` locality (per ADR 0005 defaults).

## Scrape coverage

Jobs reporting to Prometheus after the Cilium / Longhorn / Flux wiring commits:

- `apiserver`, `kubelet`, `coredns`, `node-exporter`, `kube-state-metrics`
- `cilium-agent`, `cilium-operator`
- `longhorn-backend`
- `flux-system/flux-controllers` (PodMonitor — 4 targets: source, kustomize, helm, notification controllers)
- `flux-operator` (ServiceMonitor)
- `cert-manager`, `cainjector`, `webhook`
- `external-secrets-*` (metrics, webhook, cert-controller)
- `cloudflare-dns`, `cloudflare-tunnel`
- `metrics-server`, `kube-system/reloader`
- `kube-prometheus-stack-{operator,prometheus,alertmanager,grafana}`

23 discovered jobs total. `kubeControllerManager`, `kubeScheduler`, `kubeProxy` intentionally absent — Talos does not expose these, and Cilium replaces kube-proxy.

## Exposure

- Grafana at `grafana.<cluster-domain>` via `envoy-internal` (split-horizon DNS, internal-only, cert issued by cluster CA)
- Prometheus and Alertmanager **not** exposed via HTTPRoute — accessed only via `kubectl port-forward` or cluster-internal service DNS
- Grafana admin creds sourced via ExternalSecret from 1Password vault `anton`, item `grafana-admin`

## Cluster-health-glance dashboard

Seven-panel starter dashboard (uid `cluster-health-glance`) checked in as a ConfigMap alongside the HelmRelease, picked up by the Grafana sidecar (label `grafana_dashboard: "1"`, `searchNamespace: ALL`). Panels: Node CPU %, Node Memory %, Node Filesystem %, Top Pod Restarts (24h), Flux Reconcile State, PVC Saturation %, Longhorn Volume Health.

**Flux panel fix worth remembering**: `gotk_reconcile_condition` is *not* exported by the Flux controllers in the currently installed version — only `gotk_reconcile_duration_*`, `gotk_cache_events_total`, `gotk_event_http_*`, `gotk_token_*`. The cross-resource ready/not-ready/suspended counts instead come from **flux-operator**'s `flux_resource_info{ready=…, suspended=…}` with a per-resource `kind` label. The dashboard was corrected to use that metric.

## What this means for ADR 0007 follow-ups

- Retention (15 d / 50 GiB) is oversized for current cardinality — TSDB head at ~200k series suggests we could halve PVC and still have runway. Defer right-sizing until we add loki + tempo (Phase 2 per ADR 0007) or a month of growth, whichever first.
- Grafana footprint (283Mi / 17m) is steady with the single dashboard; every added dashboard is effectively free until the sidecar reload cost becomes visible.
- No alerts defined yet. Next concrete step is the PrometheusRule for node / Longhorn / Flux saturation — cheapest lift, highest signal.

## Pointers

- Plan: `context/plans/0002-install-kube-prometheus-stack.md`
- ADRs: 0007 (kps install), 0005 (Longhorn defaults — gate cleared by baseline 2026-04-16)
- HelmRelease: `kubernetes/apps/observability/kube-prometheus-stack/app/helmrelease.yaml`
- Dashboard: `kubernetes/apps/observability/kube-prometheus-stack/app/dashboard-cluster-health.yaml`
- Flux PodMonitor: `kubernetes/apps/flux-system/flux-instance/app/podmonitor.yaml`
