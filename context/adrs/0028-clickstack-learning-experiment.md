---
status: Accepted
date: 2026-06-03
deciders: ['@wcygan']
affects: observability
intent: learning
supersedes: []
superseded-by: null
retrospective: false
review-by: 2026-08-02
---

# 0028 — Run ClickStack as a time-boxed logs/traces backend experiment

> 60-day learning intake: stand up ClickStack (ClickHouse + OTel + HyperDX) in a contained namespace to test whether ADR 0008's logs/traces backend shortlist (VictoriaLogs/Jaeger) should be re-ranked — metrics stay on Prometheus throughout.

## Status

Accepted

## Context

ADR 0007 chose kube-prometheus-stack as a deliberate metrics-only baseline. ADR 0008 is a deferred logs+traces roadmap that already decided the collector layer (OpenTelemetry Collector via otel-operator) and ranked the *backends* — VictoriaLogs (logs) and Jaeger (traces) as frontrunners — while explicitly rejecting the ClickHouse all-in-one shape (SigNoz) on three grounds: "ClickHouse is too heavy," "abandons Grafana-as-front-door," and "two metrics stores is worse than one." ADR 0008's Re-adoption-guidance clause 5 leaves an explicit door open: *"the backend shortlist needs revising before any install → write a successor ADR updating the rankings."*

ClickStack is ClickHouse's productized observability stack: ClickHouse (column store) + OpenTelemetry Collector + HyperDX (Lucene/SQL UI for logs, traces, metrics, session replay). Architecturally it is the same family as the SigNoz that 0008 rejected — but the rejection was for *concrete-need production adoption*, and was reasoned from upstream status that decays. anton is partly a learning cluster, and the honest question "do 0008's rejection grounds still hold at anton's scale?" is itself worth testing empirically rather than assuming.

This decision passed the `cluster-intake` gate as honest **learning** intent: containment gates 1–5 pass, the graveyard is clean (no reverted ClickHouse/observability ADR), and crucially ClickStack *keeps* the one thing ADR 0008 already decided (OTel Collector) and only challenges the two things 0008 left open-but-ranked — the **backend** (ClickHouse vs VictoriaLogs/Jaeger) and the **front-door** (HyperDX vs Grafana). This ADR records the experiment, not a production adoption; it does **not** supersede ADR 0007 or 0008.

## Decision

We will run ClickStack as a contained, time-boxed learning experiment in its own `clickstack` namespace, reviewed by **2026-08-02 (60-day timebox)**. The experiment's deliverable is a successor ADR to 0008 that either **confirms** the VictoriaLogs+Jaeger shortlist with evidence or **re-ranks** toward a ClickHouse/HyperDX backend.

Deployment path is the official ClickHouse-maintained Helm charts (`https://clickhouse.github.io/ClickStack-helm-charts`), a two-phase install — `clickstack-operators` (ClickHouse operator + MongoDB MCK operator + CRDs) as a platform Kustomization, then `clickstack` (HyperDX + OTel collector + the `ClickHouseCluster`/`KeeperCluster`/`MongoDBCommunity` custom resources) as a config Kustomization that `dependsOn` the operators per ADR 0027. Credentials flow from 1Password via ESO into the chart's `clickstack-secret` (`useExistingConfigSecret`); the HyperDX UI is exposed via an `envoy-internal` HTTPRoute only.

**Containment conditions (load-bearing — these keep it learning, not creep):**

- Own `clickstack` namespace; nothing else `dependsOn` it.
- **Pillar separation is the key rule.** Metrics stay 100% on kube-prometheus-stack, untouched. ClickStack must not replace Prometheus, must not become a second metrics store, and must **not** bridge Prometheus metrics into ClickHouse during the eval (that builds the two-store mess and muddies the result). ClickStack owns only the logs+traces pillar. This matches the dominant real-world pattern — keep Prometheus for alerting metrics, use ClickStack for logs/traces/high-cardinality investigation; crossing into metrics is the rarer, weaker path and the ADR-0007 supersession risk.
- Fed by a deliberately chosen **test signal** — pod logs via the OTel filelog receiver + Temporal's OTLP traces — not a fork of the production metrics path.
- All chart default passwords overridden via ESO; explicit resource limits on ClickHouse.

**Success criteria (must produce falsifiable answers for the 0008 successor):**

1. Does ClickHouse-backed wide-events querying meaningfully beat VictoriaLogs for the cross-pod / ≥24h questions ADR 0008 Trigger 1 describes?
2. Is "ClickHouse is too heavy" still true at homelab scale given ~85 GiB free RAM/node? Measure real CPU/RAM/operational cost of ClickHouse + Keeper + MongoDB + HyperDX vs a VictoriaLogs single binary.
3. Is HyperDX's wide-events UX worth abandoning Grafana-as-front-door, or does running two UIs confirm 0008's fragmentation concern?
4. Does it stay contained, or drift toward a second metrics store (the containment test itself)?

**Exit plan:** `flux suspend` + delete the `clickstack` namespace + remove the two operators, their ClusterRoles, and the `ClickHouseCluster`/`KeeperCluster`/`MongoDBCommunity` CRDs. Eval data is throwaway; no production signal ever depends on it.

## Alternatives considered

- **Do nothing / wait for ADR 0008 triggers to fire** — the orthodox path. Rejected only because the intent is honest learning with a declared timebox and exit, which is an accepted path on a partly-learning cluster; the experiment also produces evidence that makes the eventual 0008 successor sharper.
- **Adopt ClickStack as a concrete-need production stack** — rejected. ADR 0007's triggers haven't fired, it would create a second metrics store / supersede 0007, and metrics+alerting is ClickStack's weakest pillar. Gate 4 (no parallel monitoring stack) fails under concrete-need intent.
- **Evaluate by bridging Prometheus metrics into ClickHouse (community migration pattern)** — rejected for *this* eval. The bridge is correct when the question is "migrate the whole stack," but anton's question is narrowly "is ClickHouse a better logs/traces backend?" Bridging metrics adds a confounding variable and the two-store cleanup cost.

## Consequences

### Accepted costs

- **Moderate (not trivial) exit cost.** Two operators + cluster-scoped CRDs to clean up (`ClickHouseCluster`, `KeeperCluster`, `MongoDBCommunity`) — heavier than a bundled StatefulSet, but reversible without data migration since the data is throwaway. anton already runs operator+CRD components routinely (CNPG, Dragonfly, Longhorn, SeaweedFS), so the shape is familiar.
- **Renovate / upgrade tax rises materially** — two new, young (v2.x) operators plus the chart enter the audit queue for the duration.
- **Two observability front-doors during the eval** — Grafana for metrics, HyperDX for logs/traces. This is intentional and is itself data for success criterion 3.
- **Discipline obligation.** A learning intake without an enforced review date becomes permanent intake. The `review-by: 2026-08-02` field is load-bearing; at that date either write the 0008 successor and tear down, or consciously re-decide.

## Follow-ups

- [ ] Hand off to `add-flux-app` to scaffold the `clickstack` namespace: operators platform Kustomization (`wait: true`) + `clickstack` config Kustomization (`dependsOn` operators, per ADR 0027) + ESO ExternalSecret → `clickstack-secret` + `envoy-internal` HTTPRoute for HyperDX.
- [ ] Wire the test signal: OTel filelog receiver for pod logs + Temporal OTLP traces export (verify Temporal server OTLP config).
- [ ] **2026-08-02 review:** answer the four success criteria, then either write the ADR 0008 successor (confirm or re-rank the backend shortlist) and execute the exit plan, or consciously re-decide. Do not let the experiment lapse silently.
