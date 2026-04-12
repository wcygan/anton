---
status: Deferred
date: 2026-04-12
deciders: ['@wcygan']
affects: observability
intent: concrete-need
supersedes: []
superseded-by: null
retrospective: false
---

# 0008 — OpenTelemetry-based logs and traces roadmap

> Deferred roadmap: when ADR 0007's Trigger 1 or 2 fires, anton will adopt OpenTelemetry Collector via otel-operator as the Kubernetes-native collector foundation, with VictoriaLogs (logs) and Jaeger (traces) as the current shortlist frontrunners — selected per-pillar when its trigger fires, never speculatively.

## Status

Deferred

## Context

ADR 0007 adopted kube-prometheus-stack as a metrics-only monitoring stack and parked two downstream pillars behind named re-open triggers:

- **Trigger 1 (logs)**: *"I tried to grep logs across pods or namespaces over a ≥24h window to answer a real operational question and could not."*
- **Trigger 2 (traces)**: *"A workload arrives already emitting OTLP AND a diagnostic question exists that logs+metrics cannot answer."*

Those triggers exist precisely because logs and traces are genuinely likely to become real needs — not hypothetical completionism. The #1 lesson from ADR 0001's removal graveyard is *"every real cluster has X"* produced regret; the lesson from this revisit cycle (see ADR 0007's Context) is that *"every real cluster will eventually need logs"* has to be answered with "yes, *when* it does, and here's the plan." That plan is this ADR.

This ADR does not install anything. It records the architectural choices that will be made when either trigger fires, so that the successor ADRs don't re-litigate the collector decision from scratch and so future-self understands why logs-via-OpenTelemetry was already decided while the backend choice stays open.

Three forces shape this roadmap:

1. **Kubernetes-nativeness as a decision axis** (carried forward from ADR 0007). The canonical CNCF-graduated answer for collector infrastructure is OpenTelemetry. Its operator ships `OpenTelemetryCollector` and `Instrumentation` CRDs that are the logs/traces equivalent of Prometheus-operator's `ServiceMonitor` — the de facto Kubernetes-native shape. Alloy (Grafana), Vector (datadog-adjacent ownership), and Fluent Bit (CNCF-graduated but ConfigMap-driven, not CRD-driven) all trade off against this axis.
2. **Backend-swappability as a hedge.** The homelab should not bet on a specific logs backend today. VictoriaLogs is the current architectural frontrunner (single-binary, PVC-native, no S3, Alloy/OTel ingestion documented); Loki is the LGTM-suite fit but re-activates ADR 0006's install trigger at scale; SigNoz and OpenObserve exist but carry ClickHouse or early-stage risk respectively. Picking OpenTelemetry Collector as the *collector* layer means the backend can be swapped later with a config change, not a reinstall.
3. **One collector covers logs and traces.** OTel Collector receives OTLP natively and scrapes pod stdout/stderr via the `filelog` receiver. Installing it for logs positions traces to land with no additional collector infrastructure — only a new backend pod and a new Grafana data source. That matters because it means Trigger 1 and Trigger 2 share the same collector ADR spine.

Upstream status (2026-04-12, to be re-verified at install):

- `open-telemetry/opentelemetry-collector` — CNCF graduated (Feb 2024), active; core receivers/exporters stable.
- `open-telemetry/opentelemetry-operator` — CNCF project; ships `OpenTelemetryCollector`, `Instrumentation`, `OpAMPBridge` CRDs. Active Renovate cadence.
- `VictoriaMetrics/VictoriaLogs` — separate repo since 2025-07-06, ~weekly releases, v1.49.0 on 2026-04-03. Alloy and OTel ingestion both documented (Loki-protocol endpoint + OTLP endpoint).
- `jaegertracing/jaeger` — CNCF graduated. v2.17.0 on 2026-03-30. Storage backends include Badger (single-node), Cassandra, ES/OpenSearch, ClickHouse. Native Grafana data source. Jaeger v2 storage is in transition — Badger's role shifts in v2; re-verify single-node backend at install.
- `grafana/tempo` — not CNCF, smaller community than Jaeger, active. LGTM-suite fit; weaker on maturity than Jaeger.

## Decision

This ADR commits to a **single architectural spine** for future logs and traces pillars:

### Collector layer — decided in advance

- **Pick**: OpenTelemetry Collector deployed via `opentelemetry-operator`.
- **Why decided now**: this is the Kubernetes-native answer (CRD-driven, CNCF-graduated), vendor-neutral, and shared across both pillars. Picking it today removes a decision that would otherwise be re-argued in both ADRs 0009 and 0010. Installation itself still happens when Trigger 1 fires — not today.
- **Install shape when Trigger 1 fires**:
  - `opentelemetry-operator` Helm chart → installs CRDs + operator Deployment.
  - One `OpenTelemetryCollector` CR in `DaemonSet` mode with the `filelog` receiver for node-level pod log tailing.
  - Optionally a second `OpenTelemetryCollector` CR in `Deployment` mode as a gateway collector for batching/export — added only if the DaemonSet's direct-export shape produces unacceptable backend load.
  - OTLP HTTP + gRPC receivers enabled on the gateway from day one, so a future traces-emitting workload can target the same collector without a re-scaffold.

### Logs backend — shortlisted, selected at Trigger 1 install time

Re-verify upstream status at install time and pick:

| Backend | Architectural fit | S3 dep | ADR 0006 effect | Current ranking |
|---|---|---|---|---|
| **VictoriaLogs** | Single binary on Longhorn PVC; OTel-native exporter + Loki-protocol endpoint both documented | No | **None** — 0006 install trigger stays unfired | **Frontrunner** |
| Loki single-binary | Grafana-vendor-coherent; filesystem mode supported but discouraged at scale | Optional (filesystem for small, S3 for production) | Fires 0006 if S3 mode chosen | Runner-up |
| OpenObserve | Single binary, OTLP-native, very light | No | None | Worth re-verifying at install; currently "early-stage" flagged |
| SigNoz | OTLP-native, full UI | Yes (ClickHouse as Tier-0 dep) | None (but adds a new Tier-0) | Rejected — ClickHouse is too heavy |

**The frontrunner picked at install time will be the one whose upstream status is healthiest at that moment** — this ADR does not lock VictoriaLogs in, it only marks it as the current best fit. Install paperwork (ADR 0009) re-verifies.

### Traces backend — shortlisted, selected at Trigger 2 install time

Deferred further than logs because Trigger 2 has two halves (workload emits OTLP *and* diagnostic need exists) — in practice the trace backend decision happens significantly after the logs one.

| Backend | Architectural fit | Storage | Grafana data source | Current ranking |
|---|---|---|---|---|
| **Jaeger** | CNCF graduated, v2.17+; OTLP-native; multiple storage backends | Badger (single-node), Cassandra, ES/OpenSearch, ClickHouse | Native, official | **Frontrunner** |
| Tempo | LGTM-suite coherent; younger, smaller community | Object storage (would fire ADR 0006) or filesystem | Native, official | Runner-up; only picked if logs already chose Loki |
| SigNoz (traces path) | OTLP-native, full UI | ClickHouse | No (its own UI) | Rejected — ClickHouse tax + abandons Grafana-as-front-door |

Jaeger's backend choice at Trigger 2 time will likely be Badger (single-node, simplest) unless Jaeger v2's storage migration has made Badger second-class by then — re-verify at install.

## Alternatives considered

### Pick OpenTelemetry Collector now and install it — rejected

Would scaffold the collector today, no backend, as "infrastructure ready for the pillar that's coming." Attractive because it removes a future install step.

**Why rejected**: installing a collector with no backend is exactly the anti-pattern ADR 0001 warns about — components pre-positioned for workloads that may never materialise. If Trigger 1 never fires, the collector is a pure cost. The discipline is *"name the trigger, wait for it."* This ADR does decide the collector so the waiting is fast, but the install itself waits for real operational need.

### Commit to Grafana Alloy instead — rejected

Alloy is operationally mature, has first-class VictoriaLogs ingestion via Loki protocol, ships with kube-prometheus-stack's implicit vendor family, and has its own operator.

**Why rejected**: Alloy is a Grafana-vendor-specific collector. It ships `alloy-operator` CRDs that are not the broader-ecosystem standard. OpenTelemetry Collector is vendor-neutral, CNCF-graduated, and matches the *"ServiceMonitor-as-de-facto-standard"* reasoning from ADR 0007 one layer up. If a future decision needs to swap backends, OTel Collector makes that a config change; Alloy makes it a collector re-scaffold. Alloy returns as a fallback if otel-operator upstream stalls.

### Vector or Fluent Bit — rejected as the primary collector

Both are mature, lightweight, widely deployed. Fluent Bit is CNCF-graduated.

**Why rejected**: both are ConfigMap-driven rather than CRD-driven. That's a meaningful step down from the Kubernetes-native axis ADR 0007 committed to. Either remains a legitimate "escape hatch" collector for specific use cases (node-level kernel log tailing, high-throughput shipping to a non-OTLP backend), but not the primary choice.

### Commit to a specific logs or traces backend now — rejected

Would pre-decide VictoriaLogs and Jaeger in this ADR rather than ranking them.

**Why rejected**: upstream status decays. Garage's row in ADR 0004 was already factually wrong two months later (see ADR 0006's retraction). VictoriaLogs is on ~weekly releases; Jaeger v2 storage is in transition. The honest move is to name the current shortlist with today's ranking and re-verify at install — which is exactly what ADR 0004's Object-category framework did for SeaweedFS/Garage/MinIO, and which is a pattern anton now has evidence of as the right shape for forward-looking decisions.

### Adopt a unified "all-in-one" observability platform (SigNoz / OpenObserve) — rejected

SigNoz delivers metrics + logs + traces in one chart family. OpenObserve does similar.

**Why rejected at roadmap time**: anton has already committed to Prometheus for metrics (ADR 0007) via the most-K8s-native path available. Replacing that with a SigNoz/OpenObserve-as-everything stack would supersede ADR 0007 immediately, churn that ADR 0007's existence is meant to prevent. Adding SigNoz alongside Prometheus creates two metrics stores, which is worse than either alone. These platforms remain candidates *only* in the scenario where anton hits a scaling wall on Prometheus (extremely unlikely at homelab scale) — at which point a separate ADR would justify the swap.

### Skip this roadmap ADR entirely, decide only when Trigger 1 fires — rejected

ADR 0007 already names Trigger 1 and hints at the OTel path; one could argue this ADR is redundant.

**Why rejected**: writing the collector decision down now has two benefits: (1) future-self doesn't re-research "Alloy vs OTel Collector vs Vector" when Trigger 1 fires — that decision is already made and the install ADR can focus on backend selection; (2) the shortlist survey for both logs and traces backends gets captured in one document while the research is fresh, matching ADR 0004's pattern of framework-first, per-category-successor second. The failure mode ADR 0004 fought — decaying shortlists — is mitigated here by explicit re-verification clauses.

## Consequences

### Accepted costs

- **The collector decision is now load-bearing.** If otel-operator upstream stalls, regresses, or the CNCF project shape changes meaningfully, this ADR needs a successor. Mitigation: the install-time re-verification clause and the Alloy fallback.
- **Backend shortlists will decay.** VictoriaLogs ranking today may shift by the time Trigger 1 fires; Jaeger's Badger backend may change position in v2. Re-verification at install is the only protection — treat the rankings here as "current guidance," not "final answer."
- **Keeping this ADR alive requires operational discipline.** If Trigger 1 fires and the ADR is forgotten, the install can regress to ad-hoc collector + backend choice. Mitigation: ADR 0007's Follow-up 1 explicitly points to this ADR; the cluster-intake-gatekeeper should surface 0008 whenever a monitoring-adjacent intake appears.
- **This ADR claims "the collector is decided" but not installed.** That claim has a shelf life — if nothing fires within ~12 months, re-read this ADR before acting on it. OTel Collector won't break, but its CRD surface or the operator's deployment patterns may have evolved.

### What this preserves

- **ADR 0001's anti-completionism.** Nothing installs until a concrete trigger fires. The roadmap is a waiting pattern, not a commitment pattern.
- **ADR 0007's shape.** Metrics-only stays the install reality; logs and traces remain on-demand. The "every real cluster has X" trap is avoided — we have a plan for logs, not an install.
- **Kubernetes-native coherence.** OTel Collector is the CNCF-graduated answer; `OpenTelemetryCollector`/`Instrumentation` CRDs are the logs/traces equivalent of `ServiceMonitor`/`PodMonitor`. The three-ADR spine (0007 metrics, 0008 collector spine, 0009/0010 per-pillar) maintains the discipline.
- **Backend optionality.** VictoriaLogs and Jaeger are frontrunners *in this roadmap's moment*, not in stone. The install ADRs re-rank; the collector decision survives backend churn.
- **ADR 0006 sovereignty.** Both frontrunner backends (VictoriaLogs for logs, Jaeger/Badger for traces) avoid S3. Neither pillar's install fires ADR 0006's trigger by default. 0006 retains its integrity until a *genuinely* S3-hungry workload shows up.
- **Fast successor writes.** When Trigger 1 fires, ADR 0009 can be a short, focused *"install this backend behind the collector decided in 0008"* document, not a ground-up architecture review.

## Re-adoption guidance

This ADR is `Deferred`, not `Reverted`, so "re-adoption" here means *"conditions that activate the roadmap."* The ADR moves from `Deferred` toward `Accepted` (in the sense of being enacted) when any of the following happens:

1. **Trigger 1 fires** — named sentence from ADR 0007 about log-grep failure happens. Write **ADR 0009 — Install logs pipeline** as a short successor that re-verifies collector upstream status, picks backend from the shortlist at that moment, and hands off to `flux-app-author`. This ADR (0008) stays `Deferred` as the architectural spine for the traces half.
2. **Trigger 2 fires** — a workload arrives emitting OTLP traces AND a real diagnostic question exists that logs+metrics cannot answer. Write **ADR 0010 — Install traces pipeline**. Same pattern: re-verify Jaeger upstream status, pick backend, hand off.
3. **Both triggers fire in close succession** — could be a single ADR that installs logs and traces together, sharing the OTel Collector. Decide at trigger time based on whether the install will be easier as one paperwork or two.
4. **The collector decision needs revising** — if upstream otel-operator stalls meaningfully (two consecutive quarters with no release) OR if a materially better vendor-neutral CNCF-graduated collector emerges. Write a successor to *this ADR* (not to 0007) that reopens the collector question.
5. **The backend shortlist needs revising before any install** — if VictoriaLogs or Jaeger upstream degrades before Trigger 1/2 fire. Write a successor to this ADR updating the rankings.

Direct edits to the shortlists above are forbidden per the ADR immutability rule — changes come via successor ADRs. Small "seen-this-decay" notes may be added to the next successor's Context, not to this document.

## Follow-ups

- [ ] **Do nothing — actively.** This is a roadmap, not a task list. The follow-ups below all start with "when Trigger N fires."
- [ ] **When Trigger 1 fires**: write ADR 0009 (logs install) — single focused ADR that re-verifies OTel Collector + backend upstream, picks backend from shortlist, scaffolds via `flux-app-author`. Target completion: under one week from trigger-firing.
- [ ] **When Trigger 2 fires**: write ADR 0010 (traces install) — same pattern. Note that the OTel Collector installed in ADR 0009 already has OTLP receivers enabled, so ADR 0010's install is just "add a backend + Grafana data source."
- [ ] **At any install time**: re-verify `opentelemetry-operator` upstream status — CRD stability, release cadence, open-issue count vs closed. If anomalies, consult the Alloy fallback before committing.
- [ ] **Quarterly review** (~every 90 days from ADR date): skim this ADR and note whether any shortlist entry has visibly changed upstream status. Update the operator's mental model; do not edit this document. If the shortlist is materially wrong, write the successor.
- [ ] **Update `.claude/agent-memory/cluster-intake-gatekeeper/`** to record that logs and traces are pre-declared learning-and-concrete-need intake paths under triggers 1 and 2 of ADR 0007 — not new intake. A cluster-intake invocation for logs/traces after a trigger fires should route to ADR 0009/0010 scaffolding, not a fresh intake debate.
- [ ] **Watch for the anti-pattern**: if the operator finds themselves writing ADR 0009 without Trigger 1 having fired (i.e., installing logs *because* this roadmap made it easy), that is completionism dressed as governance. Abort the install and consult ADR 0001.
