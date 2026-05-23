# Flux Metrics on anton

Flux's observability has two distinct surfaces — the **controllers** (source / kustomize / helm / notification), and the **flux-operator** that manages them. They expose different metrics. Queries on anton must use the right one.

## Canonical URLs

- **Flux monitoring index**: https://fluxcd.io/flux/monitoring/
- **Flux controller metrics**: https://fluxcd.io/flux/monitoring/metrics/
- **Flux custom metrics (kube-state-metrics pattern)**: https://fluxcd.io/flux/monitoring/custom-metrics/
- **flux-operator monitoring**: https://fluxcd.control-plane.io/operator/monitoring/
- **FluxReport CRD (what the operator computes)**: https://fluxcd.control-plane.io/operator/fluxreport/

## What the controllers expose

Scraped via the `flux-controllers` PodMonitor (`kubernetes/apps/flux-system/flux-instance/app/podmonitor.yaml`), job label **`flux-system/flux-controllers`**:

| Metric family | Purpose |
| --- | --- |
| `gotk_reconcile_duration_seconds_{bucket,sum,count}` | Histogram of reconcile latency. **Use this for "how busy is Flux"**. |
| `gotk_cache_events_total` | Informer cache event counters. |
| `gotk_event_http_request_*` | The notification-controller's event webhook traffic. |
| `gotk_token_cache_*` | GitRepository / OCIRepository token cache. |
| `controller_runtime_reconcile_*` | controller-runtime standard counters (errors, panics, timeouts). |
| `go_*`, `process_*` | Standard Go / process metrics. |

**What they do NOT expose** on this chart line: `gotk_reconcile_condition`. Historical docs reference it, but it is not emitted by the controllers anton is running. A query like `gotk_reconcile_condition{type="Ready"}` returns an empty vector. Use flux-operator's `flux_resource_info` instead (next section).

## What flux-operator exposes

Scraped via the flux-operator ServiceMonitor, job label **`flux-operator`**:

| Metric | Labels | Purpose |
| --- | --- | --- |
| `flux_resource_info` | `kind`, `name`, `exported_namespace`, `ready`, `suspended`, `reason`, `revision`, `source_name`, `uid` | **One series per Flux resource** with `ready="True"/"False"` and `suspended="True"/"False"` labels. This is how you roll up "how many Kustomizations are Ready". |
| `flux_instance_info` | `name`, `version`, `distribution` | Single series describing the FluxInstance. |
| `flux_operator_info` | — | Operator version metadata. |
| `flux_token_cache_*` | — | Token cache for the operator itself. |

`flux_resource_info` is the **primary integration metric** for rollups and alerts on anton. The `kind` label covers `HelmRelease`, `Kustomization`, `OCIRepository`, `HelmRepository`, `HelmChart`, `GitRepository`, `Receiver`.

## Query recipes

```promql
# "How many Flux resources of each kind are Ready?"
count(flux_resource_info{ready="True"}) by (kind)

# "Which Flux resources are NOT Ready right now?"
flux_resource_info{ready="False"}
# returns one series per failing resource, with labels that identify it

# "Which resources are suspended (paused, not drifting)?"
count(flux_resource_info{suspended="True"}) by (kind) or vector(0)

# "What's the reconcile p99 latency, per kind and result?"
histogram_quantile(0.99,
  sum by(le, kind, result) (
    rate(gotk_reconcile_duration_seconds_bucket[5m])
  )
)

# "Is any controller panicking?" — alert-worthy
increase(controller_runtime_reconcile_panics_total{job="flux-system/flux-controllers"}[10m]) > 0
```

## PodMonitor vs ServiceMonitor — why anton has both

- **Controllers** → PodMonitor. The FluxInstance chart's Services expose port 80 (HTTP API) only, not the `http-prom` metrics port. A ServiceMonitor against those Services would scrape nothing. The PodMonitor targets pods by label `app.kubernetes.io/part-of: flux` and uses the container port name `http-prom` directly.
- **flux-operator** → ServiceMonitor. The flux-operator chart does ship a metrics Service on port 8080, so SM works. It's also enabled by default in the operator's Helm values, so there is nothing to author — it Just Works.

You can confirm both:

```sh
kubectl -n observability exec prometheus-kube-prometheus-stack-prometheus-0 -c prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/label/job/values' | mise exec -- jq
# Expect to see both "flux-operator" and "flux-system/flux-controllers"
```

## When to reach for kube-state-metrics instead

kube-state-metrics does **not** know about Flux CRDs natively. The legacy pattern (pre-flux-operator) was to configure kube-state-metrics's `customResourceState` to emit `gotk_resource_info` for Flux CRDs. **Don't do this on anton** — flux-operator's `flux_resource_info` supersedes it and requires zero config.

## Related: Alerting on Flux

When ADR 0007 Trigger 4 fires and we start authoring Alertmanager routes, the first alert should be:

```yaml
- alert: FluxResourceNotReady
  expr: flux_resource_info{ready="False", suspended!="True"} == 1
  for: 15m
  labels: { severity: warning }
  annotations:
    summary: "Flux {{ $labels.kind }}/{{ $labels.name }} not reconciling"
    description: "{{ $labels.exported_namespace }}/{{ $labels.name }} reason: {{ $labels.reason }}"
```

This is the dashboard query's "Not Ready" bucket turned into an alert — same metric, different shape.
