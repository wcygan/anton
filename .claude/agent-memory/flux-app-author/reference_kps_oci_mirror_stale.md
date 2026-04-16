---
name: kube-prometheus-stack OCI mirror is stale
description: prometheus-community publishes chart to ghcr.io OCI but the mirror lags far behind; use classic HelmRepository for current versions
type: reference
---

As of 2026-04-16, `oci://ghcr.io/prometheus-community/charts/kube-prometheus-stack` exists but its latest tag is **41.7.4** (from 2022-era). The current chart line (83.x) is only published to the classic Helm repo `https://prometheus-community.github.io/helm-charts`.

Verify before assuming OCI availability:
```
TOKEN=$(curl -s "https://ghcr.io/token?scope=repository:prometheus-community/charts/kube-prometheus-stack:pull" | jq -r .token)
curl -s -H "Authorization: Bearer $TOKEN" "https://ghcr.io/v2/prometheus-community/charts/kube-prometheus-stack/tags/list" | jq '.tags | map(select(contains("sig") | not) | select(contains("sha256") | not)) | sort | last'
```

Precedent for HelmRepository fallback in anton: `kubernetes/apps/storage/longhorn/app/helmrepository.yaml` (Longhorn also doesn't publish OCI). Both files should carry a header comment explaining the upstream-forced deviation from the OCIRepository preference so the next reader knows why.

Other prometheus-community charts (e.g. `prometheus`, `alertmanager` standalone) inherit the same stale-OCI pattern — check tag freshness before picking a source kind.
