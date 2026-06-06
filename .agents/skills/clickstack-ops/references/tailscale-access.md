# ClickStack Tailscale Access

Use this reference when HyperDX must be reached off-LAN or login redirects to `localhost`.

## Problem Shape

HyperDX needs two separate fixes for off-LAN use:

1. Reachability: the `envoy-internal` HTTPRoute is LAN-only.
2. Login redirects: HyperDX defaults `FRONTEND_URL` to `http://localhost:3000`, which breaks off-box login.

Reachability without `FRONTEND_URL` still fails at login. `FRONTEND_URL` without Tailscale exposure still leaves off-LAN clients unable to reach the service.

## Current Fix

### Tailscale Ingress

`kubernetes/apps/clickstack/hyperdx-tailscale-ingress/app/ingress.yaml` defines a Tailscale `Ingress`:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: hyperdx
  namespace: clickstack
spec:
  ingressClassName: tailscale
  tls:
    - hosts:
        - hyperdx
  defaultBackend:
    service:
      name: clickstack-app
      port:
        number: 3000
```

The Tailscale operator appends the tailnet suffix at runtime. The committed manifest must contain only the short host `hyperdx`.

### HyperDX FRONTEND_URL

`kubernetes/apps/clickstack/clickstack-app/app/helmrelease.yaml` sets:

```yaml
hyperdx:
  config:
    FRONTEND_URL: "https://hyperdx.${TAILNET_SUFFIX}"
```

`${TAILNET_SUFFIX}` comes from SOPS-encrypted `cluster-secrets` via Flux `postBuild.substituteFrom`. Never commit the literal tailnet name.

## Find The Live URL

```sh
kubectl get ingress hyperdx -n clickstack
kubectl get pods -n tailscale | rg ts-hyperdx
tailscale status | rg -i hyperdx
```

The first command's address should resolve to `hyperdx.<tailnet-name>.ts.net`.

## Verify End-To-End

Check the live pod has the expected frontend URL:

```sh
kubectl exec -n clickstack deploy/clickstack-app -c app -- printenv FRONTEND_URL
```

Check login from a tailnet client:

```sh
URL="https://$(kubectl get ingress hyperdx -n clickstack -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')"
curl -sS -o /dev/null -w "%{http_code} final=%{url_effective}\n" -L "$URL/login"
```

Expected result: HTTP 200 and the final URL remains on `hyperdx.<tailnet-name>.ts.net`; no `localhost` redirect.

## Gotchas

- `FRONTEND_URL` changes need a pod restart. `kubectl rollout restart deploy/clickstack-app -n clickstack` is a live mutation and requires approval.
- There is only one `FRONTEND_URL`. The current config canonicalizes on the tailnet origin, so LAN users who start at `hyperdx.${SECRET_DOMAIN}` may be redirected to the tailnet origin during login.
- Both exposure paths are internal. Do not add Cloudflare, `envoy-external`, or a public route for this eval.
- Removing `hyperdx-tailscale-ingress` during teardown deregisters the MagicDNS name and removes the `ts-hyperdx-*` proxy pod.
