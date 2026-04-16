---
name: kube-prometheus-stack values gotchas for Talos + Cilium + Longhorn clusters
description: Key value overrides needed when installing kps on an anton-shaped cluster (Talos control plane, Cilium kube-proxy replacement, Longhorn default SC)
type: reference
---

Scaffolded into `kubernetes/apps/observability/kube-prometheus-stack` on 2026-04-16 against chart 83.5.0.

**Must-set values for this cluster shape:**

- `crds.upgradeJob.enabled: true` — chart 68.4.0+. The Job runs before Helm upgrade and re-applies CRDs so the Prometheus Operator never sees un-Established CRDs at startup (prometheus-operator #7459).
- HelmRelease-level: `install.crds: Create`, `upgrade.crds: Skip` — override the `kubernetes/flux/cluster/ks.yaml` cluster-wide default of `CreateReplace` so the upgrade Job (not Flux) owns CRD rollover.
- `kubeControllerManager.enabled: false`, `kubeScheduler.enabled: false`, `kubeProxy.enabled: false` — Talos hides control-plane static pods; Cilium replaces kube-proxy. Without these three, `/api/v1/targets` carries 4+ permanently-Down targets and pollutes the smoke test.
- `kubeEtcd.enabled: false` unless you've verified Talos exposes etcd metrics on a reachable endpoint.
- `prometheus.prometheusSpec.{serviceMonitor,podMonitor,rule,probe}SelectorNilUsesHelmValues: false` — without these overrides, selectors get release-scoped labels and scrape-target discovery silently drops ServiceMonitors from other namespaces. Critical if other anton charts (Cilium, Flux, Longhorn, cert-manager, ESO) are expected to auto-wire via their existing ServiceMonitors.
- `grafana.admin.existingSecret: grafana-admin`, plus `userKey: admin-user` and `passwordKey: admin-password`. Grafana does NOT re-read this secret on rotation (helm-charts #3679) — rotating the 1Password item requires restarting the Grafana pod.
- Grafana dashboard sidecar hardening: `sidecar.dashboards.allowUiUpdates: false` and `disableDeletion: true` — enforces GitOps at runtime, not convention. UI-created dashboards disappear on restart anyway; these flags make that explicit.
- `sidecar.dashboards.searchNamespace: ALL` so dashboard ConfigMaps labeled `grafana_dashboard=1` can live in any namespace.

**Must-NOT-set (ADR 0007 hard boundaries):**
- `prometheus.prometheusSpec.thanos.*` — no Thanos sidecar. Keeps the install self-contained on Longhorn; ADR 0006's SeaweedFS install trigger stays unfired.
- `prometheus.prometheusSpec.remoteWrite` — must be empty/absent.
- `alertmanager.config.*` — zero routes at install is an ADR 0007 Decision; adding routes requires ADR authorisation (Trigger 4).

**Storage sizing** (anton defaults, plan 0002): Prometheus 50Gi, Alertmanager 2Gi, Grafana 5Gi, all on `longhorn` SC with RWO.

**Service name for HTTPRoute backend:** `kube-prometheus-stack-grafana` on port 80 (service) → 3000 (pod).
