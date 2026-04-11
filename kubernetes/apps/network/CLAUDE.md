# kubernetes/apps/network/

Four components that together put `envoy-external` (public, via Cloudflare tunnel) and `envoy-internal` (LAN, via split-horizon DNS) in front of every HTTPRoute in the cluster. Apps never configure networking directly — they only declare HTTPRoutes that point at one of these two gateways.

## Contents

- `envoy-gateway/` — Envoy Gateway controller plus `Gateway` definitions and the shared wildcard `Certificate` (from cert-manager); see `envoy-gateway/app/envoy.yaml` for the two Gateway specs and listener configuration
- `cloudflare-tunnel/` — `cloudflared` release bound to the `envoy-external` gateway; tunnel token is ESO-managed, HTTP/2 egress (UDP/7844 is blocked on this network)
- `cloudflare-dns/` — `external-dns` controller watching HTTPRoutes and writing CNAMEs to Cloudflare; filtered by `${cloudflare_domain}`
- `k8s-gateway/` — in-cluster DNS server at `${cluster_dns_gateway_addr}` that serves `*.${SECRET_DOMAIN}` as an A record to `${cluster_gateway_addr}` for LAN clients

## Usage

Use the `expose-service` skill to add an HTTPRoute — it chooses the correct gateway (`envoy-internal` vs `envoy-external`), wires `parentRefs`/`sectionName: https`, and handles the postBuild substitution. The `add-flux-app` skill calls it automatically when scaffolding an app that needs exposure.

**Gateway choice:** `envoy-internal` for anything that should not be on the public internet (admin UIs, dashboards, dev); `envoy-external` only when Cloudflare-fronted access is genuinely required. Changing gateway ≠ changing hostname — split-horizon DNS makes the same hostname resolve differently per client.

**Secondary domains require an explicit `DNSEndpoint` resource** — HTTPRoute annotations alone will not cause `external-dns` to create records for a non-primary domain. Full walk-through: `docs/docs/notes/adding-a-2nd-domain.md`. Before editing anything in `envoy-gateway/app/envoy.yaml` itself, confirm the change is universal across both gateways; per-app routing belongs in the app's own HTTPRoute.
