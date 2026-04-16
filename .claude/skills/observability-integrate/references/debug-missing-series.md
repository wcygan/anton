# Debugging Missing Series

"The metric exists, why is my query returning nothing?" is the third-most-common thing you'll do with this skill (after adding a SM/PM and adding a dashboard). This is the decision tree.

## Hierarchy of causes

1. The metric **name is wrong** (renamed upstream, mistyped, historical).
2. The metric **exists but not for the selector you used** (wrong `job`, wrong `namespace`, different label shape).
3. The scrape is **failing** (target DOWN).
4. The scrape **isn't configured** (SM/PM/CR not loaded).
5. The app **isn't exposing the metric** (chart option off, custom build, newer/older version).

Walk top to bottom.

## Step 1 — Does the metric name exist, at all?

```sh
kubectl -n observability exec prometheus-kube-prometheus-stack-prometheus-0 -c prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/label/__name__/values' \
  | mise exec -- jq -r '.data[]' | rg -i '<partial>'
```

If the name doesn't appear, **no source Prometheus knows about emits it**. Possible reasons:
- Upstream renamed or removed it. Check the exporter's release notes.
- The exporter is on an old version. Check its image tag.
- The metric is only emitted conditionally (e.g. only when a feature flag is on).

**Real anton example**: `gotk_reconcile_condition` is not in this list. We relied on it for the cluster-health dashboard's Flux panel, pre-verified it existed, found it didn't, and switched to `flux_resource_info` (emitted by flux-operator, not the controllers). See [flux-metrics](flux-metrics.md).

## Step 2 — Does the metric exist under a different label shape?

```sh
kubectl -n observability exec prometheus-kube-prometheus-stack-prometheus-0 -c prometheus -- \
  wget -qO- --post-data='query=<metric_name>' 'http://localhost:9090/api/v1/query' \
  | mise exec -- jq -r '.data.result[].metric | to_entries | map(.key + "=" + (.value|tostring)) | join(",")' \
  | sort -u | head -20
```

This shows the distinct label sets. Inspect:
- `job=` — what job is emitting this? Maybe it's not the one you expected.
- `namespace=` / `exported_namespace=` — which namespace? (some exporters rewrite `namespace` to `exported_namespace` to avoid collision with the scrape namespace).
- `instance=` — which pod / port?

Adjust your query's selector to match.

## Step 3 — Is there a `job` that should be emitting this?

```sh
kubectl -n observability exec prometheus-kube-prometheus-stack-prometheus-0 -c prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/label/job/values' | mise exec -- jq -r '.data[]' | sort
```

If you expected `job="foo"` but it's not listed, the scrape config for `foo` isn't loaded. Go to [verify-scrapes](verify-scrapes.md) Recipe 1 and look for the scrape pool.

## Step 4 — Scrape pool exists, target is DOWN

See [verify-scrapes](verify-scrapes.md) Recipe 3 for the error taxonomy.

Extra cases we've actually hit:

- **PodMonitor targeting by Service port name**: PodMonitor does not use Service ports — it uses **container port names**. If you wrote `port: http-metrics` but the container ports are unnamed, the PodMonitor will show zero targets (not DOWN, just zero). Fix: name the container port or use `targetPort` (less preferred).
- **Selector labels changed under you**: a chart upgrade added / removed labels. SM / PM selectors are exact-match; if the chart now labels pods with `app.kubernetes.io/name` but your SM still matches `app=...`, you get zero targets. Dump the pod labels: `kubectl -n <ns> get pods --show-labels`.
- **namespaceSelector excludes the target**: you wrote `namespaceSelector: { matchNames: [foo] }` but the app is in `bar`. Anton's scrape discovery is cluster-wide, but you constrained your SM. Remove the constraint or fix the namespace.

## Step 5 — Scrape succeeds but my metric still isn't there

Exec into the target pod (or `kubectl port-forward` for local inspection):

```sh
# If the pod has curl/wget installed:
kubectl -n <ns> exec <pod> -- wget -qO- http://localhost:<port>/metrics | rg '<metric-name>'

# If not, use the pod's own network namespace via a debug container:
kubectl -n <ns> debug <pod> --image=busybox --target=<container> -it -- \
  wget -qO- http://localhost:<port>/metrics | rg '<metric-name>'
```

If the metric isn't in the raw `/metrics` response, the exporter isn't emitting it. Usually:
- A chart values flag is off (e.g. `metrics.detailed: true`).
- The feature that produces the metric hasn't run yet (counters exist only after the first increment).
- You're on an older version where the metric was named differently.

## Step 6 — Metric shows in `/metrics` but not in Prometheus

Now it's a relabeling or filtering issue:

```sh
# grep the final scrape config
kubectl -n observability exec prometheus-kube-prometheus-stack-prometheus-0 -c prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/status/config' \
  | mise exec -- jq -r '.data.yaml' > /tmp/prom.yaml
# find the scrape_config for your job
mise exec -- yq '.scrape_configs[] | select(.job_name | test("<job>"))' /tmp/prom.yaml
```

Look for:
- `metric_relabel_configs` with `action: drop` — kps default rules drop several high-cardinality cAdvisor metrics by default.
- `honor_labels: true` — can cause a client-supplied `job` / `instance` to override, so your query selector is wrong.
- `sample_limit` — scrape is truncating above a threshold. Raise or fix cardinality at the source.

## Step 7 — Still missing

Almost certainly an upstream issue. File an issue against the exporter, or switch to the correct source. On anton this has happened twice: `gotk_reconcile_condition` (use `flux_resource_info`), `gotk_resource_info` via KSM customResourceState (use flux-operator's native `flux_resource_info`).

## Quick reference — metrics we verified exist (as of 2026-04-16)

- `up` — every job
- `flux_resource_info{ready,suspended,kind}` — from `flux-operator`
- `gotk_reconcile_duration_seconds_*` — from `flux-system/flux-controllers`
- `longhorn_volume_robustness`, `longhorn_disk_storage_*` — from `longhorn-backend`
- `cilium_unreachable_nodes`, `cilium_drop_count_total` — from `cilium-agent`
- `kube_pod_container_status_restarts_total`, `kube_namespace_created` — from `kube-state-metrics`
- `node_cpu_seconds_total`, `node_filesystem_avail_bytes`, `node_memory_MemAvailable_bytes` — from `node-exporter`
- `kubelet_volume_stats_used_bytes`, `kubelet_volume_stats_capacity_bytes` — from `kubelet`
- `certmanager_certificate_expiration_timestamp_seconds` — from `cert-manager`
- `externalsecret_sync_calls_total` — from `external-secrets-metrics`
