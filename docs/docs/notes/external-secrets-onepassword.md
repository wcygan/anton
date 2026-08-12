---
sidebar_position: 8
---

# External Secrets and 1Password

Anton uses 1Password as the human-facing secret authority. Kubernetes Secrets remain the workload interface.

## Architecture

```text
1Password vault anton
  -> 1Password SDK ClusterSecretStore
  -> External Secrets Operator
  -> Kubernetes Secret
  -> workload
```

The `ClusterSecretStore` name is `onepassword-connect` for compatibility. Anton does not deploy a 1Password Connect server.

ESO uses a service-account token from the SOPS-encrypted `onepassword-sdk-token` Secret. Keep SOPS as the bootstrap and recovery path.

Existing Kubernetes Secrets preserve the last known values during a provider outage. New values cannot materialize until ESO recovers.

## Quota incident

The previous configuration refreshed 13 ExternalSecrets every hour. Those resources contained 42 direct field references.

The nominal schedule was 1,008 field operations each day. This schedule exceeded the 1,000-request shared daily allowance before retries.

Failed reconciles, controller restarts, and cold cache reads consumed more capacity. The shared account counter reached its daily limit.

The account limit blocked new secret materialization. Existing Kubernetes Secrets continued to serve their last known values.

ESO metrics show provider call attempts. They do not provide the exact 1Password billing ledger.

See `context/postmortems/2026-08-12-onepassword-quota-exhaustion.md` for the evidence and limitations.

## Current safeguards

Anton applies these controls:

- ESO chart 2.9.0 runs one controller replica.
- The controller processes one reconcile at a time.
- The experimental SDK cache stores 100 read results for five minutes.
- The controller has a 512 MiB memory limit.
- Stable secrets use `refreshPolicy: Periodic` with `refreshInterval: 24h`.
- Development secrets use `refreshPolicy: OnChange`.
- The approved reference contract limits scheduled operations to 250 each day.
- Admission policy rejects invalid store names, reference shapes, and refresh classes.
- Grafana shows request traffic, errors, store health, and controller restarts.

The cache absorbs duplicate reads and short retry bursts. It does not reduce reads after its five-minute TTL expires.

## Add or change a reference

1. Add the item and fields to the `anton` vault.
2. Use the combined key form `<item>/<field>`.
3. Set `anton.wcygan.net/secret-refresh-class`.
4. Set the matching refresh policy.
5. Update `scripts/data/external-secret-contract.json`.
6. Run `mise exec -- task contracts:validate`.
7. Review the scheduled operation estimate.

Use this stable shape:

```yaml
metadata:
  annotations:
    anton.wcygan.net/secret-refresh-class: stable
spec:
  refreshPolicy: Periodic
  refreshInterval: 24h
```

Use this development shape:

```yaml
metadata:
  annotations:
    anton.wcygan.net/secret-refresh-class: development
spec:
  refreshPolicy: OnChange
```

Do not use `remoteRef.property` with the SDK provider. Use the combined key in `remoteRef.key`.

## Force one development refresh

Run the approved task after a 1Password change:

```sh
mise exec -- task external-secrets:force-refresh \
  NAMESPACE=<namespace> NAME=<external-secret>
```

This task changes one ExternalSecret annotation. It prompts before the live mutation.

A refreshed Kubernetes Secret does not always restart its workload. Check each workload activation method separately.

## Monitor traffic

Open the `Cluster Health Glance` dashboard. Use the `External Secrets and 1Password` section.

The section includes these panels:

- `1Password SDK Calls per 5m` shows bursts by call and status.
- `1Password SDK Rolling 24h Operations` shows the daily traffic proxy.
- `1Password SDK Errors (15m)` shows failed provider calls.
- `ESO Controller Restarts (24h)` shows cache-reset risk.
- `ClusterSecretStore Ready` shows provider readiness.

The packaged ESO dashboard gives detailed reconciliation views.

Use this PromQL query for a rolling daily proxy:

```promql
sum(increase(externalsecret_provider_api_calls_count[24h]))
```

Use this query for five-minute traffic by operation and status:

```promql
sum by (call, status) (increase(externalsecret_provider_api_calls_count[5m]))
```

## Respond to quota exhaustion

1. Check the shared account counter.

```sh
op service-account ratelimit <service-account-name-or-id> --format json
```

2. Check the Grafana request and error panels.
3. Check ESO controller restarts and memory events.
4. Check ExternalSecret and store conditions.
5. Stop unapproved retry sources before forcing a refresh.
6. Wait for the shared daily counter to reset.

Token rotation does not reset the shared account daily counter. A new token only provides a separate hourly allowance.

Never copy a service-account token or secret value into logs, tickets, or screenshots.

## Sources of truth

- Store configuration: `kubernetes/apps/external-secrets/onepassword-store/app/clustersecretstore.yaml`
- Controller configuration: `kubernetes/apps/external-secrets/external-secrets/app/helmrelease.yaml`
- Admission policy: `kubernetes/apps/external-secrets/external-secrets/app/admission-policy.yaml`
- Approved references: `scripts/data/external-secret-contract.json`
- Contract validator: `scripts/validate-external-secret-contract.py`
- Dashboard: `kubernetes/apps/observability/kube-prometheus-stack/app/dashboard-cluster-health.yaml`
- Force-refresh task: `Taskfile.yaml`

Vendor references:

- [ESO 1Password SDK provider](https://external-secrets.io/latest/provider/1password-sdk/)
- [ESO refresh policies](https://external-secrets.io/latest/api/externalsecret/)
- [ESO metrics](https://external-secrets.io/latest/api/metrics/)
- [1Password service-account limits](https://www.1password.dev/service-accounts/rate-limits/)
