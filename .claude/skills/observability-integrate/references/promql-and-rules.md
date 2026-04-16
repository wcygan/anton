# PromQL, Recording Rules, Alerting Rules

Reference for query authoring and PrometheusRule content. The CRD shape lives in [prometheus-operator-crds](prometheus-operator-crds.md); this file is about *what goes inside* a rule group.

## Canonical URLs

- **PromQL basics**: https://prometheus.io/docs/prometheus/latest/querying/basics/
- **PromQL functions**: https://prometheus.io/docs/prometheus/latest/querying/functions/
- **PromQL operators**: https://prometheus.io/docs/prometheus/latest/querying/operators/
- **Alerting rule syntax**: https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/
- **Recording rule syntax**: https://prometheus.io/docs/prometheus/latest/configuration/recording_rules/
- **Best-practices — alerting**: https://prometheus.io/docs/practices/alerting/
- **Best-practices — recording rules**: https://prometheus.io/docs/practices/rules/
- **Best-practices — naming**: https://prometheus.io/docs/practices/naming/
- **Best-practices — histograms/summaries**: https://prometheus.io/docs/practices/histograms/

## Alert or record? Decide first.

- **Alert** = fires when a boolean PromQL expression is true for a duration. A notification *might* be sent (depending on Alertmanager routes — anton has none).
- **Record** = pre-computes an expensive or awkward query into a new metric name. You reference the recorded series from dashboards and other rules.

Record when:
- The query is expensive and used in multiple places.
- The query joins / rates over a long range (`[5m]`, `[1h]`) and is polled often.
- You want a clean named series for a dashboard legend.

Don't record when:
- The query is already cheap and only used once.
- The record would just shadow an existing metric (you're adding confusion).

## Alert doctrine (symptom-based)

From the Prometheus maintainers' own guide — the golden path:

1. **Alert on symptoms, not causes.** "Latency is high" > "CPU is high." Users notice latency; they don't notice CPU.
2. **Every alert must be actionable.** If the on-caller can only say "yep, that's broken" and close it, delete the alert.
3. **Use `for:`** to absorb transient spikes. Typical values: `for: 5m` (page-worthy), `for: 15m` (slower burn), `for: 1h` (capacity / trend).
4. **Severity** convention on anton: `warning` (investigate when convenient), `critical` (page). Put in labels: `labels: { severity: warning }`.
5. **Write the runbook link in the annotation.** Even if there's no runbook yet, write the URL you *would* write — it forces clarity about what "fix" means.

```yaml
- alert: NodeFilesystemNearlyFull
  expr: |
    (node_filesystem_avail_bytes{fstype!~"tmpfs|overlay|squashfs"}
     / node_filesystem_size_bytes{fstype!~"tmpfs|overlay|squashfs"}) < 0.10
  for: 15m
  labels:
    severity: warning
  annotations:
    summary: "{{ $labels.instance }} filesystem {{ $labels.mountpoint }} < 10% free"
    runbook_url: "https://wcygan.github.io/anton/runbooks/node-disk"
```

## Recording-rule doctrine

- **Always preserve labels you might group by later.** Prefer `sum by(...) (...)` over `sum without(...)` when the label set is small; prefer `sum without(...)` when you want to preserve most labels.
- **Name recordings with the rollup in the name.** Format: `<level>:<metric>:<operation>_<range>`. Example: `job:http_requests:rate_5m`.
- **`record:` values must be valid metric names** (same char rules as Prometheus metric names). No `/`, no `-` leading.

## PromQL gotchas you will hit

- **Vector matching**: dividing two metrics with different label sets silently drops series. Use `on(...)` / `ignoring(...)` to control matching. `rate(a) / on(pod) rate(b)` is the usual shape.
- **`rate()` vs `irate()`**: `rate()` is almost always what you want (averaged over the range). `irate()` is only for dashboards that need the freshest slope. Avoid `irate()` in alerts.
- **Range-vector at query time**: `metric[5m]` is not a valid *instant* query by itself — you need a function (`rate`, `avg_over_time`, `max_over_time`, …) or a subquery.
- **`absent()` for missing series**: `absent(up{job="foo"} == 1)` fires when the series is gone. Useful for "did this job just disappear?" alerts.
- **`vector(0)` as a default**: `count(x) or vector(0)` returns 0 when `count(x)` has no series. Essential for stat panels that need to show "0" instead of "no data".

## Label hygiene

- Do **not** use high-cardinality labels (user IDs, UUIDs, request IDs). Prometheus will happily ingest them and then OOM.
- `instance` and `pod` are the two "change frequently" labels that are acceptable. Everything else should be low-cardinality and mostly stable.

## Testing rules

```sh
# render the kustomize output, extract one PrometheusRule, feed promtool
mise exec -- kustomize build kubernetes/apps/<ns>/<app>/app/ | \
  yq 'select(.kind == "PrometheusRule") | .spec' - > /tmp/rules.yaml
mise exec -- promtool check rules /tmp/rules.yaml

# unit-test a rule's PromQL against live Prometheus:
kubectl -n observability exec prometheus-kube-prometheus-stack-prometheus-0 -c prometheus -- \
  wget -qO- --post-data='query=<your rule expr>' http://localhost:9090/api/v1/query \
  | mise exec -- jq '.data.result | length, .data.result[0]'
```

## Anton-specific patterns to reuse

```promql
# Flux resources that are not Ready (per kind)
count(flux_resource_info{ready="False"}) by (kind)

# Longhorn volumes in non-healthy state
count(longhorn_volume_robustness != 1) or vector(0)

# Per-node filesystem % used (excluding ephemeral/overlay)
100 - (
  node_filesystem_avail_bytes{fstype!~"tmpfs|overlay|squashfs", mountpoint!~"/var/lib/kubelet/.*"}
  / node_filesystem_size_bytes{fstype!~"tmpfs|overlay|squashfs", mountpoint!~"/var/lib/kubelet/.*"}
) * 100

# Top pod restart counts (24h)
topk(15, sum by (namespace, pod) (increase(kube_pod_container_status_restarts_total[24h])) > 0)

# PVC saturation
(kubelet_volume_stats_used_bytes / kubelet_volume_stats_capacity_bytes) * 100
```
