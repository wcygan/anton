# ClickStack — OPERATIONS

Health checks, reconcile/debug via the anton Flux flow, and credential rotation. All read-first; mutating steps are committed-and-reconciled, not `kubectl apply`. Verify kube context before any mutating command (see root CLAUDE.md).

## Health checks

Walk top-down: Flux releases → operators → custom resources → workloads → pods. The two-phase install means a problem in the operators phase masks everything downstream — check it first.

```sh
# 1. Flux view — both Kustomizations and both HelmReleases Ready?
flux get ks -A | grep clickstack
flux get hr -n clickstack

# 2. Operators present? (ClickHouse operator + MongoDB MCK)
kubectl -n clickstack get deploy
kubectl get crd | grep -iE 'clickhouse|keeper|mongodb'
#   expect: clickhouseclusters / keeperclusters (ClickHouse operator),
#           mongodbcommunity (MongoDB MCK)

# 3. Custom resources reconciled by the operators
kubectl -n clickstack get clickhousecluster,keepercluster,mongodbcommunity
kubectl -n clickstack describe clickhousecluster   # status/conditions on stall

# 4. Workloads
kubectl -n clickstack get deploy,sts,pods -o wide
#   clickstack-app  = HyperDX Deployment (the -app suffix is the chart helper)
#   ClickHouse / Keeper / MongoDB render as StatefulSets
#   otel collector is a Deployment

# 5. HTTPRoute accepted + backend resolvable
kubectl -n clickstack get httproute hyperdx -o wide

# 6. ESO Secret materialized (gates the HelmRelease valuesFrom)
kubectl -n clickstack get externalsecret clickstack-credentials
kubectl -n clickstack get secret clickstack-credentials
```

**Per-component sanity:**

```sh
# ClickHouse responds (resolve the pod/sts name first from step 4)
kubectl -n clickstack exec <clickhouse-pod> -- clickhouse-client --query "SELECT 1"

# Keeper quorum (single replica for this eval — just confirm it's up)
kubectl -n clickstack logs <keeper-pod> --tail=50

# MongoDB up (HyperDX stores users/dashboards here)
kubectl -n clickstack logs <mongodb-pod> -c mongod --tail=50

# HyperDX + collector logs
kubectl -n clickstack logs deploy/clickstack-app --tail=100
kubectl -n clickstack logs deploy/<otel-collector> --tail=100
```

**Resource cost (ADR 0028 success criterion 2 — "is ClickHouse too heavy?"):** record real usage over the eval.

```sh
kubectl -n clickstack top pods
```

Compare ClickHouse + Keeper + MongoDB + HyperDX + collector against what a VictoriaLogs single binary would cost. Note it against criterion 2.

## Reconcile and debug

Standard anton Flux flow. Reconcile the operators phase first (the app phase `dependsOn` it):

```sh
flux reconcile ks clickstack-operators -n flux-system --with-source
flux reconcile ks clickstack-app -n flux-system
# or the repo shortcut:
task reconcile
```

Debug ladder when something is stuck:

1. **App phase won't start / shows dependency-not-ready** → the operators Kustomization (`wait: true`) hasn't reported Ready. Fix operators first: `flux get hr -n clickstack`, then describe the operators HelmRelease for the failing condition.
2. **ESO Secret missing** → the app HelmRelease's `valuesFrom` can't resolve, and the `clickstack-app` ks.yaml healthCheck on the `clickstack-credentials` Secret fails. Almost always the 1Password item doesn't exist yet (see open item below) or the `onepassword-connect` ClusterSecretStore is unhealthy. `kubectl -n clickstack describe externalsecret clickstack-credentials`.
3. **CRs not reconciling** → operator pod is up but the `ClickHouseCluster`/`MongoDBCommunity` shows no status. Check the operator logs and the CR `.status`.
4. **HelmRelease values rejected** → schema/CRD-shape mismatch (e.g. the MongoDB resources path goes through `spec.statefulSet…`, not a top-level `resources` key — see the helmrelease comments). Check the HelmRelease `describe` for the Helm error.

For deep or repeating Flux stalls, hand off to the `debug-flux-reconciliation` skill or the `flux-debugger` subagent.

## Credential rotation (ESO + 1Password)

Four runtime credentials live in 1Password vault `anton`, item **`clickstack`**, consumed via the `clickstack-credentials` ExternalSecret and injected into the chart by Flux `valuesFrom` → `targetPath: hyperdx.secrets.*`.

**OPEN ITEM — first-time setup:** the 1Password item `clickstack` does not yet exist as of scaffold. Create it (do not invent values; the operator generates strong values out of band) with exactly these fields:

| 1Password field | Purpose |
| --- | --- |
| `HYPERDX_API_KEY` | HyperDX app secret / API key |
| `CLICKHOUSE_PASSWORD` | the `otelcollector` ClickHouse user password |
| `CLICKHOUSE_APP_PASSWORD` | the `app` ClickHouse user password (HyperDX → ClickHouse) |
| `MONGODB_PASSWORD` | MongoDB password |

Never write these into a `*.sops.*` file or any committed manifest — they live only in 1Password, surfaced by ESO. Log file paths, never values.

**Rotation procedure:**

1. Update the field(s) in 1Password item `clickstack`.
2. Force ESO to re-pull (or wait for the 1h `refreshInterval`):
   ```sh
   kubectl -n clickstack annotate externalsecret clickstack-credentials \
     force-sync=$(date +%s) --overwrite
   kubectl -n clickstack get secret clickstack-credentials -o jsonpath='{.metadata.resourceVersion}'
   ```
3. **The chart reads these as Helm values at template time, not live from the Secret** — so a new Secret value does not hot-reload. Trigger Flux to re-render the HelmRelease, then let the pods restart with the new values:
   ```sh
   flux reconcile hr clickstack -n clickstack --force
   ```
   If components don't pick it up, restart the consumers:
   ```sh
   kubectl -n clickstack rollout restart deploy/clickstack-app
   # ClickHouse/Keeper/MongoDB passwords are operator-managed via the CRs — a
   # password change there may require the operator to reconcile the CR; check
   # the operator logs rather than restarting StatefulSets blindly.
   ```
4. Verify: HyperDX can still reach ClickHouse (run a query) and the pods are not crash-looping.

For the durable cross-credential rotation discipline (age key, deploy key, 1Password token, Cloudflare token), use the `rotate-credential` skill — this section is ClickStack-specific only.
