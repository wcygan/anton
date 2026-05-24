# Goldilocks

Goldilocks is Anton's recommendation-only resource sizing UI. It creates
VerticalPodAutoscaler objects for explicitly labelled namespaces, then displays
CPU and memory request recommendations from the VPA recommender.

## Access

Use the Tailscale hostname:

```sh
https://goldilocks.<tailnet-name>.ts.net
```

The committed Ingress uses `ingressClassName: tailscale` and the short TLS host
`goldilocks`. Do not add Cloudflare, public DNS, or `envoy-external` exposure
for this app.

## Scope

Goldilocks watches only namespaces labelled with:

```yaml
goldilocks.fairwinds.com/enabled: "true"
```

Initial canaries:

- `default`
- `bakery-site`

Do not enable `goldilocks.fairwinds.com/vpa-update-mode=auto` without a new
operator decision. The chart installs VPA recommender only; the updater and
admission controller are disabled so workloads are not evicted or resized
automatically.

## Verification

Local structural checks:

```sh
yq . kubernetes/apps/observability/goldilocks/ks.yaml \
  kubernetes/apps/observability/goldilocks/app/kustomization.yaml \
  kubernetes/apps/observability/goldilocks/app/helmrepository.yaml \
  kubernetes/apps/observability/goldilocks/app/helmrelease.yaml \
  kubernetes/apps/observability/goldilocks/app/ingress.yaml

kubectl kustomize kubernetes/apps/observability/goldilocks/app \
  | kubectl apply --dry-run=client -f -
```

Live read-only checks after Flux applies the app:

```sh
flux get ks -A | rg goldilocks
flux get hr -A | rg goldilocks
kubectl -n observability get deploy,svc,ingress | rg goldilocks
curl -I https://goldilocks.<tailnet-name>.ts.net
```
