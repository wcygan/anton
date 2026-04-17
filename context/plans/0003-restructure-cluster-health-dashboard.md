---
status: In-progress
opened: 2026-04-17
closed: null
affects: observability
intent: concrete-need
related-adrs: [0007, 0012, 0013]
review-by: 2026-05-01
---

# 0003 — Restructure the cluster-health Grafana dashboard top-down (ADR 0013 Phase 1)

> Execute ADR 0013 §Phase 1 — rewrite `dashboard-cluster-health.yaml` into a progressive-disclosure layout (header stats → collapsible subsystem rows), extend from 7 panels to 16–20, and walk every new panel against live Prometheus until each one either renders or is documented as a scrape gap feeding ADR 0013 Phase 2.

## Goal

Turn the existing seven-panel `cluster-health-glance` dashboard into the one-scroll glance surface ADR 0013 describes: five always-visible stat panels at the top (Nodes Ready, Pods by phase, Flux ready %, API-server 5xx rate, cert-manager expiries < 14d), six collapsible subsystem rows below (Cluster Capacity, Control Plane RED, Nodes USE, Workloads, Storage, Network & CNI), top-two rows default-expanded. The `uid: cluster-health-glance` is preserved so existing bookmarks keep working. All authoring stays in-repo — no UI edits, no new scrape config, no cluster-config changes (Phase 2 stays deferred). Done when the operator can open `https://grafana.<tailnet-name>.ts.net/d/cluster-health-glance`, scroll top-to-bottom, and see a populated answer to "is the cluster ok right now" at the top and progressively deeper subsystem context below.

## Acceptance criteria

- [ ] `dashboard-cluster-health.yaml` ConfigMap reconciled by Flux; Grafana sidecar has reloaded the new JSON; dashboard renders at the same UID.
- [ ] 16–20 panels live; layout matches ADR 0013 §Phase 1 spec (header strip visible on load, `Cluster Capacity` + `Control Plane (RED)` rows default-expanded, others default-collapsed).
- [ ] Every new panel either renders non-empty data against live Prometheus OR is documented in the Log as a known scrape gap with its ADR 0013 Phase-2 trigger mapping.
- [ ] Operator has walked the board end-to-end on the tailnet URL; any `No data` panels resolved (PromQL fix) or logged (scrape gap).
- [ ] `observability-integrate` skill memory updated with the established shape (header stats + collapsible rows, top-2 default-expanded) so future workload integrations extend the same pattern.

## Tasks

### Phase 1a: Author the JSON

- [ ] Draft the new dashboard JSON in-place in `kubernetes/apps/observability/kube-prometheus-stack/app/dashboard-cluster-health.yaml`. Preserve `uid`, `tags`, `time`, `refresh`, `timezone`. Bump `schemaVersion` only if a new panel type requires it.
- [ ] Add the **header stat strip** (row `y: 0`, `h: 4`, five panels across `w: 24`):
  - Nodes Ready — `sum(kube_node_status_condition{condition="Ready",status="true"})` with mapping/thresholds to show denominator.
  - Pods by phase — `sum by (phase)(kube_pod_status_phase)` as a single stat panel with colored thresholds on non-Running totals.
  - Flux Kustomizations ready % — reuse the `flux_resource_info{ready="True"}` vector the existing Panel 5 uses; compute `count(…ready="True") / count(…)`.
  - API-server 5xx rate (5m) — `sum(rate(apiserver_request_total{code=~"5.."}[5m])) / sum(rate(apiserver_request_total[5m]))` as percent, threshold red at 1 %.
  - Cert-manager certs expiring < 14 d — `count(certmanager_certificate_expiration_timestamp_seconds - time() < 14*86400)` (verify cert-manager ServiceMonitor is scraped; if not, drop this panel with a scrape-gap log entry).
- [ ] Convert existing seven panels into **collapsible rows** using Grafana `type: row` panels with `collapsed: false|true` per ADR 0013 spec.
- [ ] **Cluster Capacity row (default expanded)** — existing Panels 1/2/3 (node CPU, memory, filesystem) + two new panels:
  - Cluster CPU commit ratio — `sum(kube_pod_container_resource_requests{resource="cpu"}) / sum(kube_node_status_allocatable{resource="cpu"})`.
  - Cluster memory commit ratio — same with `resource="memory"`.
- [ ] **Control Plane (RED) row (default expanded)** — three new panels, data available today:
  - API-server QPS by verb — `sum by (verb)(rate(apiserver_request_total[5m]))`.
  - API-server p99 latency — `histogram_quantile(0.99, sum by (le,verb)(rate(apiserver_request_duration_seconds_bucket[5m])))`.
  - API-server error rate (promote from stat strip to timeseries for trend) — same PromQL as header stat.
- [ ] **Nodes (USE) row (default collapsed)** — two new panels:
  - Pressure conditions — `kube_node_status_condition{condition=~"MemoryPressure|DiskPressure|PIDPressure",status="true"}` as a table or state-timeline.
  - Per-node network Rx/Tx — `rate(node_network_receive_bytes_total{device!~"lo|cali.*|cilium.*|lxc.*|veth.*"}[5m])`, `rate(node_network_transmit_bytes_total{…}[5m])`. On anton's SFP+ mesh (ADR 0009) this is where bonded-interface throughput shows up.
- [ ] **Workloads row (default collapsed)** — existing pod-restarts panel + two new panels:
  - Pending pods over time — `sum(kube_pod_status_phase{phase="Pending"}) by (namespace)`.
  - OOMKilled rate (1h) — `increase(kube_pod_container_status_terminated_reason{reason="OOMKilled"}[1h])` as a table.
- [ ] **Storage row (default collapsed)** — existing PVC saturation + Longhorn robustness panels + one new panel:
  - Longhorn replica count per volume — `longhorn_volume_actual_size_bytes` joined with replica count via `count(longhorn_volume_robustness) by (volume)` (validate PromQL shape when wiring).
- [ ] **Network & CNI row (default collapsed)** — three new panels:
  - CoreDNS QPS — `sum(rate(coredns_dns_requests_total[5m]))`.
  - CoreDNS non-NOERROR response rate — `sum(rate(coredns_dns_responses_total{rcode!="NOERROR"}[5m]))`.
  - Cilium/Hubble flow rate — `sum(rate(hubble_flows_processed_total[5m]))` (confirm metric name against live Prometheus before committing).

### Phase 1b: Validate and land

- [ ] Run `conventions-linter` subagent against the edited ConfigMap before commit; confirm no `grafana_dashboard` label drift.
- [ ] Run `task configure` to re-render + validate; no SOPS churn expected (ConfigMap is plaintext).
- [ ] `jj commit` as a single scoped change ("kube-prometheus-stack: restructure cluster-health dashboard top-down (ADR 0013 Phase 1)"); `jj git push --bookmark main`.
- [ ] Verify Flux reconciles the HelmRelease-adjacent ConfigMap — `flux get ks -A` shows green; `kubectl -n observability get configmap dashboard-cluster-health-glance -o jsonpath='{.data}' | head` confirms new JSON is live.
- [ ] Wait for Grafana sidecar reload (sidecar polls ConfigMaps; default ~30 s). Confirm by hitting the dashboard UID and visually checking the new layout.

### Phase 1c: Walk and fix

- [ ] Walk the board end-to-end at `https://grafana.<tailnet-name>.ts.net/d/cluster-health-glance` — header strip first, then each row expanded in turn.
- [ ] Capture every `No data` panel into the Log with the PromQL + hypothesised cause (metric missing, relabeling stripped the label, time window too short, etc.).
- [ ] For each `No data`: either fix the PromQL and push a follow-up commit, OR mark the panel as a scrape-gap driver for ADR 0013 Phase 2 (name which of the three Phase-2 triggers it feeds).
- [ ] Close the loop with the operator — confirm the new shape actually answers "is the cluster ok" at a glance.

### Phase 1d: Propagate the pattern

- [ ] Update `.claude/skills/observability-integrate/` (or its skill-memory folder under `.claude/agent-memory/` if that's the convention) with a reference to the established dashboard shape: header stats + collapsible subsystem rows, top-2 default-expanded, `uid`-stable for URL continuity. Future per-workload dashboards extend this pattern instead of inventing their own.

## Log

- 2026-04-17: Plan opened — ADR 0013 accepted same day, authorising Phase 1 execution. Grafana is freshly reachable at `https://grafana.<tailnet-name>.ts.net/` (ADR 0012 validation landed this morning), so the rewrite has a real consumer surface. Phase 2 (enable Talos control-plane scrapes) and Phase 3 (Talos OS textfile bridge) are explicitly NOT in scope for this plan — they live as named triggers on ADR 0013 and will get their own plans if/when they fire.

## References

- Driving ADR: **0013** — restructure cluster-health dashboard (authoritative spec for Phase 1 layout, Phase 2 trigger conditions, Phase 3 rejection rationale).
- Upstream dependencies: **0007** (kps install — this plan extends its Follow-up 3), **0012** (Tailscale Grafana Ingress — made the dashboard a tailnet surface worth polishing).
- Target file: `kubernetes/apps/observability/kube-prometheus-stack/app/dashboard-cluster-health.yaml`.
- Flux reconciliation check: `flux get ks -A | rg observability` + `kubectl -n observability get configmap dashboard-cluster-health-glance`.
- Grafana UID: `cluster-health-glance` (preserved across rewrite).
- Research report sources for Phase 1 PromQL: dotdc grafana-dashboards-kubernetes (#15757/15759/15761/15762), kubernetes-mixin, Grafana #1860 Node Exporter Full, Grafana #315.
- Subagent handoffs: `conventions-linter` (pre-commit check), optional `observability-integrate` (if a new PrometheusRule or ServiceMonitor turns out to be needed during Phase 1c).
- Not in scope: ADR 0013 Phase 2 (Talos controlplane patch — requires `talos-operator`), Phase 3 (textfile bridge — rejected).
