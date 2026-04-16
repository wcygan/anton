---
status: In-progress
opened: 2026-04-16
closed: null
affects: observability
intent: concrete-need
related-adrs: [0003, 0005, 0007]
review-by: null
---

# 0002 — Install kube-prometheus-stack on Longhorn

> Execute ADR 0007 — scaffold kube-prometheus-stack single-replica on the `longhorn` StorageClass, deliver a curated weekly cluster-health dashboard, and smoke-test end-to-end scraping.

## Goal

Install kube-prometheus-stack in a new `observability` namespace via the Flux 3-file pattern, backed by Longhorn PVCs (2-replica per ADR 0005). Prometheus + Alertmanager stay ClusterIP; Grafana is exposed internal-only on `envoy-internal` with admin creds from 1Password. One committed dashboard (the "weekly glance") is the concrete-need anchor — without it, this install has no named consumer. No Alertmanager routes, no logs, no traces, no Thanos — the four deferred pillars stay deferred until their named triggers fire.

## Acceptance criteria

- [ ] `kube-prometheus-stack` HelmRelease `Ready=True` in namespace `observability`, Flux reconciled
- [ ] Prometheus scrapes kube-apiserver, kubelet, kube-state-metrics, node-exporter, Cilium, Flux, Longhorn, cert-manager, ESO — verified via `/api/v1/targets` scoped to this expected set (Talos does not expose `kubeControllerManager` / `kubeScheduler` / `kubeProxy`, and `kubeEtcd` is conditional — treat those as out-of-scope for the smoke test)
- [ ] Grafana reachable on `envoy-internal` via HTTPRoute, admin password sourced from 1Password via `ExternalSecret`, and the committed "cluster health glance" dashboard loads with non-empty panels
- [ ] PVCs (Prometheus 50Gi, Alertmanager 2Gi, Grafana 5Gi) bound on the `longhorn` SC; baseline RAM/CPU footprint captured under `docs/`
- [ ] Alertmanager reconciles with **zero routes** (by design — ADR 0007 consequence); revisit gated on Trigger 4

## Tasks

- [ ] Hand off to `flux-app-author` for the 3-file pattern under `kubernetes/apps/observability/kube-prometheus-stack/` (new namespace `observability`; check if any existing ns fits first)
- [ ] Pin chart version at scaffold time — re-verify current stable via `upgrade-auditor` before committing; ADR 0007 cites v83.x line, latest patch at review is **83.5.0** (Prometheus Operator v0.90.1, Grafana chart 11.6.1 as of 2026-04-16)
- [ ] CRD lifecycle strategy — enable `crds.upgradeJob.enabled: true` on the HelmRelease values (added in chart 68.4.0) so future operator bumps update CRDs before the Helm upgrade runs; on the HelmRelease itself, set `install.crds: Create` and `upgrade.crds: Skip` to let the job own rollover. Prevents the startup race where the operator silently skips controller registration on un-Established CRDs (prometheus-operator #7459)
- [ ] HelmRelease values (ADR 0007 §Decision): `prometheus.prometheusSpec.replicas: 1`, retention 15d, PVC 50Gi on `longhorn`; `alertmanager.alertmanagerSpec.replicas: 1`, PVC 2Gi; `grafana.replicas: 1`, PVC 5Gi, SQLite; no Thanos sidecar; no remote-write
- [ ] Disable scrape targets Talos does not expose: `kubeControllerManager.enabled: false`, `kubeScheduler.enabled: false`, `kubeProxy.enabled: false` (Cilium replaces kube-proxy). Verify `kubeEtcd` endpoint against the Talos-exposed etcd metrics or disable. Prevents four permanently-down targets from noising up the smoke test
- [ ] Grafana admin password via `ExternalSecret` from 1Password vault `anton` (entry TBD at scaffold time) — note: Grafana does not re-read the secret on rotation (helm-charts #3679); credential rotation must restart the Grafana pod
- [ ] Enable Grafana sidecar ConfigMap pattern for dashboards — GitOps'd, not UI-authored. Harden the sidecar provider: `allowUiUpdates: false`, `disableDeletion: true` to enforce GitOps at runtime, not just by convention
- [ ] Author and commit the "cluster health glance" dashboard — panels: node CPU/RAM/disk, pod restart counts, Flux reconcile state, PVC saturation, Longhorn replica health + degraded-volume count
- [ ] `HTTPRoute` for Grafana on `envoy-internal` — Prometheus + Alertmanager stay ClusterIP
- [ ] `conventions-linter` pre-commit; `task configure` to render + validate
- [ ] Smoke test: `/api/v1/targets` coverage check, Grafana login + dashboard load, Alertmanager web UI reaches steady state
- [ ] Capture baseline Prometheus + Alertmanager + Grafana RSS + CPU under `docs/notes/kps-baseline-YYYY-MM-DD.md` — this is the reference for future bloat detection
- [ ] Update `.claude/agent-memory/cluster-intake-gatekeeper/` per ADR 0007 Follow-up — the monitoring narrative (narrowing-shape reframing) is now durable
- [ ] Close this plan; schedule ADR 0007's 90-day Follow-up revisit

## Log

- 2026-04-16: Plan opened — ADR 0007's install gate formally cleared by plan 0001's Phase 3 baseline. `longhorn` StorageClass is default and smoke-tested (seq-r 219 MB/s, reboot failover 55s, zero data loss). Install path unblocked; next tick hands off to `flux-app-author`.
- 2026-04-16: Currency review via `/web-research` against upstream chart, operator release notes, and Flux + kps canonical pattern. Chart line confirmed current (83.5.0, appVersion v0.90.1, Grafana 11.6.1). Added explicit tasks for CRD lifecycle (`crds.upgradeJob.enabled: true` + `install.crds: Create` / `upgrade.crds: Skip`), Talos-absent scrape-target disables (`kubeControllerManager` / `kubeScheduler` / `kubeProxy`), sidecar provider hardening (`allowUiUpdates: false`, `disableDeletion: true`), and an existingSecret-rotation caveat. Tightened `/api/v1/targets` acceptance criterion to scope the expected target set.

## References

- Related ADRs: 0003 (deferred monitoring — triggers), 0005 (Longhorn — install gate, now cleared), 0007 (kps decision — authoritative)
- Longhorn baseline: `docs/docs/notes/longhorn-baseline-2026-04-16.md`
- Chart: `prometheus-community/kube-prometheus-stack` (HelmRepo or OCI mirror — decide at scaffold)
- Subagent handoffs: `flux-app-author` (scaffold), `upgrade-auditor` (chart pin verification), `conventions-linter` (pre-commit)
