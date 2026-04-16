# Grafana Dashboards — Sidecar ConfigMap Pattern

How to author and ship dashboards on anton. The only path is GitOps-via-ConfigMap — UI edits don't persist (we hardened the sidecar with `allowUiUpdates: false`, `disableDeletion: true`).

## Canonical URLs

- **Grafana Helm chart values** (sidecar section): https://raw.githubusercontent.com/grafana/helm-charts/main/charts/grafana/values.yaml
- **Dashboard JSON model**: https://grafana.com/docs/grafana/latest/dashboards/build-dashboards/
- **Panel catalog**: https://grafana.com/docs/grafana/latest/panels-visualizations/
- **Template variables**: https://grafana.com/docs/grafana/latest/dashboards/variables/
- **Provisioning (deep background on how the sidecar feeds Grafana)**: https://grafana.com/docs/grafana/latest/administration/provisioning/
- **Field overrides / thresholds**: https://grafana.com/docs/grafana/latest/panels-visualizations/configure-overrides/
- **sidecar image (k8s-sidecar) behavior**: https://github.com/kiwigrid/k8s-sidecar

## The one pattern

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: dashboard-<slug>
  namespace: <ns>                      # any namespace — sidecar watches all
  labels:
    grafana_dashboard: "1"             # EXACT value. "true" will not work.
data:
  <slug>.json: |
    {
      "uid": "<slug>",                 # keep stable across edits; used in URLs
      "title": "<Title>",
      "schemaVersion": 39,             # current line; 39+ is safe on Grafana 12
      "tags": ["anton", "<subject>"],
      "time": { "from": "now-6h", "to": "now" },
      "refresh": "30s",
      "timezone": "browser",
      "editable": false,               # UI can't save anyway — this makes it explicit
      "panels": [ /* ... */ ]
    }
```

The sidecar (`k8s-sidecar`) watches ConfigMaps cluster-wide for label `grafana_dashboard: "1"` and writes the file into Grafana's provisioning directory. Grafana reloads automatically within the poll interval (~30s).

## Panel skeleton

Every panel needs: `id`, `type`, `title`, `gridPos`, `datasource`, `targets`. Typical fields:

```json
{
  "id": 1,
  "type": "timeseries",
  "title": "<panel title>",
  "gridPos": { "x": 0, "y": 0, "w": 8, "h": 8 },
  "datasource": { "type": "prometheus", "uid": "prometheus" },
  "fieldConfig": {
    "defaults": {
      "unit": "percent",
      "min": 0, "max": 100,
      "thresholds": {
        "mode": "absolute",
        "steps": [
          { "color": "green", "value": null },
          { "color": "yellow", "value": 70 },
          { "color": "red", "value": 90 }
        ]
      }
    }
  },
  "targets": [
    {
      "refId": "A",
      "expr": "<PromQL>",
      "legendFormat": "{{instance}}"
    }
  ]
}
```

## Panel type picking guide

| Use case | Panel type |
| --- | --- |
| A line over time | `timeseries` |
| A single number (e.g. "3 degraded volumes") | `stat` |
| A ranked list (top N pods, top N queries) | `table` with `sortBy` |
| Horizontal progress bars for multi-item saturation | `bargauge` with `orientation: horizontal`, `displayMode: gradient` |
| Service map / distribution | `piechart` (sparingly) or `stat` with multiple values |
| Logs | `logs` (requires Loki — **not installed on anton**) |

## Datasource UIDs on anton

- **Prometheus**: `uid: "prometheus"`
- **Alertmanager** (metadata only, no metric queries): `uid: "alertmanager"`

These are the defaults the kps chart provisions. If you export a dashboard from Grafana UI for local tweaking, replace any auto-generated UID (`P1809F7CD0C75ACF3` style) with the literal `"prometheus"` before committing — otherwise the dashboard is broken on every fresh cluster.

## Variables (template vars)

For multi-cluster / multi-namespace dashboards you'd use template variables. On anton we have one cluster, three nodes, so:

```json
"templating": {
  "list": [
    {
      "name": "namespace",
      "type": "query",
      "datasource": { "type": "prometheus", "uid": "prometheus" },
      "query": "label_values(kube_namespace_created, namespace)",
      "refresh": 1,
      "includeAll": true,
      "multi": true
    }
  ]
}
```

Keep it simple. A dashboard with 5 template vars is a dashboard no one reads.

## Validation before commit

1. **JSON parses** — `jq . <file.json>` (or the embedded string). Broken JSON silently fails to load; Grafana just omits the dashboard.
2. **Every `expr` returns data** — use the probe recipe in [verify-scrapes](verify-scrapes.md) on each panel's query.
3. **schemaVersion ≤ Grafana's supported version** — Grafana 12 supports schema up through 40. Stay at 39 to leave headroom.
4. **No raw UIDs from local Grafana** — search for strings matching `"uid":\s*"[A-Z0-9]{14,}"` and replace with `"prometheus"` or `"alertmanager"`.

## Exporting from Grafana UI (sparingly)

Okay as a **starting point** for a complex dashboard:

1. Build in Grafana UI.
2. Settings → JSON Model → copy.
3. Strip `id`, set `uid` to a stable slug, strip auto-generated datasource UIDs, set `editable: false`.
4. Wrap in a ConfigMap, commit.

Do **not** commit a UI export without cleanup — auto UIDs will break the dashboard on the next cluster rebuild.

## Debugging a dashboard that doesn't appear

1. Is the ConfigMap there? `kubectl get cm -A -l grafana_dashboard=1`
2. Does the sidecar see it? `kubectl -n observability logs deploy/kube-prometheus-stack-grafana -c grafana-sc-dashboard --tail=100 | rg <slug>`
3. Is Grafana picking it up? `kubectl -n observability exec deploy/kube-prometheus-stack-grafana -c grafana -- ls /tmp/dashboards/`
4. Does the JSON parse? Grafana's main container will log `failed to load dashboard` if not.
