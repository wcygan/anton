# ClickStack experiment — baseline & operations

Baseline / operations artifact for the **ClickStack 60-day learning experiment** ([ADR 0028](https://github.com/wcygan/anton/blob/main/context/adrs/0028-clickstack-learning-experiment.md)). Captures what was deployed, the manifest layout, the endpoint surface, the 1Password item the operator still has to create, the containment rules that keep this learning rather than creep, and the hard exit obligation on **2026-08-02**.

> This is a **throwaway eval**, not a production adoption. ADR 0028 does **not** supersede ADR 0007 (kube-prometheus-stack for metrics) or ADR 0008 (the deferred logs+traces roadmap). The deliverable is a successor ADR to 0008 that either confirms the VictoriaLogs+Jaeger shortlist or re-ranks toward ClickHouse/HyperDX — backed by evidence from this run. Metrics stay 100% on Prometheus throughout.

## What was deployed

ClickStack is ClickHouse's productized observability stack. We deploy it **as-shipped** — bundled ClickHouse + Keeper + OTel collector + MongoDB + HyperDX — to evaluate ClickStack itself, not an externalized assembly of production components. The install is **two-phase**, using the official ClickHouse-maintained Helm repo `https://clickhouse.github.io/ClickStack-helm-charts` (a classic gh-pages Helm repo, not OCI — same upstream-forced `HelmRepository` deviation as Longhorn / SeaweedFS).

| Phase | Flux Kustomization | Chart | Version | What it installs |
|---|---|---|---|---|
| 1 | `clickstack-operators` | `clickstack-operators` | 1.0.0 | The new **ClickHouse Kubernetes Operator** (`ClickHouseCluster` + `KeeperCluster` CRDs — **not** Altinity's `clickhouse-operator` / `ClickHouseInstallation`) and the **MongoDB Community Operator (MCK)** |
| 2 | `clickstack-app` | `clickstack` | 3.0.0 (appVersion 2.27.0) | HyperDX (UI/API), the OTel collector, and the `ClickHouseCluster` / `KeeperCluster` / `MongoDBCommunity` custom resources the Phase-1 operators reconcile |

Phase 2 `dependsOn` Phase 1 (plus `external-secrets` for the credential pull and `envoy-gateway` for the HTTPRoute CRD), and Phase 1's Kustomization sets `wait: true` so the operators must report `Ready=True` before the main chart applies any CR. Two-phase ordering follows ADR 0027.

Both chart versions are **pinned** (no ranges) per ADR 0028 — young charts, single published version each; Renovate owns the bump.

### Component shape (chart as-shipped)

| Component | Backed by | Notes |
|---|---|---|
| ClickHouse | `ClickHouseCluster` CR | Single replica (fine for a throwaway eval). **Explicit resource limits — ADR 0028 hard requirement:** requests `1` CPU / `4Gi`, limits `4` CPU / `8Gi`; `20Gi` data PVC |
| ClickHouse Keeper | `KeeperCluster` CR | `5Gi` data PVC |
| MongoDB | `MongoDBCommunity` CR | HyperDX app metadata store. Resources set via the CRD's `spec.statefulSet` override (container name `mongod`), **not** a top-level `mongodb.resources` key (read by no template) |
| OTel collector | Deployment (not DaemonSet) | Receives OTLP (`4317` gRPC / `4318` HTTP), writes to ClickHouse. Does **not** scrape pod logs by default |
| HyperDX | Deployment `clickstack-app` | Lucene/SQL UI for logs/traces. ClusterIP service; chart Ingress disabled — Gateway API owns exposure |

### Naming gotcha worth remembering

Release name is `clickstack`, but the chart's `clickstack.hyperdx.fullname` helper **appends `-app`** — so the HyperDX Deployment and Service render as **`clickstack-app`**. The HTTPRoute `backendRef` and the `clickstack-app` Kustomization `healthChecks` both reference that name. A top-level `fullnameOverride` is deliberately **not** used: the helper would also rename ClickHouse/Keeper/MongoDB while the OTel service name stays release-name-derived, desyncing the chart's internal service wiring.

## Manifest layout

Standard anton 3-file Flux pattern, one namespace dir with two apps (the two install phases):

```
kubernetes/apps/clickstack/
  namespace.yaml                          # creates clickstack ns (prune disabled)
  kustomization.yaml                      # components: ../../components/sops; lists both ks.yaml
  clickstack-operators/                   # PHASE 1
    ks.yaml                               # wait: true; postBuild substituteFrom cluster-secrets
    app/
      kustomization.yaml
      helmrepository.yaml                 # source name `clickstack`
      helmrelease.yaml                    # chart clickstack-operators 1.0.0, values: {}
  clickstack-app/                         # PHASE 2
    ks.yaml                               # dependsOn [operators, external-secrets, envoy-gateway]
    app/
      kustomization.yaml
      helmrepository.yaml                 # source name `clickstack-charts` (see note below)
      helmrelease.yaml                    # chart clickstack 3.0.0; ESO creds via valuesFrom
      externalsecret.yaml                 # ESO → clickstack-credentials Secret
      httproute.yaml                      # envoy-internal/https → clickstack-app:3000
```

Two `HelmRepository` objects point at the **same upstream URL** but carry **distinct names** (`clickstack` vs `clickstack-charts`). Both Kustomizations target the `clickstack` namespace, so a shared name would make two Flux Kustomizations co-own one object and fight over SSA field ownership every reconcile; anton's 3-file-pattern hook also requires each app dir to ship its own source.

> Note: the `cluster-apps` Kustomization (`kubernetes/flux/cluster/ks.yaml`) points at `./kubernetes/apps` with no aggregating `kustomization.yaml`, so a new namespace directory that mirrors the existing ones (e.g. `kubernetes/apps/storage/`) is discovered automatically — no parent file needs editing.

## Endpoint surface

| Surface | Address | Notes |
|---|---|---|
| HyperDX UI (LAN) | `https://hyperdx.${SECRET_DOMAIN}` | Via `envoy-internal` Gateway (`https` listener) + the `hyperdx` HTTPRoute → `clickstack-app:3000`. Split-horizon DNS through `k8s_gateway` |
| HyperDX UI (tailnet) | `https://hyperdx.<tailnet>.ts.net` | Via the `tailscale` IngressClass (`hyperdx-tailscale-ingress` app → `clickstack-app:3000`). Off-LAN access per ADR 0012, mirrors `hubble-tailscale-ingress`. Tailnet-internal, not public |
| OTLP ingest (in-cluster) | OTel collector service, `4317` (gRPC) / `4318` (HTTP) | How workloads ship telemetry into ClickStack |

`${SECRET_DOMAIN}` is substituted by Flux `postBuild.substituteFrom` from the `cluster-secrets` Secret — never hardcode the domain.

**Internal-only, by ADR 0028 containment.** The HyperDX UI is reachable two internal ways: on-LAN via `envoy-internal` (Gateway API HTTPRoute) and off-LAN via the `tailscale` IngressClass (tailnet MagicDNS, per ADR 0012). Both are internal — **no** Cloudflare tunnel, **no** `envoy-external` binding, **no** `DNSEndpoint`, **no** public exposure. The chart's built-in Ingress is disabled (`hyperdx.ingress.enabled: false`). Note: ADR 0028's body says "envoy-internal HTTPRoute only"; the tailnet Ingress is a same-spirit internal addition (the operator asked for Tailscale access) — record it in the 0028 review.

## Credential retrieval — open item

ClickStack uses **ESO**, not SOPS. The `ExternalSecret clickstack-credentials` pulls four runtime credentials from **1Password vault `anton`**, item **`clickstack`**, via the `onepassword-connect` `ClusterSecretStore` (`onepasswordSDK` provider, combined-key syntax `<item>/<field>`).

> **OPEN ITEM — the 1Password item `clickstack` does NOT yet exist.** The operator must create it with these four fields before the ExternalSecret can resolve and Phase 2 can become Ready. No secret values were invented or committed — only the manifest references them.

| 1Password field | Purpose |
|---|---|
| `HYPERDX_API_KEY` | HyperDX app secret / API key |
| `CLICKHOUSE_PASSWORD` | The `otelcollector` ClickHouse user password |
| `CLICKHOUSE_APP_PASSWORD` | The `app` ClickHouse user password |
| `MONGODB_PASSWORD` | MongoDB password |

These **override the chart's weak default passwords** (an ADR 0028 hard requirement). The chart offers **no** `existingSecret` hook for these four runtime credentials — they are plain Helm values under `hyperdx.secrets.*`. So the flow is indirect:

1. ESO writes `Secret/clickstack-credentials` (four keys) from the 1Password item.
2. The `clickstack` HelmRelease injects each key into the values tree via `valuesFrom` + `targetPath: hyperdx.secrets.*`.
3. Helm templates the values into the running pods.

The ESO Secret is deliberately named `clickstack-credentials`, **not** `clickstack-secret`: the chart's `hyperdx/secret.yaml` template unconditionally renders its own `clickstack-secret` whenever `hyperdx.secrets` is non-nil (always, here), so an ESO target of the same name would put ESO and Helm in an ownership fight over one Secret. Only Flux reads the ESO Secret (by `valuesKey`), so its name is free to differ.

## Containment rules (ADR 0028)

These are load-bearing — they are what keep this a learning experiment instead of scope creep. **Pillar separation is the key rule.**

- **Own `clickstack` namespace only.** Nothing else `dependsOn` it.
- **Metrics stay 100% on kube-prometheus-stack, untouched.** ClickStack must not replace Prometheus, must not become a second metrics store, and must **not** bridge Prometheus metrics into ClickHouse during the eval. ClickStack owns **only** the logs+traces pillar. Bridging metrics would build the two-store mess ADR 0008 rejected and muddy the result.
- **No ServiceMonitors that fork production metrics** into ClickHouse.
- **Explicit ClickHouse resource limits** (set in the HelmRelease — see component table above).
- **HyperDX UI via `envoy-internal` HTTPRoute only** — no Cloudflare tunnel, no `envoy-external`.
- **Test signal is deliberately chosen, not a metrics fork:** pod logs via the OTel filelog receiver + Temporal's OTLP traces. Wiring that signal (filelog receiver config + pointing Temporal's OTLP export at the collector) is an **operational follow-up**, not part of this scaffold — and the Temporal app manifests are intentionally **not** edited here.

## Exit obligation — review by 2026-08-02

A learning intake without an enforced review date becomes permanent intake. The `review-by: 2026-08-02` field in ADR 0028 is load-bearing. At that date, do one of:

- **Tear down** — write the ADR 0008 successor (confirm or re-rank the logs/traces backend shortlist with evidence), then execute the exit plan below; **or**
- **Consciously re-decide** — explicitly, in a new ADR. Do not let the experiment lapse silently.

The four success criteria the successor ADR must answer (from ADR 0028):

1. Does ClickHouse-backed wide-events querying meaningfully beat VictoriaLogs for the cross-pod / ≥24h questions ADR 0008 Trigger 1 describes?
2. Is "ClickHouse is too heavy" still true at homelab scale (~85 GiB free RAM/node)? Measure real CPU/RAM/operational cost of ClickHouse + Keeper + MongoDB + HyperDX vs a VictoriaLogs single binary.
3. Is HyperDX's wide-events UX worth abandoning Grafana-as-front-door, or does running two UIs confirm 0008's fragmentation concern?
4. Does it stay contained, or drift toward a second metrics store (the containment test itself)?

### Exit plan

Eval data is throwaway; no production signal ever depends on it.

```sh
# 1. Suspend Flux so it stops reconciling the apps mid-teardown.
flux suspend kustomization clickstack-app clickstack-operators -n flux-system

# 2. Delete the custom resources first (operators GC their children), then the namespace.
kubectl -n clickstack delete clickhousecluster --all
kubectl -n clickstack delete keepercluster --all
kubectl -n clickstack delete mongodbcommunity --all
kubectl delete namespace clickstack   # destructive — confirm intent

# 3. Remove the manifests from Git: drop ./clickstack from the parent apps kustomization,
#    delete kubernetes/apps/clickstack/, commit, push, reconcile. Flux owns deletion.

# 4. Remove the two operators' cluster-scoped CRDs left behind. List them first
#    to get the exact CRD names/API groups, then delete:
kubectl get crd | grep -iE 'mongodbcommunity|clickhouse|keeper'
# kubectl delete crd <clickhousecluster-crd> <keepercluster-crd> <mongodbcommunity-crd>

# 5. Delete the 1Password item `clickstack` from vault `anton` once nothing references it.
```

> `kubectl delete namespace` is a hard rule destructive op — only with explicit confirmation. Verify the kube context before running anything mutating.

## Pointers

- Decision: [`context/adrs/0028-clickstack-learning-experiment.md`](https://github.com/wcygan/anton/blob/main/context/adrs/0028-clickstack-learning-experiment.md)
- Anchored against: [ADR 0007](https://github.com/wcygan/anton/blob/main/context/adrs/0007-adopt-kube-prometheus-stack.md) (metrics baseline, untouched) and [ADR 0008](https://github.com/wcygan/anton/blob/main/context/adrs/0008-opentelemetry-logs-and-traces-roadmap.md) (the logs+traces roadmap this experiment informs)
- Platform `dependsOn` convention: [ADR 0027](https://github.com/wcygan/anton/blob/main/context/adrs/0027-platform-dependson-rule.md)
- Manifests: `kubernetes/apps/clickstack/`
- Upstream charts: https://github.com/ClickHouse/ClickStack-helm-charts
