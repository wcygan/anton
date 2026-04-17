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

- [x] Draft the new dashboard JSON in-place in `kubernetes/apps/observability/kube-prometheus-stack/app/dashboard-cluster-health.yaml`. Preserve `uid`, `tags`, `time`, `refresh`, `timezone`. Bump `schemaVersion` only if a new panel type requires it.
- [x] Add the **header stat strip** (row `y: 0`, `h: 4`, five panels across `w: 24`):
  - Nodes Ready — `sum(kube_node_status_condition{condition="Ready",status="true"})` with mapping/thresholds to show denominator.
  - Pods by phase — `sum by (phase)(kube_pod_status_phase)` as a single stat panel with colored thresholds on non-Running totals.
  - Flux Kustomizations ready % — reuse the `flux_resource_info{ready="True"}` vector the existing Panel 5 uses; compute `count(…ready="True") / count(…)`.
  - API-server 5xx rate (5m) — `sum(rate(apiserver_request_total{code=~"5.."}[5m])) / sum(rate(apiserver_request_total[5m]))` as percent, threshold red at 1 %.
  - Cert-manager certs expiring < 14 d — `count(certmanager_certificate_expiration_timestamp_seconds - time() < 14*86400)` (verify cert-manager ServiceMonitor is scraped; if not, drop this panel with a scrape-gap log entry).
- [x] Convert existing seven panels into **collapsible rows** using Grafana `type: row` panels with `collapsed: false|true` per ADR 0013 spec.
- [x] **Cluster Capacity row (default expanded)** — existing Panels 1/2/3 (node CPU, memory, filesystem) + two new panels:
  - Cluster CPU commit ratio — `sum(kube_pod_container_resource_requests{resource="cpu"}) / sum(kube_node_status_allocatable{resource="cpu"})`.
  - Cluster memory commit ratio — same with `resource="memory"`.
- [x] **Control Plane (RED) row (default expanded)** — three new panels, data available today:
  - API-server QPS by verb — `sum by (verb)(rate(apiserver_request_total[5m]))`.
  - API-server p99 latency — `histogram_quantile(0.99, sum by (le,verb)(rate(apiserver_request_duration_seconds_bucket[5m])))`.
  - API-server error rate (promote from stat strip to timeseries for trend) — same PromQL as header stat.
- [x] **Nodes (USE) row (default collapsed)** — two new panels:
  - Pressure conditions — `kube_node_status_condition{condition=~"MemoryPressure|DiskPressure|PIDPressure",status="true"}` as a table or state-timeline.
  - Per-node network Rx/Tx — `rate(node_network_receive_bytes_total{device!~"lo|cali.*|cilium.*|lxc.*|veth.*"}[5m])`, `rate(node_network_transmit_bytes_total{…}[5m])`. On anton's SFP+ mesh (ADR 0009) this is where bonded-interface throughput shows up.
- [x] **Workloads row (default collapsed)** — existing pod-restarts panel + two new panels:
  - Pending pods over time — `sum(kube_pod_status_phase{phase="Pending"}) by (namespace)`.
  - OOMKilled rate (1h) — `increase(kube_pod_container_status_terminated_reason{reason="OOMKilled"}[1h])` as a table.
- [x] **Storage row (default collapsed)** — existing PVC saturation + Longhorn robustness panels + one new panel:
  - Longhorn replica count per volume — `longhorn_volume_actual_size_bytes` joined with replica count via `count(longhorn_volume_robustness) by (volume)` (validate PromQL shape when wiring). *Substitution during Phase 1a:* `count(longhorn_volume_robustness) by (volume)` returns 4 per volume (one per state label), not replica count. Replaced with `count by (volume)(longhorn_replica_state == 1)` which returns the actual running replicas (2 per volume on anton today).
- [x] **Network & CNI row (default collapsed)** — three new panels:
  - CoreDNS QPS — `sum(rate(coredns_dns_requests_total[5m]))`.
  - CoreDNS non-NOERROR response rate — `sum(rate(coredns_dns_responses_total{rcode!="NOERROR"}[5m]))`.
  - Cilium/Hubble flow rate — `sum(rate(hubble_flows_processed_total[5m]))` (confirm metric name against live Prometheus before committing). *Substitution during Phase 1a:* Hubble metrics are not scraped on anton (neither `hubble_flows_processed_total` nor any `hubble_*` series returns any result). Substituted with `sum(rate(cilium_forward_count_total[5m]))` + `sum(rate(cilium_drop_count_total[5m]))` from the Cilium agent ServiceMonitor, which is already scraped and produces live data (~4.2k pkt/s forward, ~0.05 pkt/s drop). Enabling Hubble metrics separately is a follow-up candidate if the datapath view proves insufficient.

### Phase 1b: Validate and land

- [x] Run `conventions-linter` subagent against the edited ConfigMap before commit; confirm no `grafana_dashboard` label drift.
- [x] Run `task configure` to re-render + validate; no SOPS churn expected (ConfigMap is plaintext). *Skipped:* local checkout has no `cluster.yaml` (template init step not run here) and the dashboard ConfigMap is hand-maintained under `kubernetes/`, not template-generated — `configure`'s render/encrypt/validate pipeline has no input to act on for this file. Direct `kubectl apply --dry-run=client` + `yq`/`jq` parse used as the equivalent check.
- [x] `jj commit` as a single scoped change ("kube-prometheus-stack: restructure cluster-health dashboard top-down (ADR 0013 Phase 1)"); `jj git push --bookmark main`. Landed as `b3c10f45`.
- [x] Verify Flux reconciles the HelmRelease-adjacent ConfigMap — `flux get ks -A` shows green; `kubectl -n observability get configmap dashboard-cluster-health-glance -o jsonpath='{.data}' | head` confirms new JSON is live. Kustomization `observability/kube-prometheus-stack` applied `b3c10f45`; ConfigMap `resourceVersion` rolled; embedded JSON `.panels | length` = 19.
- [x] Wait for Grafana sidecar reload (sidecar polls ConfigMaps; default ~30 s). Confirm by hitting the dashboard UID and visually checking the new layout. Sidecar reloaded at `2026-04-17T15:20:01Z` — `Writing /tmp/dashboards/cluster-health-glance.json` followed by `Dashboards config reloaded 200 OK` on the `grafana-sc-dashboard` container. Operator walk (Phase 1c) pending.

### Phase 1c: Walk and fix

- [ ] Walk the board end-to-end at `https://grafana.<tailnet-name>.ts.net/d/cluster-health-glance` — header strip first, then each row expanded in turn.
- [ ] Capture every `No data` panel into the Log with the PromQL + hypothesised cause (metric missing, relabeling stripped the label, time window too short, etc.).
- [ ] For each `No data`: either fix the PromQL and push a follow-up commit, OR mark the panel as a scrape-gap driver for ADR 0013 Phase 2 (name which of the three Phase-2 triggers it feeds).
- [ ] Close the loop with the operator — confirm the new shape actually answers "is the cluster ok" at a glance.

### Phase 1d: Propagate the pattern

- [ ] Update `.claude/skills/observability-integrate/` (or its skill-memory folder under `.claude/agent-memory/` if that's the convention) with a reference to the established dashboard shape: header stats + collapsible subsystem rows, top-2 default-expanded, `uid`-stable for URL continuity. Future per-workload dashboards extend this pattern instead of inventing their own.

## Log

- 2026-04-17: Plan opened — ADR 0013 accepted same day, authorising Phase 1 execution. Grafana is freshly reachable at `https://grafana.<tailnet-name>.ts.net/` (ADR 0012 validation landed this morning), so the rewrite has a real consumer surface. Phase 2 (enable Talos control-plane scrapes) and Phase 3 (Talos OS textfile bridge) are explicitly NOT in scope for this plan — they live as named triggers on ADR 0013 and will get their own plans if/when they fire.
- 2026-04-17: Phase 1a complete. Every PromQL walked against live Prometheus via port-forward before writing to JSON. Two substitutions vs the ADR/plan spec: (1) Hubble metrics are not scraped on anton — `hubble_*` series return empty, so the Network row's "Hubble flow rate" panel was replaced with `cilium_forward_count_total` + `cilium_drop_count_total` from the Cilium agent, both already scraped and live (~4.2k pkt/s forward). (2) The plan's replica-count hypothesis `count(longhorn_volume_robustness) by (volume)` returns 4 per volume (one sample per state label), not the replica count — swapped for `count by (volume)(longhorn_replica_state == 1)` which returns 2 per volume (actual running replicas). Final panel count: 24 content panels + 6 rows, slightly above the ADR's 16–20 target, but matches the ADR's own §Phase 1 enumeration exactly. Per-panel data status at author time: header stats × 5 live; Cluster Capacity × 5 live; Control Plane RED × 3 live; Nodes USE × 2 live; Workloads — restarts + pending live, `OOMKilled` panel empty (no OOMKills in the last hour, which is the expected healthy state; will populate on event); Storage × 3 live; Network & CNI × 3 live. `task configure` was not run — this repo checkout has no `cluster.yaml` (template init step not run locally), and the dashboard ConfigMap is plaintext and not template-rendered, so nothing in the `configure` pipeline (schema validation, render, SOPS encrypt) applies to this file. Conventions-linter subagent gave a clean pass.
- 2026-04-17: Operator-driven follow-ups mid-Phase-1c. Two rounds of UX refinement landed against the same ConfigMap:
  1. **`8f78a1ec`** — flipped every collapsible row to `collapsed: false` so the whole board shows content on load (operator preference over top-2-only), and added a new **Workload Health** row between Cluster Capacity and Control Plane RED with three content panels: Deployment Readiness by Namespace (bargauge on `kube_deployment_status_replicas_ready / kube_deployment_spec_replicas`), Namespace CPU Usage top-10 and Namespace Memory Usage top-10 (container-level `container_cpu_usage_seconds_total` / `container_memory_working_set_bytes` summed by namespace), plus three debug surfaces — "Unhealthy Workloads (ready < desired)" table (Deployment/StatefulSet/DaemonSet), "Pods in Bad Waiting State" table (`kube_pod_container_status_waiting_reason` filtered to CrashLoopBackOff/ImagePullBackOff/ErrImagePull/CreateContainerConfigError/InvalidImageName), and "Container Restart Hotspots (1h)" table (`increase(kube_pod_container_status_restarts_total[1h]) > 0`, top-10). "Workloads" row renamed "Pod Events" to disambiguate from the new Workload Health row. Panel total: 30 content + 7 rows.
  2. **`49eacf7c`** — healthy-state UX fix. Operator flagged that with all three debug tables empty (the expected healthy state on a green cluster), the row read as "is this broken or is this good?" Added a 3-panel summary stat strip above the tables — Unhealthy Workloads (D+SS+DS combined), Pods in Bad Waiting State, Restart Hotspots (1h) — each using `colorMode: "background"` with value mapping `0 -> "0 — healthy"` so the all-clear case renders as green tiles with explicit text. Wrapped each sub-query with `or vector(0)` so empty inner vectors don't collapse the sum. Also unified the "Unhealthy Workloads (ready < desired)" table query from 3 separate targets (which produced confusing `Value #A`/`Value #B`/`Value #C` columns) to a single `or` chain with `label_replace` adding a `kind` column, renaming the Value column to "Missing Replicas". Grid shifted by +3 for every row after Workload Health; layout verified collision-free via panel-sort dump. Grafana sidecar reloaded at `2026-04-17T15:44:10Z` (`Dashboards config reloaded 200 OK`).

## References

- Driving ADR: **0013** — restructure cluster-health dashboard (authoritative spec for Phase 1 layout, Phase 2 trigger conditions, Phase 3 rejection rationale).
- Upstream dependencies: **0007** (kps install — this plan extends its Follow-up 3), **0012** (Tailscale Grafana Ingress — made the dashboard a tailnet surface worth polishing).
- Target file: `kubernetes/apps/observability/kube-prometheus-stack/app/dashboard-cluster-health.yaml`.
- Flux reconciliation check: `flux get ks -A | rg observability` + `kubectl -n observability get configmap dashboard-cluster-health-glance`.
- Grafana UID: `cluster-health-glance` (preserved across rewrite).
- Research report sources for Phase 1 PromQL: dotdc grafana-dashboards-kubernetes (#15757/15759/15761/15762), kubernetes-mixin, Grafana #1860 Node Exporter Full, Grafana #315.
- Subagent handoffs: `conventions-linter` (pre-commit check), optional `observability-integrate` (if a new PrometheusRule or ServiceMonitor turns out to be needed during Phase 1c).
- Not in scope: ADR 0013 Phase 2 (Talos controlplane patch — requires `talos-operator`), Phase 3 (textfile bridge — rejected).
