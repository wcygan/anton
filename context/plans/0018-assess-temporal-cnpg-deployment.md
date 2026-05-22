---
status: Done
opened: 2026-05-22
closed: 2026-05-22
affects: temporal
intent: concrete-need
related-adrs: [0027]
review-by: null
---

# 0018 - Assess Temporal on CNPG

> Shape a ready-to-implement Temporal deployment for Anton using the upstream Temporal Helm chart and a dedicated CloudNativePG cluster.

## Goal

Define a GitOps-ready Temporal deployment for Anton that uses the upstream Temporal Helm chart, a dedicated CNPG Postgres cluster, Flux dependency ordering, Kubernetes Secret references for persistence credentials, and internal access by default.

## Success Means

- The plan records a clear go recommendation grounded in current Temporal chart behavior and Anton's existing CNPG/Flux patterns.
- The implementation shape names every namespace, Kustomization, dependency edge, health check, Helm source, and chart value needed for a first manifest PR.
- The database contract names both Temporal stores, the CNPG bootstrap SQL, the chart schema-management settings, the credentials Secret, and the backup gate for durable workflows.
- The access contract exposes the Temporal Web UI at `https://temporal.<tailnet-name>.ts.net` through the Tailscale operator and validates that the Web UI can list namespaces and inspect workflow state.
- The validation loop names local render checks, read-only cluster checks, first reconcile checks, and an operator approval boundary.
- The plan gives the next agent enough context to draft manifests without rediscovering the Temporal/CNPG fit.

## Stop When

Stop shaping when this plan contains a complete implementation contract and every remaining item is either an execution task, an operator approval point, or an explicit open decision.

## Constraints

- Keep the plan in `Draft` while the work is assessment and manifest design.
- Use `registries/harbor-postgres` and `csgoplant/csgoplant-postgres` as precedents only; create a Temporal-owned Postgres cluster for Temporal state.
- Keep live-cluster interaction read-only during planning: `flux get`, `kubectl get`, `kubectl describe`, and local render commands are sufficient.
- Ask for explicit operator approval before applying Flux changes, reconciling the new app, exposing the gRPC frontend beyond trusted internal clients, or running destructive database actions.
- Choose the backup posture before running irreplaceable workflows on the cluster.
- Use the short Tailscale hostname `temporal` in manifests; document the full URL with the placeholder `temporal.<tailnet-name>.ts.net`.

## Direction

Build Temporal as two Flux apps in a new `temporal` namespace:

```text
databases/cloudnative-pg
  -> temporal/temporal-config
  -> temporal/temporal
```

Use `temporal-config` for state prerequisites: the CNPG `Cluster`, generated app Secret health check, and any future backup resources. Use `temporal` for the HelmRelease, HelmRepository, Tailscale Web UI Ingress, and chart-owned schema Job.

Expose the Temporal Web UI through a Tailscale operator `Ingress` at `https://temporal.<tailnet-name>.ts.net`, following ADR 0012 and the existing Harbor/ntfy pattern. Point the Ingress default backend at the chart's `temporal-web` Service on port `8080`. Keep the Temporal frontend service as ClusterIP for SDK clients inside the cluster and trusted internal networks. Add a separate routing decision before publishing Temporal's gRPC frontend through any public path.

Enable Temporal ServiceMonitors when the deployment lands, and make the `temporal` Kustomization depend on `observability/kube-prometheus-stack` so the `monitoring.coreos.com` CRDs exist before Helm renders those resources.

## Findings

- Go recommendation: Temporal fits Anton cleanly with a dedicated CNPG `Cluster`.
- Current upstream chart observed locally: chart `temporal` version `1.2.0`, app version `1.31.0`, server image `temporalio/server:1.31.0`, UI image `temporalio/ui:2.49.1`.
- Temporal needs two logical stores: `temporal` for workflow state and `temporal_visibility` for visibility/search metadata.
- The Temporal Web UI is the operator debugging surface for namespaces, workflow executions, workflow history, schedules, pending activities, and metadata. Ship the UI route with the initial deployment so the service is usable without port-forwarding.
- SQL visibility keeps the first deployment within the existing Postgres/CNPG footprint and leaves Elasticsearch/OpenSearch for a later explicit search-scale decision.
- CNPG's generated application user is intentionally unprivileged. Let CNPG create the databases, then set `createDatabase: false` in the Temporal chart.
- Temporal's chart can still own schema setup. Keep `manageSchema: true` so the schema Job runs `temporal-sql-tool setup-schema` and `temporal-sql-tool update-schema` against both stores.
- Flux should own Job lifecycle visibility. Set `schema.useHelmHooks: false` so the schema Job renders as a normal `batch/v1 Job`.
- Temporal chart `1.2.0` renders `TEMPORAL_SERVER_CONFIG_FILE_PATH=/etc/temporal/config/config_template.yaml` natively for server `1.31.0`; no extra config-path values are needed.
- The 1.29 compatibility shims can stay off for server/admin-tools `1.31.0`: set `shims.dockerize: false` and `shims.elasticsearchTool: false`.
- `numHistoryShards` is immutable after first deployment. Record the final value before first reconcile; the current chart default is `512`.

## App Shape

```text
kubernetes/apps/temporal/namespace.yaml
kubernetes/apps/temporal/kustomization.yaml
kubernetes/apps/temporal/temporal-config/ks.yaml
kubernetes/apps/temporal/temporal-config/app/postgres-cluster.yaml
kubernetes/apps/temporal/temporal-config/app/kustomization.yaml
kubernetes/apps/temporal/temporal/ks.yaml
kubernetes/apps/temporal/temporal/app/helmrepository.yaml
kubernetes/apps/temporal/temporal/app/helmrelease.yaml
kubernetes/apps/temporal/temporal/app/ingress-tailscale.yaml
kubernetes/apps/temporal/temporal/app/kustomization.yaml
```

Model the root namespace folder after `kubernetes/apps/registries/`:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: temporal

components:
  - ../../components/sops

resources:
  - ./namespace.yaml
  - ./temporal-config/ks.yaml
  - ./temporal/ks.yaml
```

## Dependency Contract

`temporal-config/ks.yaml`:

- Depends on `databases/cloudnative-pg`.
- Targets namespace `temporal`.
- Health-checks `Cluster/temporal-postgres`.
- Health-checks `Secret/temporal-postgres-app`, matching the Harbor CNPG precedent.

`temporal/ks.yaml`:

- Depends on `temporal-config`.
- Depends on `observability/kube-prometheus-stack` when Temporal ServiceMonitors are enabled.
- Health-checks `HelmRelease/temporal` and `Ingress/temporal` when the Tailscale UI route is present.

## Access Contract

Expose the Temporal Web UI over Tailscale:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: temporal
spec:
  ingressClassName: tailscale
  defaultBackend:
    service:
      name: temporal-web
      port:
        number: 8080
  tls:
    - hosts:
        - temporal
```

Verify the user-facing URL as `https://temporal.<tailnet-name>.ts.net`. Use the short hostname in the manifest so the literal tailnet name stays out of git. Keep any optional LAN route through `envoy-internal` as a separate follow-up after the Tailscale Web UI path works.

## Database Contract

Create a Temporal-owned CNPG cluster in the `temporal` namespace:

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: temporal-postgres
spec:
  instances: 3
  imageName: ghcr.io/cloudnative-pg/postgresql:17.2

  storage:
    storageClass: longhorn
    size: 20Gi

  walStorage:
    storageClass: longhorn
    size: 5Gi

  bootstrap:
    initdb:
      database: temporal
      owner: temporal
      postInitSQL:
        - CREATE DATABASE temporal_visibility OWNER temporal

  monitoring:
    enablePodMonitor: true
```

Tune storage, WAL size, memory, and replicas during implementation using Harbor's `harbor-postgres` values as the starting point. Keep the generated Secret name `temporal-postgres-app`; the Temporal chart reads its `password` key.

## Helm Values Contract

Start the Temporal HelmRelease with these persistence and Flux settings:

```yaml
schema:
  useHelmHooks: false

shims:
  dockerize: false
  elasticsearchTool: false

server:
  image:
    tag: 1.31.0
  resources:
    requests:
      cpu: 100m
      memory: 256Mi
    limits:
      memory: 512Mi
  metrics:
    serviceMonitor:
      enabled: true
      interval: 30s
  config:
    logLevel: info
    persistence:
      defaultStore: default
      visibilityStore: visibility
      numHistoryShards: 512
      datastores:
        default:
          sql:
            createDatabase: false
            manageSchema: true
            pluginName: postgres12
            driverName: postgres12
            databaseName: temporal
            connectAddr: temporal-postgres-rw.temporal.svc.cluster.local:5432
            connectProtocol: tcp
            user: temporal
            existingSecret: temporal-postgres-app
            secretKey: password
            connectAttributes:
              sslmode: require
            maxConns: 20
            maxIdleConns: 20
            maxConnLifetime: "1h"
        visibility:
          sql:
            createDatabase: false
            manageSchema: true
            pluginName: postgres12
            driverName: postgres12
            databaseName: temporal_visibility
            connectAddr: temporal-postgres-rw.temporal.svc.cluster.local:5432
            connectProtocol: tcp
            user: temporal
            existingSecret: temporal-postgres-app
            secretKey: password
            connectAttributes:
              sslmode: require
            maxConns: 20
            maxIdleConns: 20
            maxConnLifetime: "1h"
    namespaces:
      create: true
      namespace:
        - name: default
          retention: 3d
```

Implementation adds first-pass resource requests and a `15m` HelmRelease timeout. Add pod disruption policy after the initial reconcile if any Temporal service scales beyond one replica.

## Implementation Tasks

- [x] Read upstream Temporal self-hosted deployment docs and the current `temporalio/helm-charts` chart metadata.
- [x] Inspect Anton's CNPG operator, Harbor CNPG consumer pattern, Flux dependency rule, and live read-only CNPG cluster inventory.
- [x] Render the Temporal chart locally with PostgreSQL persistence to verify schema Job behavior under Flux-compatible settings.
- [x] Reshape this plan as an outcome-first implementation contract using directional language.
- [x] Confirm the first-pass defaults: `numHistoryShards: 512`, one replica per Temporal service, Harbor-like CNPG sizing, conservative Temporal resource requests, chart-managed `default` Temporal namespace, and backup as a pre-durable-workflows gate.
- [x] Draft `kubernetes/apps/temporal/` with `temporal-config` and `temporal` Kustomizations.
- [x] Add `ingress-tailscale.yaml` for `https://temporal.<tailnet-name>.ts.net`, backed by `Service/temporal-web:8080`.
- [x] Render the chart locally with the draft HelmRelease values and inspect the schema Job, namespace Job, ServiceMonitors, Deployments, Services, and Tailscale Ingress.
- [x] Run local YAML and Kustomize checks.
- [x] Request operator approval for the first Flux reconcile.
- [x] Reconcile in order and verify CNPG, schema Job completion, Temporal pods, Tailscale UI route, ServiceMonitors, and a Temporal namespace-list command.
- [x] Verify `https://temporal.<tailnet-name>.ts.net` from a Tailscale-connected client: the Web UI shell loads, namespaces API lists `temporal-system` and `default`, and the `default` workflow list route/API responds.
- [ ] Add a short Docusaurus note if Temporal becomes a maintained Anton service.

## Validation Loop

Local checks before commit:

```sh
yq . kubernetes/apps/temporal/**/*.yaml
kustomize build kubernetes/apps/temporal
helm template temporal temporal --repo https://go.temporal.io/helm-charts -f <draft-values>
```

Read-only live checks before reconcile:

```sh
flux get ks -n databases
flux get ks -n network
flux get ks -n observability
kubectl get clusters.postgresql.cnpg.io -A
flux get hr -A
```

Post-reconcile checks after explicit operator approval:

```sh
flux get ks -n temporal
flux get hr -n temporal
kubectl -n temporal get cluster,job,pods,secrets,servicemonitor,ingress
kubectl -n temporal describe ingress temporal
kubectl -n temporal exec deploy/temporal-admintools -- temporal operator namespace list
```

Browser check after the Tailscale Ingress is admitted:

```text
Open https://temporal.<tailnet-name>.ts.net on a Tailscale-connected device.
Confirm the Web UI loads, lists namespaces, and shows the Workflows view for a namespace.
```

## Open Decisions

- `numHistoryShards` is now locked at `512` for this deployment; changing it requires a fresh Temporal deployment.
- Choose the backup target and restore drill before running durable workflows. Use the Harbor Postgres backup plan as the closest precedent.
- Choose whether a LAN-only `envoy-internal` route adds value after the Tailscale Web UI route is working.
- Choose whether to add pod disruption policy after any Temporal service scales beyond one replica.

## Pause Conditions

- Pause for a backup decision before placing irreplaceable workflows on Temporal.
- Pause for a routing decision before exposing Temporal gRPC beyond trusted internal clients.
- Pause if the rendered chart adds CRD instances beyond `ServiceMonitor` that need new ADR 0027 dependency edges, or if an optional `HTTPRoute` is introduced without a matching `network/envoy-gateway` dependency.
- Pause if the schema Job fails against CNPG with the generated application Secret; inspect the Job logs and Postgres events before changing database privileges.

## Log

- 2026-05-22: Plan opened from a feasibility pass. Upstream Temporal chart requires external persistence; Anton already has a healthy CNPG operator and two app-owned CNPG clusters. Local render confirmed that `schema.useHelmHooks: false` produces a normal schema Job and that `createDatabase: false` suppresses database-creation init containers while preserving schema-management containers.
- 2026-05-22: Reshaped the plan with an explicit outcome block, positive implementation direction, dependency contract, database contract, validation loop, open decisions, and pause conditions.
- 2026-05-22: Added Web UI access as a required deliverable: expose `Service/temporal-web:8080` through a Tailscale operator Ingress at `https://temporal.<tailnet-name>.ts.net` and validate the UI against Temporal's namespace/workflow views.
- 2026-05-22: Implemented the initial manifest set under `kubernetes/apps/temporal/`: dedicated CNPG cluster, Temporal HelmRepository/HelmRelease, Tailscale Web UI Ingress, ServiceMonitors, SQL visibility, `sslmode=require`, schema hooks disabled, chart-managed `default` Temporal namespace, and local render checks. Live reconcile remains operator-approved follow-up.
- 2026-05-22: Validation passed locally: YAML/frontmatter parse, `kustomize build kubernetes/apps/temporal`, `flux build kustomization cluster-apps --dry-run`, and `helm template temporal temporal --repo https://go.temporal.io/helm-charts --version 1.2.0 -n temporal -f /tmp/temporal-values.yaml`. Rendered Temporal Jobs have no Helm hook annotations; schema Job manages both default and visibility stores, namespace Job creates `default`, `temporal-web` exposes port 8080, and four ServiceMonitors render.
- 2026-05-22: Deployed through Flux at revision `e14415ee`: `cluster-apps`, `temporal-config`, and `temporal` all reconciled Ready; CNPG reports `temporal-postgres` healthy with 3/3 instances; HelmRelease `temporal` installed chart `1.2.0`; schema and namespace Jobs completed; all Temporal Deployments are Available; four ServiceMonitors exist; the Tailscale Ingress is admitted; in-cluster `temporal operator cluster health` returns `SERVING`; namespace listing shows `temporal-system` and `default`; HTTPS checks through the Tailscale Web UI route return 200 for the UI shell, namespace API, workflow list route, and workflow list API. Initial server components restarted twice during first boot before schema/namespace readiness settled; restart counts stayed flat after the final stability check.

## References

- Temporal deployment docs: https://docs.temporal.io/self-hosted-guide/deployment#use-helm-charts
- Temporal Web UI docs: https://docs.temporal.io/web-ui
- Temporal Helm chart repo: https://github.com/temporalio/helm-charts
- CNPG bootstrap docs: https://cloudnative-pg.io/docs/1.28/bootstrap/
- Anton CNPG operator: `kubernetes/apps/databases/cloudnative-pg/`
- Harbor CNPG precedent: `kubernetes/apps/registries/harbor-config/app/postgres-cluster.yaml`
- Tailscale access decision: `context/adrs/0012-tailscale-for-internal-remote-workload-access.md`
- Flux dependency rule: `context/adrs/0027-platform-dependson-rule.md`
- Harbor Postgres backup plan: `context/plans/0008-harbor-postgres-backup-strategy.md`
