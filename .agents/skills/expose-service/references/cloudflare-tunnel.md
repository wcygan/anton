# Cloudflare Tunnel in Anton

The public ingress path. `cloudflared` runs in-cluster, establishes an outbound tunnel to Cloudflare's edge, and proxies inbound requests to the `envoy-external` gateway. No inbound firewall holes, no public LB.

Upstream docs: https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/deployment-guides/kubernetes/

Manifests: `kubernetes/apps/network/cloudflare-tunnel/app/` — `helmrelease.yaml` is the source of truth.

## Traffic flow (public request)

```
browser
  → Cloudflare edge (DNS CNAME written by external-dns)
  → Cloudflare tunnel (outbound-initiated, HTTP/2 over TCP/7844)
  → cloudflared pod in cluster
  → https://envoy-external.network.svc.cluster.local:443  (HTTP/2 origin, TLS SNI = external.${SECRET_DOMAIN})
  → envoy-external Gateway (HTTPS listener on port 443)
  → HTTPRoute match by Host header
  → app Service
```

## Key config (from the HelmRelease)

- **Transport: HTTP/2 (TCP/7844).** `TUNNEL_TRANSPORT_PROTOCOL=http2`. QUIC (UDP/7844) is blocked on this network, so the tunnel falls back to HTTP/2 over TCP. This is load-bearing — do not flip back to `quic` without first confirming UDP/7844 egress works.
- **`TUNNEL_POST_QUANTUM: false`** — must be false when the transport is `http2`; post-quantum is QUIC-only.
- **Origin: `https://envoy-external.network.svc.cluster.local:443`** for every hostname in the config. `originRequest.http2Origin: true` keeps the connection HTTP/2 end-to-end; `originRequest.originServerName` is set to `external.${SECRET_DOMAIN}` (or `external.${SECRET_DOMAIN_TWO}` for the second domain) so TLS SNI on the origin leg matches the gateway's cert.
- **Auth token**: `cloudflare-tunnel-secret` via External Secrets Operator → 1Password vault `anton`.
- **Metrics**: Prometheus on `:8080/metrics`, scraped via `ServiceMonitor`. `/ready` on the same port is the liveness/readiness probe.

## `config.yaml` ingress list

The tunnel's ingress routing is flat — one entry per `hostname` pattern, in order, with a `404` fallback at the end. Today the list covers:

```yaml
- "${SECRET_DOMAIN}"             # apex
- "*.${SECRET_DOMAIN}"           # all primary-domain hosts
- "${SECRET_DOMAIN_TWO}"         # second-domain apex
- "*.${SECRET_DOMAIN_TWO}"       # all secondary-domain hosts
- service: http_status:404       # fallback
```

Every entry points to the same `envoy-external` service — the gateway does the per-app routing from there. Adding a new *domain* (not a new app) means editing this list. Adding a new *app* does not.

## What this is **not**

- **Not a reverse proxy you configure per-app.** Per-app routing happens inside Envoy via HTTPRoute. The tunnel just forwards everything on these hostnames to one service.
- **Not the only way in.** LAN traffic skips the tunnel entirely via `envoy-internal` + split-horizon DNS. The tunnel exists only for public access.
- **Not responsible for DNS.** `external-dns` (see `cloudflare-dns/`) creates the CNAME records at Cloudflare. The tunnel connector only handles the data path once DNS has resolved.

## Common failures

| Symptom | Likely cause |
| --- | --- |
| `cloudflared` stuck in CrashLoopBackOff at startup | ESO did not populate `cloudflare-tunnel-secret`; check `ExternalSecret` status |
| Tunnel up but public request returns 404 | Hostname missing from `config.yaml` ingress list, or DNS points somewhere else |
| Tunnel up but public request returns 530 / 502 | Origin TLS mismatch (`originServerName` wrong), or `envoy-external` ClusterIP not reachable |
| Tunnel flapping | Check egress for TCP/7844 to Cloudflare — if that is also blocked, public ingress is simply not available on this network |
