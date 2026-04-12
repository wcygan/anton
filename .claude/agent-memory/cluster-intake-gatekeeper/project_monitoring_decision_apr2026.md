---
name: Monitoring stack decision (April 2026)
description: How ADRs 0007/0008 landed after a three-agent team review rejected a VictoriaMetrics pivot; kube-prometheus-stack won on Kubernetes-native grounds; logs/traces roadmap committed behind named triggers
type: project
---

**Fact**: On 2026-04-12 the operator asked to revisit ADR 0003's deferred monitoring decision. Initial proposal pivoted from the ADR 0006-implied LGTM anchor to a VictoriaMetrics + VictoriaLogs + Grafana shape on practitioner Reddit feedback. A three-agent team review (`devils-advocate`, `cluster-intake-gatekeeper` — me — and a general-purpose web-research auditor) converged on a different answer. Final outcome: **ADR 0007 Accepted (kube-prometheus-stack)**, **ADR 0008 Deferred (OpenTelemetry-based logs/traces roadmap)**, **ADR 0003 stays Deferred, ADR 0006 stays Accepted and is decoupled rather than superseded.**

**My intake verdict was DEFER, not Add.** An earlier draft of this memory recorded "Add" — that was wrong; my first gatekeeper message returned empty and on re-prompt I delivered the DEFER with three unblock conditions (intent reconciliation, VictoriaLogs scope clarification, ADR 0006 decoupling). The operator addressed the conditions and resolved the decision by shifting axis to "most Kubernetes-native," which re-opened the shortlist in a way that landed on kube-prometheus-stack cleanly. DEFER → resolution-via-reframing is a legitimate path, not a bypass — but the memory must record the DEFER, not the final Add, since the Add came from a different decision frame.

**What each agent contributed**:
- **devils-advocate**: flagged that pivoting 48 hours after ADR 0006 on social-proof evidence was governance theater; surfaced the CRD-parallelism tax from ADR 0003 line 101 as a cost being silently waved away; observed that "defer traces" recreated the completionism pattern from ADR 0001.
- **intake-gatekeeper (me)**: DEFER with unblock conditions — intent flip from `unknown` (ADR 0003) to `mixed` in 24 hours needed honest reconciliation; smallest-viable-install was probably less than VMStack; ADR 0006 must be decoupled not superseded to protect immutability discipline.
- **web-research-auditor (general-purpose)**: **refuted the "Alloy → VictoriaLogs is untested" claim** (it's documented and supported via VL's Loki-protocol endpoint); partially confirmed "Tempo weaker than Jaeger" (CNCF-graduated vs not, Jaeger 4× stars); found no primary-source 2025–2026 bake-off backing the "VM is 10× easier" practitioner claim.

**Decisive axis — Kubernetes-native**: once the operator asked "which is the most Kubernetes-native choice," the shortlist collapsed. kube-prometheus-stack owns the Prometheus-operator CRDs (`ServiceMonitor`/`PodMonitor`/`PrometheusRule`) that every Flux chart in anton ships by default — Cilium, cert-manager, envoy-gateway, external-dns, ESO, Longhorn-to-be, SeaweedFS-operator-to-be, Flux itself. Any non-Prometheus-operator pick pays a recurring CRD-translation tax for no offsetting benefit at this scale. This axis settled the debate in one move — no further practitioner-opinion weighing required.

**What ADR 0007 actually committed**:
- kube-prometheus-stack chart v83.x pinned, single-replica Prometheus (15d TSDB, 50 GiB Longhorn PVC), single-replica Alertmanager (no routes at install), single-replica Grafana (dashboards GitOps'd via sidecar ConfigMap).
- Blackbox Exporter bundled; Probe CRs added on demand.
- No Thanos sidecar, no remote-write — install stays self-contained on Longhorn.
- Grafana exposed via HTTPRoute on `envoy-internal` only.
- **Three named re-open triggers** for logs / traces / long-term metrics retention, each authorising a future ADR.

**What ADR 0008 pre-decided (without installing anything)**:
- When Trigger 1 or 2 fires, anton adopts **OpenTelemetry Collector via opentelemetry-operator** as the CNCF-graduated, CRD-native, vendor-neutral, backend-swappable collector layer for *both* logs and traces. One collector spine; two pillars.
- **Logs backend shortlist** (re-verified at install): VictoriaLogs frontrunner (single binary on Longhorn, no S3, OTLP + Loki-protocol ingestion documented); Loki runner-up (would fire ADR 0006 if S3 mode chosen); OpenObserve "worth re-verifying"; SigNoz rejected (ClickHouse tax).
- **Traces backend shortlist**: Jaeger frontrunner (CNCF-graduated, Grafana data source, Badger single-node mode); Tempo runner-up; SigNoz/ClickHouse rejected.
- **Alloy rejected as primary collector** — vendor-specific (Grafana-bound) and less K8s-native than OTel Collector by CRD measure. Alloy remains a fallback if otel-operator upstream stalls.
- **Vector/Fluent Bit rejected as primary** — ConfigMap-driven, not CRD-driven.
- **ADR 0006 sovereignty preserved**: both frontrunner backends avoid S3. Neither pillar's install fires 0006's trigger.

**What ADR 0006 cascade resolution looks like**: ADR 0006 stays `Accepted`. ADR 0007 contains a one-line note that 0006's install trigger does not fire from the monitoring path. SeaweedFS waits for a *different* S3 consumer (backups, media stack, Mimir-as-remote-write, etc.). None of 0006's six documented supersession triggers fired; therefore 0006 is not rewritten. This preserves ADR immutability as a governance norm — re-litigating a 48-hour-old ADR on Reddit feedback would have been the failure mode.

**Graveyard relevance — did this clear the LGTM-removal check?**: Yes, narrowly. ADR 0001's #1 regret was LGTM in *microservices mode with no workloads to observe*, not Prometheus-as-an-idea. kube-prom-stack single-replica at ~3 GiB is not the same shape as the original 4–8 GiB microservices LGTM burn. ADR 0003 explicitly pre-blessed "narrower scope first" as the re-adoption path. The graveyard clears **provided install actually stays small** — no Thanos, no remote-write, no VMAlert-style overbuilding. If any of that creeps in during scaffolding, it's a graveyard repeat.

**Why this decision is durable**: the team-review pattern forced honesty on every load-bearing claim. Three of the four practitioner claims that drove the initial pivot were *wrong or overstated* once independently verified. Future intake should apply the same discipline — social proof is evidence of what practitioners like, not of what fits anton's constraints.

**How to apply**:
- If a future intake for logs or traces arrives after a trigger fires, **do not re-run intake from scratch**. Route to ADR 0008's roadmap; the collector is already decided and the backend shortlist is already ranked. The successor ADR (0009 logs / 0010 traces) is an install-only document, not a fresh architecture review.
- If a future intake questions "why not VictoriaMetrics?" — the answer is the CRD-parallelism tax, not a technical weakness. VictoriaMetrics is a serious candidate specifically for long-term retention via Prometheus remote-write (ADR 0007 Trigger 3), not as an upfront stack replacement.
- If a future intake proposes a SigNoz/OpenObserve-style all-in-one observability platform, the answer is "supersedes ADR 0007 — requires explicit ADR, not an intake rubric pass." Ground-up replacement of the metrics pillar is outside normal intake scope.
- **Re-verify upstream status before any logs/traces install**. VictoriaLogs is on ~weekly releases; Jaeger v2 storage is in transition; otel-operator's CRD surface evolves. The shortlists in ADR 0008 are guidance, not locks — treat any ranking older than ~60 days as decayed.
- **Watch for the anti-pattern** ADR 0008 Follow-ups calls out: if someone writes ADR 0009 *without* Trigger 1 firing (i.e., installing logs because the roadmap made it easy), that's completionism dressed as governance. Abort and consult ADR 0001.

**Cross-references**:
- ADR 0003 (deferred, still open) — the original monitoring deferral; its trigger #4 is ADR 0007's authorising path.
- ADR 0006 (accepted, install trigger decoupled) — unaffected structurally; its consumer is now "some future S3 workload," not LGTM.
- ADR 0007 (accepted) — the actual install ADR.
- ADR 0008 (deferred roadmap) — the OTel-based logs/traces spine.
- `.claude/agent-memory/cluster-intake-gatekeeper/project_s3_shortlist_apr2026.md` — S3 decisions sit alongside but don't interact with this decision now that 0006 is decoupled.
