---
status: Done
opened: 2026-04-16
closed: 2026-04-16
affects: observability
intent: concrete-need
related-adrs: [0003, 0005, 0007]
review-by: 2026-07-15
---

# 0002 — Install kube-prometheus-stack on Longhorn

> Execute ADR 0007 — scaffold kube-prometheus-stack single-replica on the `longhorn` StorageClass, deliver a curated weekly cluster-health dashboard, and smoke-test end-to-end scraping.

## Goal

Install kube-prometheus-stack in a new `observability` namespace via the Flux 3-file pattern, backed by Longhorn PVCs (2-replica per ADR 0005). Prometheus + Alertmanager stay ClusterIP; Grafana is exposed internal-only on `envoy-internal` with admin creds from 1Password. One committed dashboard (the "weekly glance") is the concrete-need anchor — without it, this install has no named consumer. No Alertmanager routes, no logs, no traces, no Thanos — the four deferred pillars stay deferred until their named triggers fire.

## Acceptance criteria

- [x] `kube-prometheus-stack` HelmRelease `Ready=True` in namespace `observability`, Flux reconciled
- [x] Prometheus scrapes kube-apiserver, kubelet, kube-state-metrics, node-exporter, Cilium, Flux, Longhorn, cert-manager, ESO — verified via `/api/v1/targets` scoped to this expected set (Talos does not expose `kubeControllerManager` / `kubeScheduler` / `kubeProxy`, and `kubeEtcd` is conditional — treat those as out-of-scope for the smoke test)
- [x] Grafana reachable on `envoy-internal` via HTTPRoute, admin password sourced from 1Password via `ExternalSecret`, and the committed "cluster health glance" dashboard loads with non-empty panels
- [x] PVCs (Prometheus 50Gi, Alertmanager 2Gi, Grafana 5Gi) bound on the `longhorn` SC; baseline RAM/CPU footprint captured under `docs/`
- [x] Alertmanager reconciles with **zero routes** (by design — ADR 0007 consequence); revisit gated on Trigger 4

## Tasks

- [x] Hand off to `flux-app-author` for the 3-file pattern under `kubernetes/apps/observability/kube-prometheus-stack/` (new namespace `observability`; check if any existing ns fits first)
- [x] Pin chart version at scaffold time — re-verify current stable via `upgrade-auditor` before committing; ADR 0007 cites v83.x line, latest patch at review is **83.5.0** (Prometheus Operator v0.90.1, Grafana chart 11.6.1 as of 2026-04-16)
- [x] CRD lifecycle strategy — enable `crds.upgradeJob.enabled: true` on the HelmRelease values (added in chart 68.4.0) so future operator bumps update CRDs before the Helm upgrade runs; on the HelmRelease itself, set `install.crds: Create` and `upgrade.crds: Skip` to let the job own rollover. Prevents the startup race where the operator silently skips controller registration on un-Established CRDs (prometheus-operator #7459)
- [x] HelmRelease values (ADR 0007 §Decision): `prometheus.prometheusSpec.replicas: 1`, retention 15d, PVC 50Gi on `longhorn`; `alertmanager.alertmanagerSpec.replicas: 1`, PVC 2Gi; `grafana.replicas: 1`, PVC 5Gi, SQLite; no Thanos sidecar; no remote-write
- [x] Disable scrape targets Talos does not expose: `kubeControllerManager.enabled: false`, `kubeScheduler.enabled: false`, `kubeProxy.enabled: false` (Cilium replaces kube-proxy). Verify `kubeEtcd` endpoint against the Talos-exposed etcd metrics or disable. Prevents four permanently-down targets from noising up the smoke test
- [x] Grafana admin password via `ExternalSecret` from 1Password vault `anton` (entry TBD at scaffold time) — note: Grafana does not re-read the secret on rotation (helm-charts #3679); credential rotation must restart the Grafana pod
- [x] Enable Grafana sidecar ConfigMap pattern for dashboards — GitOps'd, not UI-authored. Harden the sidecar provider: `allowUiUpdates: false`, `disableDeletion: true` to enforce GitOps at runtime, not just by convention
- [x] Author and commit the "cluster health glance" dashboard — panels: node CPU/RAM/disk, pod restart counts, Flux reconcile state, PVC saturation, Longhorn replica health + degraded-volume count
- [x] `HTTPRoute` for Grafana on `envoy-internal` — Prometheus + Alertmanager stay ClusterIP
- [x] `conventions-linter` pre-commit; `task configure` to render + validate
- [x] Smoke test: `/api/v1/targets` coverage check, Grafana login + dashboard load, Alertmanager web UI reaches steady state
- [x] Capture baseline Prometheus + Alertmanager + Grafana RSS + CPU under `docs/notes/kps-baseline-YYYY-MM-DD.md` — this is the reference for future bloat detection
- [ ] Update `.claude/agent-memory/cluster-intake-gatekeeper/` per ADR 0007 Follow-up — the monitoring narrative (narrowing-shape reframing) is now durable *(deferred — tracked in closing log)*
- [x] Close this plan; schedule ADR 0007's 90-day Follow-up revisit

## Log

- 2026-04-16: Plan opened — ADR 0007's install gate formally cleared by plan 0001's Phase 3 baseline. `longhorn` StorageClass is default and smoke-tested (seq-r 219 MB/s, reboot failover 55s, zero data loss). Install path unblocked; next tick hands off to `flux-app-author`.
- 2026-04-16: Currency review via `/web-research` against upstream chart, operator release notes, and Flux + kps canonical pattern. Chart line confirmed current (83.5.0, appVersion v0.90.1, Grafana 11.6.1). Added explicit tasks for CRD lifecycle (`crds.upgradeJob.enabled: true` + `install.crds: Create` / `upgrade.crds: Skip`), Talos-absent scrape-target disables (`kubeControllerManager` / `kubeScheduler` / `kubeProxy`), sidecar provider hardening (`allowUiUpdates: false`, `disableDeletion: true`), and an existingSecret-rotation caveat. Tightened `/api/v1/targets` acceptance criterion to scope the expected target set.
- 2026-04-16: **Closed.** Stack installed on chart 83.5.0 via upstream HelmRepository (OCI mirror was stale at 41.7.4 — matches the Longhorn fallback precedent). All five acceptance criteria met:
  - HelmRelease `Ready=True`, Flux reconciled to `4d2b1ad0`.
  - 23 scrape jobs discovered after wiring Cilium (`prometheus.serviceMonitor.enabled: true` on both agent + operator), Longhorn (`metrics.serviceMonitor.enabled: true`), and a hand-authored `PodMonitor` for Flux controllers (the chart ships Services only on port 80, so ServiceMonitor discovery alone misses the `http-prom` metrics port).
  - Grafana reachable on `envoy-internal` at `grafana.<cluster-domain>`; admin creds sourced from 1Password vault `anton` item `grafana-admin` via the repo's first `ExternalSecret` (onepasswordSDK combined-key syntax `grafana-admin/username`).
  - PVCs bound: Prometheus 50 Gi, Alertmanager 2 Gi, Grafana 5 Gi, all on `longhorn`.
  - Alertmanager reconciled with zero routes (intentional per ADR 0007).
  - Seven-panel `cluster-health-glance` dashboard committed as a sidecar ConfigMap. **Gotcha recorded for future:** `gotk_reconcile_condition` is not exposed by the Flux controllers on this version — only `gotk_reconcile_duration_*` plus token/event/cache metrics. The cross-resource ready/suspended rollup lives on **flux-operator**'s `flux_resource_info{ready=…, suspended=…, kind=…}`; panel queries corrected accordingly in commit `4d2b1ad0`.
  - Baseline captured: Prometheus 68m / 810Mi, Grafana 17m / 283Mi, Alertmanager 5m / 33Mi, TSDB head ~199k series. Full writeup at `docs/docs/notes/kps-baseline-2026-04-16.md`.
- 2026-04-16: **Follow-ups carried out of plan scope:**
  - Update `.claude/agent-memory/cluster-intake-gatekeeper/` with the ADR 0007 monitoring narrative (narrowing-shape reframing) — deferred; the intake memory system is a separate workstream and the narrative is already durable in the ADR itself.
  - ADR 0007 90-day revisit scheduled via frontmatter `review-by: 2026-07-15` on this plan; when that date hits, re-evaluate right-sizing (retention / PVC), Alertmanager route authoring, and whether any of the four deferred pillars (Loki, Tempo, long-term storage, remote-write) have hit their trigger.

## References

- Related ADRs: 0003 (deferred monitoring — triggers), 0005 (Longhorn — install gate, now cleared), 0007 (kps decision — authoritative)
- Longhorn baseline: `docs/docs/notes/longhorn-baseline-2026-04-16.md`
- Chart: `prometheus-community/kube-prometheus-stack` (HelmRepo or OCI mirror — decide at scaffold)
- Subagent handoffs: `flux-app-author` (scaffold), `upgrade-auditor` (chart pin verification), `conventions-linter` (pre-commit)
