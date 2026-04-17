---
status: Accepted
date: 2026-04-17
deciders: ['@wcygan']
affects: observability
intent: concrete-need
supersedes: []
superseded-by: null
retrospective: false
---

# 0013 — Restructure the cluster-health Grafana dashboard top-down; defer Talos control-plane scrapes; reject a Talos OS exporter bridge

> The single `cluster-health-glance` dashboard is rewritten into a progressive-disclosure layout (header stats → capacity → control plane → nodes → workloads → storage → network); enabling etcd / kube-controller-manager / kube-scheduler scrapes is named as a follow-up trigger, not committed today; a Talos-specific textfile-exporter bridge is rejected.

## Status

Accepted

## Context

ADR 0007's Follow-up 3 committed anton to "commit a cluster-health dashboard to Git at install time" as the **named consumer** of the kube-prometheus-stack install. That commitment was met minimally: `kubernetes/apps/observability/kube-prometheus-stack/app/dashboard-cluster-health.yaml` ships seven panels — node CPU / memory / filesystem, top pod restarts (24h), Flux reconcile state, PVC saturation, Longhorn volume robustness. Good coverage of storage and workloads; no control-plane, no network, no header-stat surface.

Two events make now the right time to revisit the shape:

1. **Grafana is newly reachable over the tailnet with a browser-trusted cert** (ADR 0012 validation, landed today as `kube-prometheus-stack: enable grafana Tailscale Ingress`). The dashboard is no longer a `kubectl port-forward` chore — it's a surface the operator will actually open, so its layout starts to matter.
2. **The operator has asked for progressive enhancement** — high-level glance at the top, drill-down panels below as the page scrolls. This is the canonical top-down pattern (Four Golden Signals × USE × RED) that every mature Kubernetes dashboard family uses: dotdc 15757/15759/15761/15762, kubernetes-mixin's `k8s-resources-*` series, Grafana #315, #1860.

A parallel question surfaced during research: **can Talos-specific OS metrics be piped into kube-prometheus-stack?** The honest answer is that Talos exposes **no native Prometheus endpoint** on `apid` / `machined` / `trustd` — there is no `machined_*` / `apid_*` metric family. What Talos *can* expose are the Kubernetes control-plane components it hosts:

- **etcd** on `:2381/metrics`, gated behind `cluster.etcd.extraArgs.listen-metrics-urls: https://0.0.0.0:2381` plus client-cert secret mount.
- **kube-controller-manager** and **kube-scheduler**, gated behind `bind-address: 0.0.0.0` machine-config patches.

All three are **currently disabled on anton** in `helmrelease.yaml` (commented inline as "Talos hides them, Cilium replaces kube-proxy"). Enabling etcd is the single highest-ROI Talos-layer observability add — etcd leader changes, DB size, and proposal failures are invaluable on a three-control-plane cluster. But it requires a rolling Talos machine-config change, which is a materially different change class than a dashboard JSON edit.

The final option — a `talosctl get … -o json` → textfile-exporter bridge for Talos-unique OS state (machine-config drift, upgrade state, schematic ID) — is technically possible but has no concrete-need anchor today. node-exporter + kube-state-metrics already cover ~95% of useful OS signal at homelab scale.

## Decision

Anton restructures the cluster-health dashboard in three phases, two of which are committed today and one of which is explicitly rejected:

### Phase 1 — Restructure + extend `cluster-health-glance` (Accepted, landing this week)

Rewrite `kubernetes/apps/observability/kube-prometheus-stack/app/dashboard-cluster-health.yaml` into a progressive-disclosure layout:

- **Header strip (no collapsible row, always visible)** — 5 stat panels: Nodes Ready, Pods by phase, Flux Kustomizations ready %, API-server 5xx rate (last 5m), cert-manager certs expiring < 14 days.
- **Collapsible rows below, top-2 default-expanded:**
  - `Cluster Capacity` — existing node CPU / memory / filesystem panels + new cluster CPU and memory commit ratio.
  - `Control Plane (RED)` — API-server QPS by verb, p99 request latency, error rate. Uses only what kube-prometheus-stack already scrapes (api-server ServiceMonitor is enabled).
  - `Nodes (USE)` — existing node panels + node pressure conditions (Memory/Disk/PID) + per-node network Rx/Tx.
  - `Workloads` — existing pod restarts + pending pods over time + OOMKilled rate.
  - `Storage` — existing PVC saturation + Longhorn volume robustness + Longhorn replica count.
  - `Network & CNI` — CoreDNS QPS, CoreDNS non-NOERROR response rate, Cilium/Hubble flow rate.

Target: 16–20 panels, one dashboard, one scroll. `uid: cluster-health-glance` is preserved so existing URLs do not break. Same ConfigMap, no new scrape config, no cluster changes.

### Phase 2 — Enable kubeEtcd / kubeControllerManager / kubeScheduler scrapes (Deferred with a named trigger)

Not committed today. Authorised when any of the following happens:

- *"I wanted to know whether etcd had a leader change during <incident> and couldn't."*
- *"I wanted to see kube-controller-manager reconcile latency and couldn't."*
- *"A Renovate PR bumps kube-prometheus-stack and I'm looking at what the chart defaults want me to scrape anyway."*

When fired, a follow-up ADR (or a PR referencing this ADR if no shape question remains) will:

1. Patch Talos controlplane machine config — `cluster.etcd.extraArgs.listen-metrics-urls: https://0.0.0.0:2381`, mount etcd client certs for Prometheus, set `bind-address: 0.0.0.0` in `controllerManager.extraArgs` and `scheduler.extraArgs`. Rolling apply via the `talos-operator` subagent, one node at a time, etcd-quorum-gated.
2. Flip `kubeEtcd.enabled`, `kubeControllerManager.enabled`, `kubeScheduler.enabled` to `true` in `kube-prometheus-stack` values.
3. Add an etcd / scheduler / KCM row to the dashboard below `Control Plane (RED)`.

### Phase 3 — Talos-specific OS exporter bridge (Rejected)

No CronJob-driven `talosctl get … -o json` → textfile-exporter pipeline today. The missing signal (machine-config drift, upgrade state, schematic ID, staged-reboot) has no concrete-need anchor, and node-exporter + kube-state-metrics already answer "is the machine healthy" at homelab scale. Reframed authorisation conditions live in **Re-adoption guidance** below.

## Alternatives considered

- **Do nothing — keep the seven-panel board** — rejected. The operator has named progressive enhancement as the concrete need, and the dashboard is now a tailnet surface worth polishing. Seven panels don't answer "is the control plane ok" or "is the network ok."
- **Split into sibling boards immediately** (`cluster-overview`, `cluster-network`, `cluster-storage`) — rejected for now. Under ~20 panels, one dashboard with collapsible rows is easier to scan than three dashboards with tab-switching overhead. Splitting becomes the right move when any single subsystem row outgrows ~6 panels; documented as a Follow-up trigger.
- **Import the dotdc 15757/15759/15761/15762 family wholesale and drop the custom board** — rejected. The anton-specific panels (Flux reconcile, Longhorn robustness, and eventually etcd-on-Talos) would be scattered or missing across the default family. The custom `cluster-health-glance` remains the "is the cluster ok" surface; dotdc dashboards are linked from panel descriptions for per-subsystem drill-down.
- **Commit Phase 2 now (enable all three control-plane scrapes today)** — rejected. Phase 2 touches Talos machine config, which is a different change class than JSON editing and wants its own PR with `talos-operator` gating. Bundling it with the dashboard rewrite would couple a low-risk values edit to a rolling controlplane apply. Kept as a named trigger instead.
- **Commit Phase 3 now (Talos OS textfile bridge)** — rejected. No named incident where the missing Talos OS signal cost the operator time. Classic completionism (ADR 0001 graveyard pattern).

## Consequences

### Accepted costs

- **ConfigMap grows from ~7 KB to ~20–25 KB.** Still comfortably under the 1 MiB ConfigMap limit. Sidecar reload time per reconcile stays negligible.
- **The dashboard JSON is hand-authored, not imported.** Every panel edit is a repo edit + Flux sync; the sidecar has `allowUiUpdates: false` (ADR 0007's GitOps-only posture). Cost accepted; this is the whole point.
- **Phase 2 is a *named* debt, not a hidden one.** If the trigger never fires, anton stays on "kube-scheduler / KCM / etcd are scraped via the generic kubelet cAdvisor surface only." That is already enough for pod-level observability; missing signal is strictly control-plane-internal.
- **No new Renovate-PR tax.** No new chart, no new CRDs. Phase 1 is values-free; Phase 2 (when it fires) is a values flip + a Talos patch, both inside existing infra.
- **Phase 2, when it fires, exposes kube-controller-manager and kube-scheduler on `:10257` / `:10259` to the node's network namespace.** Mitigated by the fact that the node network is reachable only via Tailscale or physical LAN; the three ports are not internet-exposed. Documented here so the follow-up ADR doesn't need to re-derive it.

### What this preserves

- **ADR 0007 Follow-up 3 remains satisfied.** The dashboard that was the named consumer of the metrics install still exists and is still the one dashboard the operator opens; this ADR deepens it rather than replacing it.
- **GitOps-only dashboard discipline (ADR 0007).** All authoring stays in `dashboard-cluster-health.yaml`; nothing is authored in the Grafana UI.
- **Tailscale-only exposure (ADR 0012).** No new ingress; the restructured board is reached through the existing `ingressClassName: tailscale` Ingress.
- **Anti-completionism discipline (ADR 0001).** Phase 3 is rejected with a named re-adoption condition rather than silently skipped. Phase 2 is deferred with a named trigger rather than silently bundled.
- **Talos-as-immutable-OS posture.** No textfile-exporter CronJob, no host-path writes, no workarounds for Talos' deliberately narrow surface.

## Re-adoption guidance — Phase 3 (Talos OS exporter bridge)

This is not a full `Reverted` ADR, but the rejection deserves explicit reframing conditions so a future intake doesn't re-litigate from scratch:

- **Concrete-need reframing** — an incident where machine-config drift, a staged Talos upgrade, or a schematic-ID mismatch cost the operator > 30 minutes of diagnosis time that a Prometheus panel would have saved. Name the incident in the authorising ADR.
- **Learning-intake reframing** — operator wants hands-on time with Talos' resource model (`MachineStatus`, `EtcdMember`, `LinkStatus`) via a small exporter. Timebox 1 week, acceptance criterion is a single working CronJob + textfile-exporter path + one panel. Exit plan: remove if no real-world query lands on that panel within 30 days.
- **Sidero upstream change** — if a future Talos release ships a first-party Prometheus endpoint for machined / apid / trustd, this decision is obsolete and should be revisited regardless of need.

## Follow-ups

- [ ] **Phase 1 implementation** — rewrite `dashboard-cluster-health.yaml` into the top-down layout described in Decision §Phase 1. Single scoped commit, single PR, Flux auto-reconcile. Verify every panel renders against live Prometheus before declaring done.
- [ ] **Phase 1 verification** — walk the dashboard end-to-end with the operator; capture any panels that return `No data` and decide per-panel whether it's a scrape gap (move to Phase 2 candidate list) or a PromQL fix.
- [ ] **Sibling-board split trigger** — if any single collapsible row outgrows ~6 panels, or total panel count crosses ~20, split that row out into a dedicated dashboard (`cluster-network-glance`, `cluster-storage-glance`, etc.) and link from the glance board. Do not pre-split.
- [ ] **Phase 2 watch** — if any of the three named triggers above fires, open an ADR (or a Phase-2 PR referencing this one) that scopes: Talos machine-config patch + kube-prometheus-stack values flip + new Control-Plane-Internal row. Rolling apply via `talos-operator`.
- [ ] **Phase 3 watch** — if an incident matching the Re-adoption §Concrete-need conditions happens, name the incident and author the Phase-3 ADR. Do not pre-build the bridge.
- [ ] **Update `observability-integrate` skill memory** — after Phase 1 lands, note the established dashboard shape (header stats + collapsible rows, default-expanded top-2) so future workload integrations extend the same pattern instead of inventing their own.
