# Post-deploy verification

Run these after `task reconcile` (or once Flux has picked up the commit).

## 1. HTTPRoute accepted

```sh
kubectl get httproute -A | rg <app>

kubectl get httproute -n <ns> <app> \
  -o jsonpath='{.status.parents[*].conditions[?(@.type=="Accepted")].status}'
# expect: True
```

If `Accepted=False`, look at `.status.parents[*].conditions[*].message` — the usual causes are a typo in `parentRefs[0].name`, a missing `namespace: network`, or `sectionName` pointing at a listener the gateway does not expose.

## 2. DNS resolves

```sh
# Public URL (Cloudflare):
dig <app>.${SECRET_DOMAIN}

# Internal split-horizon (via k8s-gateway on the LAN):
dig <app>.${SECRET_DOMAIN} @${cluster_dns_gateway_addr}
```

Public name doesn't resolve? Check `external-dns` logs:
```sh
kubectl logs -n network -l app.kubernetes.io/name=cloudflare-dns --tail=100
```
Common hits: secondary domain ignored (missing `DNSEndpoint` — see `secondary-domain.md`), or `domainFilters` not matching.

## 3. End-to-end request

```sh
curl -I https://<app>.${SECRET_DOMAIN}
```

Expected: `HTTP/2 200` (or whatever the app returns). Useful failure modes:

| `curl` outcome | Likely cause |
| --- | --- |
| DNS error / NXDOMAIN | See step 2 |
| Connection refused | Gateway not attaching the listener — re-check `sectionName: https` |
| TLS cert name mismatch | Secondary domain missing from gateway `tls.certificateRefs` (see `secondary-domain.md`) |
| 404 from `cloudflared` (public path only) | Hostname missing from `cloudflare-tunnel` config.yaml ingress list |
| 404 from Envoy | `backendRefs[].name` points at a nonexistent Service, or port mismatch |
| 502 / 503 | Backend pod not ready — check the app's own pods/logs |

## 4. Spot checks for the common traps

```sh
# All HTTPRoutes attached to the external gateway (sanity check what's public):
kubectl get httproute -A \
  -o jsonpath='{range .items[?(@.spec.parentRefs[0].name=="envoy-external")]}{.metadata.namespace}/{.metadata.name}{"\n"}{end}'

# Certs on both gateways:
kubectl get certificate -n network

# DNSEndpoint resources (should exist for every secondary-domain host):
kubectl get dnsendpoints.externaldns.k8s.io -A
```
