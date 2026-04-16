# Envoy Gateway in Anton

The in-cluster gateway controller. Implements the Kubernetes Gateway API; in this cluster it is the **only** ingress path for workload HTTP traffic.

Upstream docs: https://gateway.envoyproxy.io/docs/

Manifests: `kubernetes/apps/network/envoy-gateway/app/` — `envoy.yaml` is the source of truth for the resources below.

## What lives here

- **`GatewayClass` `envoy`** — bound to controller `gateway.envoyproxy.io/gatewayclass-controller`, parameterized by an `EnvoyProxy` CR (2 replicas, Prometheus metrics, 180s drain timeout, gzip compression).
- **`Gateway` `envoy-internal`** — LAN-only. Cilium LB IP `192.168.1.103`. Hostname `internal.${SECRET_DOMAIN}`. HTTPS listener terminates with primary + secondary domain certs.
- **`Gateway` `envoy-external`** — public. Cilium LB IP `192.168.1.104`. Hostname `external.${SECRET_DOMAIN}`. HTTPS listener terminates with primary + secondary domain certs. `cloudflared` dials this service.
- **`BackendTrafficPolicy` `envoy`** — brotli + gzip compression, 60s HTTP request timeout, tcp keepalive.
- **`ClientTrafficPolicy` `envoy`** — TLS 1.3 minimum, HTTP/2 + HTTP/3, X-Forwarded-For trusted-hops=1, 30s request-received timeout.
- **`HTTPRoute` `https-redirect`** — attaches to the HTTP listener on both gateways and 301s to HTTPS.

## Listener model

Each gateway exposes two listeners:

| Listener | Port | Purpose |
| --- | --- | --- |
| `http` | 80 | Only hosts the `https-redirect` route. App HTTPRoutes must **not** attach here. |
| `https` | 443 | The listener every app HTTPRoute attaches to via `sectionName: https`. |

The HTTPS listener has `allowedRoutes.namespaces.from: All`, which is why HTTPRoutes can live in any namespace and still attach by using `parentRefs[].namespace: network`.

## How app HTTPRoutes attach

- `parentRefs[0].name` — the Gateway name (`envoy-internal` or `envoy-external`).
- `parentRefs[0].namespace: network` — mandatory, both gateways live in the `network` namespace.
- `parentRefs[0].sectionName: https` — picks the TLS listener. Omitting it attaches to port 80, which only serves the redirect.

## What Envoy Gateway does **not** do here

- It does not terminate any tunnel by itself — the Cloudflare-tunnel path is fronted by `cloudflared` dialing `envoy-external`'s ClusterIP service internally.
- It does not handle DNS — `external-dns` writes Cloudflare records from HTTPRoute hostnames, and `k8s-gateway` answers LAN DNS; the gateway itself only cares about Host headers.
- It does not issue certs — cert-manager does, and the Gateway listener references the resulting Secrets.

## Editing rules

- **Per-app routing belongs in the app's own HTTPRoute**, never in `envoy-gateway/app/envoy.yaml`.
- Changes to `envoy.yaml` should be *universal* (affect both gateways) — listener-wide TLS, compression, timeouts, new domain certs.
- When adding a new domain, add *both* a `Certificate` and the matching `certificateRefs` entry on the gateway listener. See `secondary-domain.md`.
