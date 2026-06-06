# ClickStack Operations

Use this reference for health checks, Flux triage, and ClickStack-specific credential rotation. Start read-only. Ask for approval before any command that changes cluster state.

## Health Checks

Walk top-down because the operators phase blocks the app phase.

```sh
flux get ks -A | rg clickstack
flux get hr -n clickstack
kubectl -n clickstack get deploy
kubectl get crd | rg -i 'clickhouse|keeper|mongodb'
kubectl -n clickstack get clickhousecluster,keepercluster,mongodbcommunity
kubectl -n clickstack get deploy,sts,pods -o wide
kubectl -n clickstack get httproute hyperdx -o wide
kubectl -n clickstack get ingress hyperdx -o wide
kubectl -n clickstack get externalsecret clickstack-credentials
kubectl -n clickstack get secret clickstack-credentials
```

Per-component checks. The log reads are read-only. The ClickHouse `exec` starts
a process inside a pod, so present it for approval unless the operator already
approved pod exec for this task:

```sh
kubectl -n clickstack exec <clickhouse-pod> -- clickhouse-client --query "SELECT 1"
kubectl -n clickstack logs <keeper-pod> --tail=50
kubectl -n clickstack logs <mongodb-pod> -c mongod --tail=50
kubectl -n clickstack logs deploy/clickstack-app --tail=100
kubectl -n clickstack logs deploy/<otel-collector> --tail=100
```

For ADR 0028 success criterion 2, record resource cost during the eval:

```sh
kubectl -n clickstack top pods
```

Compare ClickHouse, Keeper, MongoDB, HyperDX, and collector cost against the VictoriaLogs single-binary alternative.

## Reconcile And Debug

Use `debug-flux-reconciliation` for deep Flux stalls. For ClickStack, check the operators phase first:

1. `clickstack-operators` not Ready: inspect the operators HelmRelease and CRD install.
2. `clickstack-app` dependency not ready: resolve the operators Kustomization first.
3. ESO Secret missing: describe `ExternalSecret/clickstack-credentials` and verify the 1Password item exists.
4. Custom resources not reconciling: inspect operator logs and CR status.
5. Helm values rejected: inspect the HelmRelease condition for chart schema or CRD-shape mismatch.

Reconcile commands are live mutations. If needed, present this order and wait for approval:

```sh
flux reconcile ks clickstack-operators -n flux-system --with-source
flux reconcile ks clickstack-app -n flux-system
```

`task reconcile` is also a live reconcile command; do not run it without approval.

## Credential Rotation

Runtime credentials live in 1Password vault `anton`, item `clickstack`, consumed through `ExternalSecret/clickstack-credentials` and injected into Helm values:

| Field | Purpose |
| --- | --- |
| `HYPERDX_API_KEY` | HyperDX app secret / API key |
| `CLICKHOUSE_PASSWORD` | `otelcollector` ClickHouse user password |
| `CLICKHOUSE_APP_PASSWORD` | `app` ClickHouse user password for HyperDX |
| `MONGODB_PASSWORD` | MongoDB password |

The current committed `externalsecret.yaml` comments mark the 1Password item as an open setup item. Verify live status before choosing between initial creation and rotation:

```sh
kubectl -n clickstack describe externalsecret clickstack-credentials
```

Rotation or first-time setup requires operator approval because it changes credentials and live cluster state.

Approval-ready procedure:

1. Update or create the field values in 1Password. Never write values into a committed file.
2. Force ESO to re-pull, or wait for the `1h` refresh interval:

   ```sh
   kubectl -n clickstack annotate externalsecret clickstack-credentials force-sync=$(date +%s) --overwrite
   kubectl -n clickstack get secret clickstack-credentials -o jsonpath='{.metadata.resourceVersion}'
   ```

3. Re-render the HelmRelease so the `valuesFrom` data is templated again:

   ```sh
   flux reconcile hr clickstack -n clickstack --force
   ```

4. If consumers do not pick up the change, restart only the affected consumers after approval:

   ```sh
   kubectl -n clickstack rollout restart deploy/clickstack-app
   ```

5. Verify HyperDX can query ClickHouse and pods are not crash-looping.

Use `rotate-credential` for broader Anton credential discipline. This section is only the ClickStack-specific flow.
