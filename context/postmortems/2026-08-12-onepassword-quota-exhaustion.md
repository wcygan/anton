---
date: 2026-08-12
severity: high
component: external-secrets / 1Password SDK
detected: 2026-08-12, exact onset unknown
mitigated: 2026-08-12
resolved: 2026-08-12
related-commits: [225e8c7d, 5c174551, 1dcecb9e, 34042dde, 2fe3bf84, 6210cd52]
---

# 2026-08-12 - 1Password quota exhaustion

## Summary

Anton exhausted the shared 1Password service-account daily allowance. ESO could not read new values after the account counter reached its limit.

The previous design scheduled 13 ExternalSecrets each hour. The resources contained 42 direct field references.

That schedule created a nominal 1,008 field operations each day. It left no capacity for retries, restarts, validation, or operator activity.

Retry traffic accelerated the exhaustion. Existing Kubernetes Secrets kept their last known values, but new values could not materialize.

## Impact

- ESO could not fetch new or changed values from 1Password.
- Flux dependencies that required new Secrets could not become ready.
- Existing workloads continued with their last materialized Secret values.
- Secret changes waited for the shared daily counter to reset.

## Detection

The 1Password rate-limit response showed these states:

- The inspected token had unused hourly read and write counters.
- The account daily counter used all 1,000 requests.
- The account counter had no remaining daily capacity.

The unused token counter did not prove that the token made no earlier requests. The command reports current counters, not a historical ledger.

## Root cause

The hourly refresh schedule exceeded the account budget before failure traffic.

The calculation was:

```text
42 direct field references x 24 hourly refreshes = 1,008 operations each day
```

The account allowance was 1,000 daily requests. All service-account tokens shared that daily account pool.

## Contributing factors

- Every ExternalSecret used the same hourly schedule.
- The controller had no configured SDK cache.
- Invalid references could reach reconciliation.
- Retries repeated failed provider work.
- Controller restarts cleared in-memory state.
- No repository contract reserved daily capacity.
- No dashboard showed the rolling daily request proxy.

## Resolution

The repair introduced these controls:

- ESO was upgraded to chart 2.9.0.
- One controller replica processes one reconcile at a time.
- The SDK cache stores 100 read results for five minutes.
- Stable secrets refresh every 24 hours.
- Development secrets refresh only after an explicit change.
- A force-refresh task supports fast development work.
- A static contract approves references, target keys, and refresh classes.
- The contract rejects estimates above 250 scheduled operations each day.
- Admission policy rejects invalid references before controller reconciliation.
- Grafana shows provider traffic, errors, store health, and controller restarts.

The 2.9.0 rollout also exposed an ESO memory limit problem. A 512 MiB limit corrected that separate rollout issue.

## Prevention

- Run `mise exec -- task contracts:validate` for every ExternalSecret change.
- Keep stable secrets on the 24-hour refresh class.
- Keep development secrets on `OnChange`.
- Use the approved force-refresh task for rapid development.
- Investigate any provider errors before they become a retry storm.
- Investigate controller restarts because they clear the in-memory cache.
- Keep the rolling daily traffic proxy below its warning threshold.
- Check the account counter before service-account token rotation.

Token rotation does not reset the shared daily account counter.

## Evidence limits

`externalsecret_provider_api_calls_count` counts ESO provider call attempts. It is a traffic proxy, not the 1Password billing ledger.

The static estimate models scheduled reference operations. It does not include retries, validation, restarts, or manual work.

Individual and Families accounts do not provide a documented historical request ledger. Support is required for exact provider attribution.

## Current sources

- Operations note: `docs/docs/notes/external-secrets-onepassword.md`
- Approved inventory: `scripts/data/external-secret-contract.json`
- Contract validator: `scripts/validate-external-secret-contract.py`
- Controller values: `kubernetes/apps/external-secrets/external-secrets/app/helmrelease.yaml`
- Store configuration: `kubernetes/apps/external-secrets/onepassword-store/app/clustersecretstore.yaml`
- Cluster dashboard: `kubernetes/apps/observability/kube-prometheus-stack/app/dashboard-cluster-health.yaml`
