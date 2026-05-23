# Prometheus Operator CRDs — ServiceMonitor, PodMonitor, PrometheusRule, Probe

Deep reference for the four CRDs you author against kps. Use the local summary for quick decisions; WebFetch the canonical URLs when you need the latest field-by-field spec.

## Canonical URLs

- **API reference** (all CRDs, every field): https://prometheus-operator.dev/docs/api-reference/api/
- **Design doc** (why the CRDs exist, how selectors compose): https://prometheus-operator.dev/docs/getting-started/design/
- **Developer getting-started** (how to expose metrics from an app): https://github.com/prometheus-operator/prometheus-operator/blob/main/Documentation/developer/getting-started.md
- **Alerting routes** (when you eventually wire Alertmanager): https://prometheus-operator.dev/docs/developer/alerting/
- **Chart values that drive the selectors**: https://github.com/prometheus-community/helm-charts/blob/main/charts/kube-prometheus-stack/values.yaml

## ServiceMonitor — the default choice

Discovers targets by scraping Pods **behind a Service**. Use when the app already exposes a Service on the metrics port.

Minimum viable shape:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: <app>-metrics
  namespace: <ns>                  # doesn't matter for discovery — anton's selectors are nil
spec:
  namespaceSelector:
    matchNames: [<ns>]             # scope which namespaces' Services to scrape
  selector:
    matchLabels:
      app.kubernetes.io/name: <app>  # must match the Service's labels
  endpoints:
    - port: metrics                # must match Service spec.ports[].name (not number)
      interval: 30s
      path: /metrics
```

**Pitfalls**:
- `endpoints[].port` is the Service's **port name**, not number. If the Service uses an unnamed port, you must name it first.
- HTTPS endpoints need `scheme: https` + `tlsConfig.insecureSkipVerify: true` (or real CA config).
- If the target is a metrics-only Service (separate from the main app Service), the selector usually needs `matchLabels` aimed at the metrics Service alone — don't accidentally scrape two Services on the same selector.
- `honorLabels: true` is the right call only when the exporter **already** carries a `job` label you want to preserve (e.g. Blackbox).

## PodMonitor — when the Service hides the metrics port

Use when there is no Service, or the Service exposes port 80 / the app port but **not** the metrics port. This is what Flux needs on anton — the FluxInstance chart ships Services on port 80 only.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: <app>-controllers
  namespace: <ns>
spec:
  namespaceSelector:
    matchNames: [<ns>]
  selector:
    matchLabels:
      app.kubernetes.io/part-of: <app>   # pod label, not Service label
  podMetricsEndpoints:
    - port: http-prom                    # must match container port NAME
      interval: 30s
      path: /metrics
```

**Pitfalls**:
- `podMetricsEndpoints[].port` is the container port **name** (pod spec `spec.containers[].ports[].name`). If containers don't name ports, PodMonitor can't target them — you'd have to use `targetPort` (discouraged) or modify the pod spec.
- PodMonitor does not care about Services at all — handy for Jobs / CronJobs / sidecar-only exporters.

## PrometheusRule — alerts and recording rules

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: <app>-rules
  namespace: <ns>
  labels:
    # optional: kps default selector is match-all, so labels don't gate discovery
    prometheus: kube-prometheus-stack
    role: alert-rules
spec:
  groups:
    - name: <app>.recording
      interval: 30s
      rules:
        - record: job:<app>_error_rate:ratio_5m
          expr: |
            sum by(job) (rate(http_requests_total{status=~"5.."}[5m]))
              /
            sum by(job) (rate(http_requests_total[5m]))
    - name: <app>.alerts
      rules:
        - alert: <App>ErrorRateHigh
          expr: job:<app>_error_rate:ratio_5m > 0.05
          for: 10m
          labels:
            severity: warning
          annotations:
            summary: "<App> error rate above 5% for 10m"
            description: "{{ $labels.job }} is at {{ $value | humanizePercentage }}"
```

**Validation** (run before commit):

```sh
yq '.spec.groups' <file.yaml> | yq -o=yaml > /tmp/rules.yaml
mise exec -- promtool check rules /tmp/rules.yaml
```

## Probe — blackbox-style external checks

Rarely used on anton. Requires `blackbox-exporter` to exist (it does not — add it if you actually need synthetic probing). Canonical spec: same API reference URL above.

## How the selectors compose on anton

The HelmRelease sets:

```yaml
prometheus:
  prometheusSpec:
    serviceMonitorSelector: {}
    serviceMonitorNamespaceSelector: {}
    podMonitorSelector: {}
    podMonitorNamespaceSelector: {}
    ruleSelector: {}
    ruleNamespaceSelector: {}
    probeSelector: {}
    probeNamespaceSelector: {}
```

Empty object + nil namespace selector = **scrape everything, everywhere**. You do not need to add labels to get picked up. This is intentional — anton is single-tenant — but it means:
- A malformed SM / PM **does** land in the scrape config and shows up as a "DOWN" pool. Don't assume "Prometheus ignored it."
- A PrometheusRule with broken PromQL **does** get loaded and will surface in `/api/v1/rules` as `health: err`. Check there if an alert never fires.

## Decision cheat sheet

| Situation | Pick |
| --- | --- |
| App has a Service on the metrics port | ServiceMonitor |
| Chart has `metrics.serviceMonitor.enabled` | Flip the chart flag; don't author your own |
| No Service, or Service doesn't expose metrics port | PodMonitor |
| Sidecar exporter in a Job / CronJob | PodMonitor |
| Probing an external URL / ICMP target | Probe (requires blackbox-exporter — not installed) |
| Alert or recording rule | PrometheusRule |
