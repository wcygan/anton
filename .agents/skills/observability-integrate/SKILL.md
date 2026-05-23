---
name: observability-integrate
description: Integrate an anton workload with kube-prometheus-stack. Use to add a ServiceMonitor, add a PodMonitor, expose metrics to Prometheus, author a Grafana dashboard (sidecar ConfigMap), write a PrometheusRule (alerts or recording rules), verify scrape targets, or debug why a metric or series is missing. Covers the observability stack installed per ADR 0007 / plan 0002.
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

# Integrate with kube-prometheus-stack

Task skill for wiring anton workloads into the metrics stack. The stack itself was installed under plan 0002 (closed 2026-04-16); this skill is what you use every time afterward. For the *why* behind the install shape (retention, replica counts, deferred pillars) read `context/adrs/0007-adopt-kube-prometheus-stack.md`. This skill assumes you already know the Flux 3-file pattern — if not, load `add-flux-app` or `anton-repo-conventions` first.

## When to invoke

| Intent | Reference | Template |
| --- | --- | --- |
| Scrape a Service's metrics port | [prometheus-operator-crds](references/prometheus-operator-crds.md) | [servicemonitor.yaml.template](templates/servicemonitor.yaml.template) |
| Scrape pods without a Service (or where the Service hides the metrics port) | [prometheus-operator-crds](references/prometheus-operator-crds.md) | [podmonitor.yaml.template](templates/podmonitor.yaml.template) |
| Author a Grafana dashboard | [grafana-dashboards](references/grafana-dashboards.md) | [dashboard-configmap.yaml.template](templates/dashboard-configmap.yaml.template) |
| Write an alerting or recording rule | [promql-and-rules](references/promql-and-rules.md) | [prometheusrule.yaml.template](templates/prometheusrule.yaml.template) |
| Change kps chart values (retention, PVC size, remote-write, …) | [kps-chart-values](references/kps-chart-values.md) | — |
| Verify a new scrape actually landed | [verify-scrapes](references/verify-scrapes.md) | — |
| A metric exists but no series appear | [debug-missing-series](references/debug-missing-series.md) | — |
| Query Flux / kube-state / Longhorn / Cilium metrics | [flux-metrics](references/flux-metrics.md), [integration-metrics](references/integration-metrics.md) | — |

## Anton-specific facts (don't re-derive these)

- **Namespace**: `observability`. All kps workloads live here.
- **Chart**: `kube-prometheus-stack` **83.5.0** via **HelmRepository** (the OCI mirror at `ghcr.io/prometheus-community/charts` is stale at 41.7.4 — do not switch sources without checking Artifact Hub).
- **Discovery scope**: the HelmRelease sets every `*MonitorSelector`, `probeSelector`, and `ruleSelector` to `{}` (match-all) with nil `*NamespaceSelector`. **You can put a ServiceMonitor / PodMonitor / PrometheusRule in any namespace** and Prometheus will pick it up. Co-locate with the app.
- **Grafana sidecar**: looks for ConfigMaps with label `grafana_dashboard: "1"` in **every** namespace (`searchNamespace: ALL`). Hardened: `allowUiUpdates: false`, `disableDeletion: true` — UI edits don't persist, which is intentional.
- **Grafana admin creds**: sourced via `ExternalSecret` from 1Password vault `anton`, item `grafana-admin`. Rotating the item does **not** hot-reload — restart the Grafana pod (helm-charts #3679).
- **Exposure**: Grafana on `envoy-internal` at `grafana.<cluster-domain>`. Prometheus + Alertmanager are **ClusterIP only** — no HTTPRoute.
- **Alertmanager**: zero routes by design (ADR 0007). Don't add a receiver until Trigger 4 (paging need) fires.
- **Talos-absent scrape targets**: `kubeControllerManager`, `kubeScheduler`, `kubeProxy` are disabled in values. Do not re-enable — the endpoints don't exist on Talos (Cilium replaces kube-proxy).
- **Flux controllers** scrape via a **PodMonitor**, not a ServiceMonitor, because the FluxInstance chart's Services only expose port 80, not the `http-prom` metrics port. Path: `kubernetes/apps/flux-system/flux-instance/app/podmonitor.yaml`.
- **Flux ready/not-ready rollup**: use **`flux_resource_info{ready="True"|"False", suspended, kind}`** from the flux-operator job. The commonly-cited `gotk_reconcile_condition` metric is **not exported** by the controllers on this chart line — queries using it return empty. See [flux-metrics](references/flux-metrics.md).
- **Prometheus probe recipe** (port-forwards in the background are unreliable in this repo — use this instead):
  ```sh
  kubectl -n observability exec prometheus-kube-prometheus-stack-prometheus-0 -c prometheus -- \
    wget -qO- --post-data='query=<PROMQL>' http://localhost:9090/api/v1/query
  ```

## Standard workflow — add metrics for a new (or existing) app

1. **Does the app already have a Service on the metrics port?**
   - Yes → `ServiceMonitor`. Confirm the Service's `spec.ports[].name` matches what you'll put in `spec.endpoints[].port`.
   - No, but pods expose `/metrics` on a named container port → `PodMonitor`.
   - No `/metrics` at all → check the chart values; most charts ship a `metrics.serviceMonitor.enabled` flag. Flipping it is almost always simpler than hand-authoring an SM (this is what we did for Cilium, Longhorn).
2. **Co-locate the manifest** with the app under `kubernetes/apps/<ns>/<app>/app/`. Add it to `kustomization.yaml`. Labels don't matter to discovery — kps selectors are match-all — but use `app.kubernetes.io/name: <app>` for readability.
3. **Commit, push, let Flux reconcile.** Do not `kubectl apply` manually.
4. **Verify** with the probe recipe: `{__name__=~"<something>",job="<ns>/<sm-or-pm-name>"}` or check `/api/v1/targets?state=active` for the scrape pool. Full recipe in [verify-scrapes](references/verify-scrapes.md).
5. **If the scrape pool exists but every target is DOWN** → it's almost always a port name mismatch, a cert mismatch (HTTPS endpoints need `tlsConfig.insecureSkipVerify: true` or real TLS), or NetworkPolicy. See [debug-missing-series](references/debug-missing-series.md).

## Standard workflow — add a dashboard

1. Author the dashboard JSON. Either export from Grafana UI (dev-only; don't commit UI-generated JSON that won't pin datasource UIDs) or hand-write referencing [grafana-dashboards](references/grafana-dashboards.md).
2. Wrap it in a ConfigMap with **exactly** `labels.grafana_dashboard: "1"`.
3. Put it next to the HelmRelease that owns the subject (e.g. `kubernetes/apps/storage/longhorn/app/dashboard-longhorn.yaml`). Add to the `app/kustomization.yaml`.
4. Commit, push, reconcile. The Grafana sidecar watches **all namespaces**, so the location is purely for repo hygiene.
5. Verify: open Grafana → Dashboards → Browse. Dashboard appears within ~60s of the ConfigMap existing. If it doesn't, check the sidecar logs: `kubectl -n observability logs deploy/kube-prometheus-stack-grafana -c grafana-sc-dashboard`.

**Validate dashboard queries before committing.** Every panel's `expr` should resolve against live Prometheus — use the probe recipe. A dashboard with broken queries is worse than no dashboard (it hides the fact that no one is watching).

### Anton dashboard shape (established 2026-04-17, ADR 0013 / plan 0003)

The `cluster-health-glance` dashboard is the canonical exemplar — new dashboards extend this shape rather than inventing their own:

- **Header stat strip** at `y: 0, h: 4` — five always-visible stat panels covering subsystem headline numbers (Nodes Ready, Pods non-Running, Flux ready %, API 5xx rate, cert expiries). First impression on page load.
- **Subsystem rows** (`type: row`) below the header, **all `collapsed: false`** — one row per conceptual subsystem (Capacity, Workload Health, Control Plane RED, Nodes USE, Pod Events, Storage, Network & CNI). Operator preference: show content on load, don't hide behind a click.
- **Debug surfaces pair a summary stat strip with a detail table.** When the healthy state is an empty table ("no OOMKills", "no restart hotspots"), the table alone reads as "is this broken?" Add a stat tile above with the "0 — healthy" pattern (see `grafana-dashboards.md`). The dashboard's Workload Health row does this for Unhealthy Workloads / Bad Waiting Pods / Restart Hotspots.
- **Preserve `uid`** across rewrites so existing bookmarks don't break.
- **One dashboard, one scroll** up to ~30 panels. Split into sibling boards only when a single row outgrows ~6 panels.

## Standard workflow — add a PrometheusRule

1. Decide: **alerting** (fires a notification) or **recording** (pre-computes an expensive series). See [promql-and-rules](references/promql-and-rules.md) for when to use which.
2. For alerts: follow the "symptom-based, page-on-action" doctrine — alert on what a human can *do*, not on what's metrically interesting. The plan 0002 revisit (2026-07-15) is the moment to build out the first wave; until then, one-offs are fine.
3. Put the PrometheusRule next to the thing it alerts on. Anton convention: under the owning app's `app/` directory.
4. Validate **before** committing: `promtool check rules <rendered-file>`. You can pipe through `yq`:
   ```sh
   yq '.spec.groups' <file.yaml> | yq -o=yaml > /tmp/rules.yaml && mise exec -- promtool check rules /tmp/rules.yaml
   ```
5. Commit, push, reconcile. Alertmanager has no routes, so firing alerts go to the void until someone wires a receiver — this is fine for silent-alert authoring, not for paging.

## Verification one-liners

```sh
# List all scrape pool jobs and how many targets each has
kubectl -n observability exec prometheus-kube-prometheus-stack-prometheus-0 -c prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/targets?state=active' > /tmp/t.json
mise exec -- jq -r '.data.activeTargets | group_by(.scrapePool) | .[] | "\(length)\t\(.[0].scrapePool)"' /tmp/t.json

# List every job label Prometheus knows about
kubectl -n observability exec prometheus-kube-prometheus-stack-prometheus-0 -c prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/label/job/values' | mise exec -- jq

# Check whether a specific metric name exists at all
kubectl -n observability exec prometheus-kube-prometheus-stack-prometheus-0 -c prometheus -- \
  wget -qO- --post-data='query=<metric_name>' http://localhost:9090/api/v1/query | mise exec -- jq '.data.result | length'
```

## Related skills

- `add-flux-app` — the 3-file pattern every new manifest rides on
- `debug-flux-reconciliation` — when the manifest is committed but the ConfigMap / SM / PM hasn't applied
- `anton-repo-conventions` — SOPS-vs-ESO, postBuild, Flux-namespace rules
- `expose-service` — HTTPRoute + DNSEndpoint (only relevant if you ever need to expose Prometheus or Alertmanager, which ADR 0007 says we don't)

## Pointers

- ADR 0007 (kps decision, deferred-pillar triggers): `context/adrs/0007-adopt-kube-prometheus-stack.md`
- Plan 0002 (install record): `context/plans/0002-install-kube-prometheus-stack.md`
- Baseline (reference footprint): `docs/docs/notes/kps-baseline-2026-04-16.md`
- HelmRelease (source of truth for values): `kubernetes/apps/observability/kube-prometheus-stack/app/helmrelease.yaml`
- Dashboard exemplar: `kubernetes/apps/observability/kube-prometheus-stack/app/dashboard-cluster-health.yaml`
- Flux PodMonitor exemplar: `kubernetes/apps/flux-system/flux-instance/app/podmonitor.yaml`
