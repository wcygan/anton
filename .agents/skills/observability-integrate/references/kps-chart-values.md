# kube-prometheus-stack Chart Values — Reference for Edits

When you need to change what Prometheus scrapes by default, alter retention, add remote-write, or tweak Grafana — you're editing `kubernetes/apps/observability/kube-prometheus-stack/app/helmrelease.yaml`. This is a map of the important value keys so you're not scrolling a 4000-line values.yaml blind.

## Canonical URLs

- **Authoritative values.yaml** (pinned to the version you want to upgrade to): https://github.com/prometheus-community/helm-charts/blob/main/charts/kube-prometheus-stack/values.yaml
- **Chart README** (often more useful than values.yaml for "how is this meant to be used"): https://github.com/prometheus-community/helm-charts/blob/main/charts/kube-prometheus-stack/README.md
- **ArtifactHub** (version-pinned values renders, upgrade notes): https://artifacthub.io/packages/helm/prometheus-community/kube-prometheus-stack
- **Prometheus Operator release notes** (appVersion → operator version mapping): https://github.com/prometheus-operator/prometheus-operator/releases
- **Grafana Helm chart values** (what gets wrapped under `grafana:` in kps): https://raw.githubusercontent.com/grafana/helm-charts/main/charts/grafana/values.yaml
- **Alertmanager chart values**: https://github.com/prometheus-community/helm-charts/blob/main/charts/alertmanager/values.yaml

## Top-level structure

```yaml
values:
  # shared
  fullnameOverride: …
  crds:
    upgradeJob:
      enabled: true          # anton uses this to avoid the un-Established CRD race

  # feature toggles — which scrape targets kps auto-creates
  kubeApiServer: { enabled: true }
  kubelet: { enabled: true }
  kubeControllerManager: { enabled: false }   # Talos — absent
  kubeScheduler:         { enabled: false }   # Talos — absent
  kubeProxy:             { enabled: false }   # Cilium replaces it
  kubeEtcd: { enabled: false|true }           # check Talos etcd exposure before flipping
  kubeStateMetrics: { enabled: true }         # (ships the kube-state-metrics subchart)
  nodeExporter:     { enabled: true }         # (ships node-exporter subchart)
  defaultRules:     { create: true }          # default PrometheusRules the chart ships

  # Prometheus
  prometheus:
    prometheusSpec:
      replicas: 1
      retention: 15d
      retentionSize: "45GB"      # leave ~5Gi headroom under the PVC
      storageSpec:
        volumeClaimTemplate:
          spec:
            storageClassName: longhorn
            resources: { requests: { storage: 50Gi } }
      serviceMonitorSelector:    {}   # nil = match-all
      serviceMonitorNamespaceSelector: {}
      podMonitorSelector:        {}
      podMonitorNamespaceSelector: {}
      ruleSelector:              {}
      ruleNamespaceSelector:     {}
      probeSelector:             {}
      probeNamespaceSelector:    {}
      # add remote-write here when Trigger 3 fires
      remoteWrite: []
      # resources: {}            # leave unset at current scale
      # additionalScrapeConfigs: # last-resort escape hatch; prefer SM/PM

  # Alertmanager
  alertmanager:
    alertmanagerSpec:
      replicas: 1
      storage:
        volumeClaimTemplate:
          spec:
            storageClassName: longhorn
            resources: { requests: { storage: 2Gi } }
    config:
      route: { receiver: "null" }  # zero routes by design (ADR 0007)
      receivers: [ { name: "null" } ]

  # Grafana
  grafana:
    replicas: 1
    persistence:
      enabled: true
      type: pvc
      storageClassName: longhorn
      size: 5Gi
    admin:
      existingSecret: grafana-admin     # populated by ExternalSecret
      userKey: admin-user
      passwordKey: admin-password
    ingress: { enabled: false }          # HTTPRoute handles exposure
    sidecar:
      dashboards:
        enabled: true
        label: grafana_dashboard         # value "1" on the ConfigMap
        searchNamespace: ALL
        provider:
          allowUiUpdates: false
          disableDeletion: true
      datasources:
        enabled: true                    # auto-provisions Prometheus + Alertmanager DS
```

## Common edits and their triggers

| Edit | When | Notes |
| --- | --- | --- |
| `prometheus.prometheusSpec.retention` | Disk pressure or need for longer trend data | Check TSDB compaction headroom first. Doubling retention ≈ doubles PVC need for most workloads. |
| `prometheus.prometheusSpec.storageSpec.*.resources.requests.storage` | Approaching 80% PVC fullness | Longhorn supports online resize. Change Prometheus PVC → wait for StatefulSet rollout → Longhorn expands. |
| `prometheus.prometheusSpec.resources.requests.memory` | OOM kill seen on Prometheus pod | Set both `requests` and `limits`. At our series count (~200k) `1Gi` is fine. Only raise if actual OOM. |
| `prometheus.prometheusSpec.remoteWrite[]` | ADR 0007 Trigger 3 (long-term storage) | Add a target (Mimir, Grafana Cloud, etc.). This is a cross-ADR decision, not a values-tweak. |
| `alertmanager.config` | ADR 0007 Trigger 4 (paging need) | Put route + receivers here. Keep it minimal — one severity dimension. |
| `grafana.resources` | Dashboard load growth | `300Mi` is plenty until many hundreds of dashboards. |
| `grafana.plugins` | Need for a specific datasource plugin | Array of plugin IDs. Grafana re-downloads on pod restart. |
| Re-enable a disabled scrape target | Something changed upstream | Don't. Talos is Talos. Re-enabling `kubeProxy` will add 3 permanently-DOWN targets. |

## CRD lifecycle (operator bumps)

The values that matter:

```yaml
crds:
  upgradeJob:
    enabled: true              # run a Job to update CRDs before upgrading the Helm release
    forceConflicts: true       # required to win race with operator-applied CRDs

# AND at the HelmRelease level (not chart values):
spec:
  install:
    crds: Create
  upgrade:
    crds: Skip                 # let the Job own CRD rollover
```

Rationale: prometheus-operator issue #7459 — if CRDs aren't Established before the operator boots, the operator silently skips controller registration and nothing scrapes until the next restart. The upgrade Job is synchronous; it blocks Helm until CRDs are Established.

## Upgrading the chart

1. Check ArtifactHub for the latest version and any breaking changes.
2. Read the upstream release notes for the operator (`github.com/prometheus-operator/prometheus-operator/releases`). kps minor version bumps often wrap operator minor bumps.
3. Bump `.spec.chart.spec.version` in the HelmRepository-style HelmRelease.
4. Let Flux reconcile. The CRD upgrade Job runs first; if it fails, the HelmRelease will not progress — check `kubectl -n observability logs job/kube-prometheus-stack-admission-create` and friends.
5. Verify: probe `/api/v1/targets`, confirm scrape count didn't drop, confirm `cluster-health-glance` dashboard still renders.

## Escape hatches (use sparingly)

- `prometheus.prometheusSpec.additionalScrapeConfigs` — raw Prometheus scrape YAML for things that can't be ServiceMonitor'd. **Last resort**; prefer authoring a PodMonitor.
- `prometheus.prometheusSpec.externalLabels` — adds a label to every series. Useful only if we ever remote-write to a shared store (Trigger 3).
- `prometheus.prometheusSpec.secrets` — mounts arbitrary Secrets into the Prometheus pod for custom scrape auth.
- `grafana.extraConfigmapMounts` / `extraSecretMounts` — for plugins or custom certs.

## What not to configure

- **HA**: multi-replica Prometheus + Thanos sidecar. Explicitly out of scope per ADR 0007; would multiply cost without a named need.
- **Remote-write** without a destination ADR. Adding remote-write silently is an expensive bug waiting to happen.
- **Thanos Query / Receiver** components. Same — ADR 0007 Trigger 3 or a new ADR.
