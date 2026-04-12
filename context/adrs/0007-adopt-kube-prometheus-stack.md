---
status: Accepted
date: 2026-04-12
deciders: ['@wcygan']
affects: observability
intent: concrete-need
supersedes: []
superseded-by: null
retrospective: false
---

# 0007 — Adopt kube-prometheus-stack as the metrics-only monitoring pick

> Anton adopts kube-prometheus-stack single-replica as a metrics-only stack on Longhorn PVCs; logs, traces, and long-term retention stay deferred behind named re-open triggers, and ADR 0006's SeaweedFS install trigger is explicitly left unfired.

## Status

Accepted

## Context

ADR 0003 deferred the monitoring stack with three candidates shortlisted — kube-prometheus-stack, victoria-metrics-k8s-stack, and Grafana LGTM — and named four re-open triggers. ADR 0006 then adopted SeaweedFS for object storage with **LGTM as the implicit concrete-need anchor**, gating SeaweedFS install on an LGTM successor to ADR 0003.

On 2026-04-12, a revisit of the monitoring question ran through a three-agent review (devils-advocate, cluster-intake-gatekeeper, independent web-research auditor) after practitioner feedback suggested pivoting to a VictoriaMetrics + VictoriaLogs shape. The review's converged finding:

- **The VM-stack pivot's rationale was partly wrong.** The Alloy → VictoriaLogs integration is documented and supported (via VL's Loki-protocol endpoint), not "untested." Tempo is smaller and younger than Jaeger, not broken. The "VM is 10× easier" claim is architectural inference, not a cited bake-off.
- **Governance matters more than the technical pick here.** Overturning ADR 0006's install trigger 48 hours after acceptance, on social-proof evidence, would undermine the ADR immutability discipline ADR 0001 explicitly set up.
- **The honest concrete-need is "weekly cluster-health dashboard + historical metrics when something breaks."** Logs and traces are genuinely deferrable; `kubectl logs` + `stern` / `k9s` covers Phase 0 log needs at homelab scale.
- **The smallest viable install that delivers this need is also the most Kubernetes-native.** kube-prometheus-stack owns the archetypal Kubernetes operator pattern: `ServiceMonitor` / `PodMonitor` / `PrometheusRule` are the de facto scrape-discovery standard, and every chart anton runs or plans to run (Cilium, cert-manager, envoy-gateway, external-dns, ESO, Longhorn, SeaweedFS-operator, Flux) ships ServiceMonitor out of the box. Any non-Prometheus-operator pick pays a recurring CRD-translation tax for no offsetting benefit at this scale.

This ADR takes ADR 0003's own **re-adoption trigger #4** — *"if the operator narrows the aspirational shape from full LGTM to 'metrics only', Candidates 1 and 2 are not gated by trigger #1 and could be re-evaluated immediately"* — as its authorising path. The aspirational shape has narrowed. Logs and traces remain welcome later, but only under explicit named triggers, never speculatively.

The cluster shape this ADR must fit: 3 Talos control-plane nodes, 16 GiB RAM each, 1 Gbit network, Longhorn block storage (ADR 0005) installing alongside this ADR's consumer. Monitoring RAM ceiling: ~8 GiB cluster-wide. kube-prometheus-stack in single-replica mode fits at ~3 GiB, leaving comfortable headroom for a future logs tier.

## Decision

Anton adopts **kube-prometheus-stack** as the metrics-only monitoring stack with the following shape:

- **Chart**: `prometheus-community/kube-prometheus-stack`, pinned to a specific v83.x patch at scaffold time (current upstream as of this ADR; re-verified at install).
- **Prometheus**: `replicas: 1`, retention `15d` (chart default), PVC `50Gi` on the `longhorn` StorageClass (2-replica per ADR 0005). Scrape discovery via `ServiceMonitor` and `PodMonitor` from every namespace.
- **Alertmanager**: `replicas: 1`, PVC `2Gi` on `longhorn`. **No routes configured at install** — alerts go nowhere until a real destination (Discord webhook, email, PagerDuty, etc.) is chosen. Stops the "alerts into the void" pattern.
- **Grafana**: `replicas: 1`, SQLite on PVC `5Gi` on `longhorn`. Admin password delivered via `ExternalSecret` from 1Password. Dashboards declared via the sidecar ConfigMap pattern — all dashboards GitOps'd, none added via the UI.
- **Blackbox Exporter**: enabled (bundled with the chart). Probes declared via `Probe` CRs when a blackbox target is named; none at install.
- **Node Exporter + kube-state-metrics**: enabled (chart defaults). DaemonSet + Deployment respectively.
- **Thanos sidecar / remote-write**: **not enabled**. This keeps the install fully self-contained on Longhorn and leaves ADR 0006's install trigger untouched.
- **Exposure**: `HTTPRoute` for Grafana on `envoy-internal` (not external). Prometheus and Alertmanager stay ClusterIP-only — no public exposure.
- **Upgrade discipline**: kube-prometheus-stack chart upgrades reviewed by `upgrade-auditor` before merge. Major version bumps (e.g., 83.x → 84.x) smoke-tested by redeploying in a scratch namespace first.

**ADR 0006 is explicitly decoupled, not superseded.** ADR 0006 stays `Accepted`; its install trigger (LGTM as S3 consumer) simply does not fire from this ADR. SeaweedFS waits for a different S3 consumer (backups, media stack, Mimir-as-long-term-retention, etc.) to arrive before it installs. None of ADR 0006's six documented supersession triggers have fired, so 0006 is not rewritten.

## Alternatives considered

### VictoriaMetrics k8s-stack (VMSingle) — deferred, not rejected

Architecturally lighter than kube-prometheus-stack (~600 MiB vs ~3 GiB), smaller surface area per service, better metrics compression. Genuinely strong on its technical merits.

**Why not picked today**: the VM operator ships parallel CRDs (`VMServiceScrape`, `VMPodScrape`, `VMRule`) rather than consuming `ServiceMonitor` directly. Every Flux chart anton runs ships ServiceMonitor; picking VM means either installing prometheus-operator CRDs alongside VM (defeating the "simpler" pitch) or hand-converting scrape resources forever. On a homelab that values small operational surface, the CRD-translation tax is a worse deal than kube-prometheus-stack's monolithic default. VM returns as a serious candidate later *if* long-term metrics retention becomes a real need — see Follow-ups.

### Grafana LGTM monolithic (the ADR 0006 anchor) — rejected for this ADR

Three-pillar coverage in one chart family, intended consumer for ADR 0006's SeaweedFS.

**Why not picked today**: logs and traces are not concrete-need today. Installing LGTM to "stay consistent with ADR 0006" is exactly the completionism pattern ADR 0001 set up the intake gate to catch — the storage decision is not supposed to drive the monitoring decision; the monitoring decision is supposed to drive the storage decision. Decoupling 0006 is the honest move. LGTM returns to the shortlist if logs-on-S3 later becomes the path (unlikely given the VictoriaLogs-on-Longhorn option).

### Do nothing — `metrics-server` + `k9s` + `kubectl top` — rejected

The stated need — "weekly cluster-health dashboard + historical metrics when something breaks" — is not satisfiable with live-only `kubectl top`. No trend data, no PVC saturation alerts, no reconcile-loop visibility. This was the ADR 0003 status quo, and it's sufficient for today but not for the stated concrete need.

### kube-prometheus-stack + Loki filesystem mode (add logs now) — rejected

Would install logs simultaneously with metrics, skipping the "wait for the trigger" discipline.

**Why not picked today**: there is no named incident where `kubectl logs` / `stern` failed the operator. Installing Loki before that sentence exists is the same pattern as installing LGTM before workloads existed — the #1 completionism regret from ADR 0001's graveyard. Logs return via a separate ADR 0008 if and when the trigger fires.

### Bare VMSingle (no operator) — rejected

Smallest possible metrics footprint but sacrifices every Kubernetes-native integration (no CRD-driven scrape discovery). Would require hand-maintaining scrape configs as ConfigMaps. Not a serious contender once "Kubernetes-native" is the decision axis.

## Consequences

### Accepted costs

- **One more chart in the Flux tree** — kube-prometheus-stack is a large chart bundling Prometheus, Alertmanager, Grafana, Node Exporter, kube-state-metrics, and Blackbox Exporter. Renovate PR stream picks up all of these; `upgrade-auditor` reviews major version bumps.
- **~3 GiB cluster-wide RAM committed to observability.** Under the 8 GiB ceiling. Leaves ~5 GiB headroom for a future logs tier (VictoriaLogs ~500 MiB + OTel Collector DaemonSet ~200 MiB ≈ 1 GiB) and future traces.
- **Prometheus is now a Tier-0 dependency.** A broken Prometheus = no cluster health visibility. Mitigation: Prometheus local TSDB is self-contained on Longhorn; no external service it depends on.
- **15-day retention ceiling.** Queries older than 15 days return nothing. Acceptable for "weekly glance"; becomes the trigger for long-term retention (Follow-up 3).
- **Alertmanager with no routes generates zero alerts.** Intentional — prevents phantom "alerting stack installed" confidence while no destination exists. Must revisit when a destination is chosen.
- **Grafana dashboards must be GitOps'd.** Dashboards created in the UI are not persisted across Grafana restarts unless the admin remembers to JSON-export them back to the repo. Documented as a scaffold-time reminder; future drift is the operator's responsibility.
- **No logs pillar.** `kubectl logs` / `stern` / `k9s` remains the answer to "what did app X do yesterday at 2pm" until Follow-up 1's trigger fires.
- **No traces pillar.** No answer to "why is this request slow across services" until Follow-up 2's trigger fires. Homelab-appropriate.
- **CRD footprint expands.** Prometheus-operator installs: `Prometheus`, `Alertmanager`, `ThanosRuler`, `ServiceMonitor`, `PodMonitor`, `Probe`, `PrometheusRule`, `AlertmanagerConfig`, `ScrapeConfig`, `PrometheusAgent`. Several are unused at install but ship with the chart.

### What this preserves

- **ADR 0006 intact.** SeaweedFS stays `Accepted` with its install trigger unfired. No supersession, no 48-hour-churn governance optics.
- **ADR 0005 install path unchanged.** Longhorn is this ADR's install trigger; ADR 0005's accepted-but-deferred install fires exactly as originally designed.
- **Anti-completionism discipline (ADR 0001).** Only the pillar with a real concrete-need is installed. Logs and traces stay behind named triggers.
- **Optionality for the three downstream pillars.** VictoriaLogs-vs-Loki and Jaeger-vs-Tempo decisions stay open for the moment they have to be made, with upstream status freshly verified at that time.
- **Kubernetes-native shape.** Every chart in anton that ships `ServiceMonitor` wires up automatically. No parallel-CRD tax, no hand-translated scrape configs.
- **The team-review learnings are durable.** The web-research auditor's correction (Alloy → VL is documented and supported), the devils-advocate's governance-theater flag, and the intake gate's unblock conditions are all reflected either in this decision or in Follow-ups 1–3.

## Follow-ups

This ADR's Follow-ups section is unusually load-bearing — it encodes the named re-open triggers that keep this decision honest over time. Each trigger, when fired, authorises a specific follow-up ADR.

- [ ] **Scaffold the kube-prometheus-stack Flux app** — hand off to `flux-app-author`. 3-file pattern under `kubernetes/apps/observability/kube-prometheus-stack/` (new namespace `observability` unless an existing one fits). Pin chart version at scaffold time, enable the sidecar ConfigMap pattern for dashboards, declare `HTTPRoute` for Grafana on `envoy-internal`, wire Grafana admin password from 1Password via `ExternalSecret`.
- [ ] **Longhorn install precedes this app.** ADR 0005's gate fires here: Longhorn + Talos image rebuild (iscsi-tools + util-linux-tools) must be green before the `longhorn` StorageClass is claimable. Dependency order: Talos image rebuild → Longhorn HelmRelease → kube-prometheus-stack HelmRelease.
- [ ] **Commit a "cluster health" dashboard to Git at install time** — the concrete-need anchor is literally "weekly cluster-health glance." Curate one dashboard showing node CPU/RAM, pod restarts, Flux reconcile state, PVC saturation, and Longhorn replica health. Without this, the install has no named consumer delivering the concrete need.
- [ ] **Post-install smoke test**: verify Prometheus scrapes kube-apiserver, kubelet, kube-state-metrics, node-exporter, Cilium, Flux; verify Grafana loads the committed dashboard; verify Alertmanager reconciles (even with zero routes); capture baseline RAM/CPU footprint in `docs/`.
- [ ] **Trigger 1 — Logs**: *"I tried to grep logs across pods or namespaces over a ≥24h window to answer a real operational question and could not."* When this sentence happens, write **ADR 0008** selecting an OpenTelemetry-Collector-based logs pipeline with a VictoriaLogs or Loki backend. Alloy → VictoriaLogs is documented and supported (VL's Loki-protocol endpoint) — `upgrade-auditor` should re-verify at that time.
- [ ] **Trigger 2 — Traces**: *"A workload arrives already emitting OTLP AND a diagnostic question exists that logs+metrics cannot answer."* When both halves hold, write an ADR selecting a trace backend. Current shortlist ranking (subject to re-verification): Jaeger (CNCF-graduated, Badger single-node mode, native Grafana data source) > Tempo > ClickHouse-based (SigNoz, etc.). Not installing a trace backend before a workload emits OTLP is a hard rule.
- [ ] **Trigger 3 — Long-term metrics retention**: *"I want to answer a question about cluster state older than 15 days and cannot."* When this fires, write an ADR selecting a long-term sink. Current shortlist ranking (subject to re-verification): VictoriaMetrics single-node as remote-write sink (no S3, lightest) > Grafana Mimir on SeaweedFS (finally fires ADR 0006's install trigger) > Thanos sidecar on SeaweedFS. The VictoriaMetrics-for-metrics case returns here on its own merits, not as an upfront stack swap.
- [ ] **Trigger 4 — Alertmanager routing**: when the operator decides which destination alerts should flow to (Discord, email, PagerDuty, ntfy, etc.), add routes via `AlertmanagerConfig` CRs. Delivered by the existing chart; no new ADR needed unless the destination adds a Tier-0 dependency.
- [ ] **Revisit schedule**: review this ADR's Follow-ups every ~90 days to decide whether any triggers have quietly fired without being acknowledged. If three months pass with zero triggers fired, the install is honest; if Follow-up 1 fires two months in but nobody writes ADR 0008 for a month afterward, that's the governance model failing.
- [ ] **Update `.claude/agent-memory/cluster-intake-gatekeeper/`** with the monitoring narrative so future intake rounds see the narrowing-shape reframing and don't re-litigate the VM-vs-LGTM debate from scratch.
