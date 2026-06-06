---
name: clickstack-ops
description: >-
  Operate Anton's time-boxed ClickStack logs and traces experiment. Use when
  handling HyperDX UI access, ClickHouse, Keeper, MongoDB, OTel collector
  health, Flux reconciliation, OTLP test signals, Lucene or SQL queries, ESO
  and 1Password credential rotation, Renovate chart or operator bumps, the
  2026-08-02 ADR 0028 review, or ClickStack teardown. Keywords: clickstack,
  hyperdx, clickhouse, keeper, mongodb, otel, otlp, logs, traces, wide events,
  temporal traces, review-by, ADR 0028.
---

# ClickStack Ops

Goal: Operate the ClickStack learning experiment on Anton without letting it become production observability.

Success means:
- Logs and traces questions are answered with ClickStack evidence.
- Metrics stay entirely on kube-prometheus-stack.
- Source-of-truth manifests and ADR 0028 remain the basis for any change.
- Live cluster mutations are presented for explicit operator approval before they run.

Stop when: the requested ClickStack task is handled, the next approval-only action is named, or the review/teardown evidence is recorded.

## Read First

1. Read root `AGENTS.md` for Anton safety rules.
2. Read `context/adrs/0028-clickstack-learning-experiment.md` for the experiment contract.
3. If editing manifests under `kubernetes/apps/clickstack/`, read `kubernetes/apps/AGENTS.md` and load `anton-repo-conventions`.
4. Load only the reference needed:
   - `references/usage.md` for HyperDX access, OTLP test signals, and queries.
   - `references/tailscale-access.md` for off-LAN HyperDX access and login redirects.
   - `references/operations.md` for health checks, Flux triage, and credential rotation.
   - `references/maintenance.md` for Renovate posture, the review-by checklist, and teardown.

Use QMD only when the task needs Anton history beyond the ADR and manifests. Treat QMD snippets as leads; retrieve the actual `context/` file before citing it.

## Safety Rules

- Run read-only checks freely: `kubectl get`, `kubectl describe`, `kubectl logs`, `flux get`, and file reads.
- Do not run live mutations without explicit operator approval. This includes `flux reconcile`, `flux suspend`, `kubectl annotate`, `kubectl rollout restart`, namespace deletion, CRD deletion, Temporal OTLP wiring, and credential rotation.
- Before asking for approval, show the exact command, target namespace/resource, expected effect, and verification command.
- Never hardcode the literal tailnet name or cluster domain. Use `<tailnet-name>.ts.net`, `${TAILNET_SUFFIX}`, and `${SECRET_DOMAIN}` in committed files.
- Never print or commit ClickStack credential values. Log field names and file paths only.

## Containment Rules

- Own only the `clickstack` namespace.
- Keep metrics 100% on kube-prometheus-stack. Do not bridge Prometheus metrics into ClickHouse, add ClickStack ServiceMonitors, or make non-ClickStack apps depend on ClickStack.
- Evaluate ClickStack as shipped: bundled ClickHouse, Keeper, MongoDB, OTel collector, and HyperDX.
- Keep HyperDX internal-only. Current manifests expose it through `envoy-internal` and a Tailscale Ingress, never Cloudflare or `envoy-external`.
- Keep ClickHouse resource limits explicit and all chart default passwords overridden through ESO.

## Anton Facts

- Namespace: `clickstack`; namespace prune is disabled.
- Install phases:
  - `clickstack-operators`: platform Kustomization with `wait: true`; installs ClickHouse and MongoDB operators. Chart `clickstack-operators` version `1.0.0`.
  - `clickstack-app`: depends on operators, `external-secrets`, and `envoy-gateway`; installs HyperDX, the OTel collector, and the ClickHouse/Keeper/MongoDB custom resources. Chart `clickstack` version `3.0.0`, appVersion `2.27.0`.
- Chart source: HTTP `HelmRepository` at `https://clickhouse.github.io/ClickStack-helm-charts`, not OCI.
- HyperDX release name quirk: release `clickstack` renders HyperDX Deployment and Service as `clickstack-app`; do not set a top-level `fullnameOverride`.
- Collector mode: Deployment, not DaemonSet. It accepts OTLP on 4317 and 4318 but does not tail pod logs until a test-signal change wires that path.
- Credentials: `ExternalSecret` `clickstack-credentials` reads the 1Password item `clickstack` and Flux injects four fields into `hyperdx.secrets.*`. The current manifest comments mark the 1Password item as an open setup item; verify live ESO status before claiming it exists.

## Source Files

- ADR: `context/adrs/0028-clickstack-learning-experiment.md`
- Operators HelmRelease: `kubernetes/apps/clickstack/clickstack-operators/app/helmrelease.yaml`
- Main chart values: `kubernetes/apps/clickstack/clickstack-app/app/helmrelease.yaml`
- ESO: `kubernetes/apps/clickstack/clickstack-app/app/externalsecret.yaml`
- On-LAN HTTPRoute: `kubernetes/apps/clickstack/clickstack-app/app/httproute.yaml`
- Off-LAN Tailscale Ingress: `kubernetes/apps/clickstack/hyperdx-tailscale-ingress/app/ingress.yaml`

## Quick Read-Only Pulse

```sh
flux get ks -A | rg clickstack
flux get hr -n clickstack
kubectl -n clickstack get externalsecret,secret
kubectl -n clickstack get clickhousecluster,keepercluster,mongodbcommunity
kubectl -n clickstack get deploy,sts,pods -o wide
kubectl -n clickstack get httproute,ingress
```

If a mutating action is needed after this pulse, stop and ask for approval with the exact command.

## Related Skills

- `anton-repo-conventions` for Flux app shape, sources, substitutions, and secret conventions.
- `debug-flux-reconciliation` for stuck Kustomizations, HelmReleases, SOPS, and substitutions.
- `anton-remote-access` for kubeconfig, Tailscale, and Talos access paths.
- `rotate-credential` for broader credential rotation discipline.
- `anton-upgrade-audit` for Renovate PR triage.
- `adr` for the ADR 0008 successor at review time.
- `observability-integrate` for the metrics boundary ClickStack must not cross.
- `expose-service` for Gateway API and Tailscale exposure mechanics.
