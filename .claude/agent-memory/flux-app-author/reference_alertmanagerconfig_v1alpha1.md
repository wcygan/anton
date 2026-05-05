---
name: AlertmanagerConfig CRD is v1alpha1 only on anton
description: kube-prometheus-stack 83.5.0 ships only v1alpha1 AlertmanagerConfig; spec layout differs from v1beta1
type: reference
---

`kubectl get crd alertmanagerconfigs.monitoring.coreos.com -o jsonpath='{.spec.versions[*].name}'` → `v1alpha1` only. v1beta1 is upstream-stable but **not present** in anton's Prometheus Operator. Authoring a `monitoring.coreos.com/v1beta1` AlertmanagerConfig will fail validation.

Differences that bit me on the ntfy scaffold:

- `apiVersion: monitoring.coreos.com/v1alpha1`
- `route.matchers` is a list of `{name, value, matchType}` objects (not the v1beta1 string-matcher form). `matchType: "="` for exact, `"=~"` for regex.
- `webhookConfigs[].urlSecret` exists in v1alpha1 — preferred over `url` when the URL contains a secret (e.g., a webhook topic). Same-namespace Secret only; key holds the full URL.
- Selector default in kube-prometheus-stack 83.5.0 is `alertmanagerConfigSelector: {}` (match-all). Adding `release: kube-prometheus-stack` label is harmless and matches the convention every PrometheusRule in `observability/kube-prometheus-stack/app/` already uses.

ESO + AlertmanagerConfig urlSecret pattern (used by ntfy): the ExternalSecret's `target.template.data` builds the full URL string from a templated topic field (`http://svc.ns.svc.cluster.local/{{ .topic }}`); AlertmanagerConfig references that key via `urlSecret`. Keeps the topic out of every committed manifest.
