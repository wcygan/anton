---
name: clickstack-ops
description: Operate the time-boxed ClickStack logs/traces experiment on anton (ClickHouse + Keeper + MongoDB + OTel collector + HyperDX, per ADR 0028). Use to access the HyperDX UI, send a test signal (pod logs via the bundled OTel collector, point Temporal's OTLP traces at it), run Lucene/SQL queries, check health of any ClickStack component, reconcile/debug the Flux flow, rotate the 1Password credentials via ESO, triage Renovate bumps for the two operators + chart, run the 2026-08-02 review-by checklist, or execute the exit/teardown runbook. Keywords — clickstack, hyperdx, clickhouse, keeper, mongodb, otel collector, otlp, logs, traces, wide events, lucene, temporal traces, teardown, exit plan, review-by, ADR 0028.
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

# clickstack-ops

Operational skill for the **ClickStack** learning experiment on anton — ClickHouse (column store) + Keeper + MongoDB + an OpenTelemetry Collector + HyperDX (Lucene/SQL UI for logs and traces). This is a **60-day throwaway eval** per ADR 0028 (`context/adrs/0028-clickstack-learning-experiment.md`), reviewed by **2026-08-02**. The deliverable is a successor ADR to 0008 that confirms or re-ranks the logs/traces backend shortlist. This skill is for running the eval day-to-day, not for production hardening.

Read ADR 0028 for the *why*. This skill assumes you already know the Flux 3-file pattern — if not, load `anton-repo-conventions` or `debug-flux-reconciliation` first.

## Containment rules (ADR 0028 — non-negotiable, don't relax for convenience)

- **Pillar separation is the key rule.** Metrics stay 100% on kube-prometheus-stack. ClickStack owns **only** logs + traces. Do **not** bridge Prometheus metrics into ClickHouse, do **not** add a ServiceMonitor that forks prod metrics, do **not** make anything outside `clickstack` `dependsOn` it.
- Own `clickstack` namespace only.
- Evaluate ClickStack **as-shipped** — the chart's bundled ClickHouse + Keeper + MongoDB + OTel collector. Do not externalize to production CNPG / SeaweedFS / etc.
- HyperDX UI exposed **internal-only** — no Cloudflare tunnel, no `envoy-external`, no public path. Two internal routes exist: the `envoy-internal` HTTPRoute (on-LAN) and a `tailscale` IngressClass Ingress (off-LAN, per ADR 0012). ADR 0028's body says "envoy-internal HTTPRoute only"; the Tailscale Ingress is a same-spirit internal addition — see [tailscale-access](references/tailscale-access.md).
- Explicit resource limits on ClickHouse; all default passwords overridden via ESO.

## When to invoke

| Intent | Section / Reference |
| --- | --- |
| Open the HyperDX UI / first-login | [USAGE](#usage) · [usage](references/usage.md) |
| Reach HyperDX over Tailscale / fix a login→`localhost` redirect | [tailscale-access](references/tailscale-access.md) |
| Send a test signal — pod logs via the bundled collector | [usage](references/usage.md#test-signal-pod-logs-via-the-otel-collector) |
| Point Temporal's OTLP traces at ClickStack (ADR 0028 follow-up) | [usage](references/usage.md#test-signal-temporal-otlp-traces) |
| Run a Lucene or SQL query in HyperDX | [usage](references/usage.md#querying-lucene-and-sql) |
| Check health of ClickHouse / Keeper / MongoDB / HyperDX / collector | [OPERATIONS](#operations) · [operations](references/operations.md#health-checks) |
| Reconcile / debug the Flux flow | [operations](references/operations.md#reconcile-and-debug) |
| Rotate the 1Password credentials (ESO) | [operations](references/operations.md#credential-rotation-eso--1password) |
| Triage a Renovate bump (two operators + chart) | [MAINTENANCE](#maintenance) · [maintenance](references/maintenance.md#renovate-posture) |
| Run the 2026-08-02 review-by checklist | [maintenance](references/maintenance.md#review-by-checklist-2026-08-02) |
| Tear the whole thing down | [maintenance](references/maintenance.md#exit--teardown-runbook) |

## Anton-specific facts (don't re-derive these)

- **Namespace**: `clickstack`. Everything lives here. Namespace prune is disabled.
- **Two-phase install** (ADR 0028 / ADR 0027):
  - `clickstack-operators` — Flux Kustomization, `wait: true`. Installs the **ClickHouse Kubernetes Operator** (`ClickHouseCluster` + `KeeperCluster` CRDs — NOT Altinity's `clickhouse-operator`/`ClickHouseInstallation`) and the **MongoDB Community Operator (MCK)** (`MongoDBCommunity` CRD). Chart `clickstack-operators` **1.0.0**.
  - `clickstack-app` — `dependsOn` operators + `external-secrets` + `envoy-gateway`. Installs HyperDX + OTel collector + the `ClickHouseCluster`/`KeeperCluster`/`MongoDBCommunity` CRs. Chart `clickstack` **3.0.0** (appVersion 2.27.0).
- **Source**: both charts come from a classic Helm repo (`HelmRepository`), not OCI: `https://clickhouse.github.io/ClickStack-helm-charts`. The operators app's source is named `clickstack`; the main app's is named `clickstack-charts` (distinct names so two Kustomizations in one namespace don't co-own one source object).
- **HyperDX naming quirk**: release name is `clickstack`, but the chart's `clickstack.hyperdx.fullname` helper appends `-app`, so the HyperDX **Deployment and Service render as `clickstack-app`**. The HTTPRoute backendRef and the `clickstack-app` ks.yaml healthCheck both reference that name. A top-level `fullnameOverride` is deliberately NOT set (it would desync ClickHouse/Keeper/MongoDB names from the release-derived OTel service name).
- **HyperDX URL**: off-LAN via Tailscale at `hyperdx.<tailnet-name>.ts.net` (the `hyperdx-tailscale-ingress` app), on-LAN via `envoy-internal` at `hyperdx.${SECRET_DOMAIN}`. Both domains come from Flux postBuild (`${TAILNET_SUFFIX}` / `${SECRET_DOMAIN}` in `cluster-secrets`) — **never hardcode the tailnet name or the domain**. HyperDX's `FRONTEND_URL` is set to `https://hyperdx.${TAILNET_SUFFIX}` so login redirects target the tailnet origin (the chart default `http://localhost:3000` breaks off-box login). Full rationale + verification in [tailscale-access](references/tailscale-access.md).
- **OTel collector is Deployment-mode, not DaemonSet.** It receives telemetry via OTLP (`4317` gRPC / `4318` HTTP) and writes to ClickHouse. It does **not** scrape pod logs by default — wiring the filelog receiver is the operational test-signal step (see usage).
- **Credentials**: ESO `ExternalSecret` `clickstack-credentials` pulls four fields from 1Password vault `anton`, item `clickstack`. Flux injects each into the chart values via `valuesFrom` + `targetPath: hyperdx.secrets.*`. The ESO Secret is deliberately named `clickstack-credentials`, **not** `clickstack-secret` — the chart unconditionally renders its own `clickstack-secret`, so a same-named ESO target would fight Helm over ownership.
  - 1Password item `clickstack` (fields `HYPERDX_API_KEY`, `CLICKHOUSE_PASSWORD`, `CLICKHOUSE_APP_PASSWORD`, `MONGODB_PASSWORD`) is **created and the ExternalSecret resolves** (`SecretSynced=True`). To rotate, see [operations](references/operations.md#credential-rotation-eso--1password).
- **Manifests** (source of truth, prefer reading these over re-deriving):
  - Operators: `kubernetes/apps/clickstack/clickstack-operators/app/helmrelease.yaml`
  - Main chart values: `kubernetes/apps/clickstack/clickstack-app/app/helmrelease.yaml`
  - ESO: `kubernetes/apps/clickstack/clickstack-app/app/externalsecret.yaml`
  - HTTPRoute (on-LAN): `kubernetes/apps/clickstack/clickstack-app/app/httproute.yaml`
  - Tailscale Ingress (off-LAN): `kubernetes/apps/clickstack/hyperdx-tailscale-ingress/app/ingress.yaml`

## USAGE

Accessing HyperDX, sending a test signal, and querying. Full recipes in [usage](references/usage.md).

- **Access the UI**: over Tailscale at `https://hyperdx.<tailnet-name>.ts.net` (the `hyperdx-tailscale-ingress` app — find the live host with `kubectl get ingress hyperdx -n clickstack`), or on-LAN at `https://hyperdx.${SECRET_DOMAIN}` (envoy-internal). First login creates the local HyperDX account; the data source (ClickHouse connection) is seeded by HyperDX itself for the eval (`useExistingConfigSecret: false`). If login bounces to `localhost`, `FRONTEND_URL` is wrong — see [tailscale-access](references/tailscale-access.md).
- **Test signal — pod logs**: the bundled collector listens for OTLP but does not tail pod logs out of the box. To feed it logs you either (a) add a **filelog receiver** to the collector config, or (b) point an app's OTLP log exporter at the collector Service. Recipe + the in-cluster OTLP endpoint in [usage](references/usage.md#test-signal-pod-logs-via-the-otel-collector).
- **Test signal — Temporal OTLP traces** (ADR 0028 follow-up, **not** part of the scaffold): point the Temporal server's OTLP trace exporter at the ClickStack collector's gRPC endpoint. **Do not edit the Temporal app manifests as part of this skill's scaffolding** — this is a deliberate, separate operational change. Endpoint + Temporal-side config in [usage](references/usage.md#test-signal-temporal-otlp-traces).
- **Querying**: HyperDX supports Lucene-style search and a SQL mode against ClickHouse. Patterns for the four ADR 0028 success criteria (cross-pod / ≥24h wide-events questions) in [usage](references/usage.md#querying-lucene-and-sql).

## OPERATIONS

Health, reconcile/debug, and credential rotation. Full recipes in [operations](references/operations.md).

- **Health**: walk operators → CRs → workloads. `flux get hr -n clickstack`, then the `ClickHouseCluster`/`KeeperCluster`/`MongoDBCommunity` CR status, then the HyperDX Deployment, collector, and pods. One-liners in [operations](references/operations.md#health-checks).
- **Reconcile / debug**: standard anton Flux flow — `flux reconcile ks clickstack-operators -n flux-system` then `clickstack-app`. The two-phase `dependsOn` means a stuck operators phase blocks the app phase; check that first. Hand deep Flux stalls to the `debug-flux-reconciliation` skill / `flux-debugger` subagent.
- **Credential rotation**: rotate in 1Password item `clickstack`, let ESO refresh (or force it), then restart the consuming pods — ESO/Helm value injection does not hot-reload. Ordered steps in [operations](references/operations.md#credential-rotation-eso--1password). For the broader rotation discipline, see the `rotate-credential` skill.

## MAINTENANCE

Renovate posture, the review-by checklist, and teardown. Full detail in [maintenance](references/maintenance.md).

- **Renovate**: three young pins enter the audit queue — `clickstack-operators` 1.0.0, `clickstack` 3.0.0, and transitively the two bundled operators. Treat operator-major bumps as cluster-tier (CRD churn risk); chart bumps as their own tier. Posture + merge guidance in [maintenance](references/maintenance.md#renovate-posture). Hand PR triage to `anton-upgrade-audit` / `upgrade-auditor`.
- **Review-by 2026-08-02**: answer ADR 0028's four success criteria with evidence, then either write the ADR 0008 successor (via the `adr` skill) and execute the exit plan, or consciously re-decide. **Do not let the experiment lapse silently** — the review-by field is load-bearing. Checklist in [maintenance](references/maintenance.md#review-by-checklist-2026-08-02).
- **Exit / teardown**: `flux suspend` → delete the namespace → remove the two operators, their ClusterRoles, and the three CRDs. Eval data is throwaway. Full runbook with the exact resources to remove in [maintenance](references/maintenance.md#exit--teardown-runbook).

## Related skills

- `anton-repo-conventions` — SOPS-vs-ESO, postBuild, Flux-namespace rules
- `debug-flux-reconciliation` — when the manifest is committed but the HelmRelease / CR hasn't applied
- `rotate-credential` — the durable rotation procedure ESO credential rotation rides on
- `anton-upgrade-audit` — Renovate PR triage and tiered merge order for the operator + chart bumps
- `adr` — author the ADR 0008 successor at the 2026-08-02 review
- `observability-integrate` — the metrics pillar that ClickStack must **not** touch (read it to know the boundary)
- `expose-service` — HTTPRoute mechanics (HyperDX is already wired; relevant only if exposure changes)

## Pointers

- ADR 0028 (the experiment, success criteria, exit plan): `context/adrs/0028-clickstack-learning-experiment.md`
- ADR 0027 (the platform `dependsOn` rule the two phases follow): `context/adrs/0027-platform-dependson-rule.md`
- ADR 0008 (deferred logs/traces roadmap this eval informs): `context/adrs/0008-*.md`
- ADR 0007 (metrics-only baseline ClickStack must not displace): `context/adrs/0007-adopt-kube-prometheus-stack.md`
