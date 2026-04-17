---
name: expose-service
description: Expose a workload for access. Three paths: envoy-internal (LAN via split-horizon DNS), Tailscale (internal remote access, annotation on Service), envoy-external + Cloudflare tunnel (genuinely public, requires explicit approval). Handles HTTPRoute authoring, DNSEndpoint for secondary domains, and per-domain cert wiring.
allowed-tools: Read, Write, Edit, Glob, Grep
---

# Expose a service

Task skill for routing traffic to a workload. Anton has three supported access paths; architecture deep-dive lives in `kubernetes/apps/network/CLAUDE.md`.

## Exposure policy (ADR 0012)

Pick by **who needs to reach the workload**, not by what feels easiest:

1. **LAN clients only** → `envoy-internal` HTTPRoute. Split-horizon DNS via `k8s-gateway` returns the internal LB to LAN clients.
2. **Operator / tailnet members, off-LAN** → **Tailscale** annotation on the Service. MagicDNS at `<hostname>.<tailnet>.ts.net`, Tailscale-issued TLS, no public DNS. See `references/tailscale.md`.
3. **LAN clients AND remote operator access** → `envoy-internal` HTTPRoute **plus** Tailscale annotation on the same Service. LAN users keep the `<app>.${SECRET_DOMAIN}` URL; remote ops use the tailnet hostname. Grafana is the canonical example.
4. **Genuinely public** (audience that cannot be required to join the tailnet) → `envoy-external` HTTPRoute + Cloudflare tunnel. **Requires explicit user approval** before authoring.

Do **not** pick `envoy-external` to solve "I want to reach this from my laptop off-LAN" — that is what Tailscale is for now (ADR 0012). Shipping something public and pulling it back is irreversible (cached DNS, search engines, external referrers); Tailscale is reversible.

## Gateway-choice matrix

| Use case | Path | Hostname | Reaches |
| --- | --- | --- | --- |
| **LAN only (default)** | `envoy-internal` HTTPRoute | `<app>.${SECRET_DOMAIN}` | LAN → `k8s-gateway` DNS → cluster |
| **Tailnet (internal remote)** | Tailscale Service annotation | `<hostname>.<tailnet>.ts.net` | Tailnet device → operator proxy → Service |
| **LAN + tailnet** | HTTPRoute **and** Tailscale annotation | both of the above | either path resolves independently |
| **Public** (requires approval) | `envoy-external` HTTPRoute | `<app>.${SECRET_DOMAIN}` | Internet → Cloudflare tunnel → cluster |
| **App on a second domain** (`${SECRET_DOMAIN_TWO}`) | `envoy-external` HTTPRoute | `<app>.${SECRET_DOMAIN_TWO}` | **also needs an explicit `DNSEndpoint` — see `references/secondary-domain.md`** |

Both envoy gateways live in namespace `network`. HTTPRoutes must set `parentRefs[].namespace: network` (cross-namespace) and `sectionName: https` (attach to the TLS listener, not port 80). Tailscale exposure does **not** use an HTTPRoute — the annotation is on the Service directly.

## Workflow

1. **Confirm the path** against the exposure policy above. If `envoy-external` is on the table, verify the user has approved public exposure before writing anything. "I want to reach it off-LAN" is a **Tailscale** reason, not an `envoy-external` reason.
2. **Author the resource(s):**
   - **HTTPRoute path** (`envoy-internal` or `envoy-external`) — write `kubernetes/apps/<ns>/<app>/app/httproute.yaml` using the template in `references/authoring-httproute.md`, or use the chart-values variant (Workflow B) if the chart supports it (bjw-s `app-template`).
   - **Tailscale path** — add `tailscale.com/expose: "true"` and `tailscale.com/hostname: <short-slug>` to the Service's annotations. Prefer the chart's own `service.annotations` values knob over a Kustomize patch. Recipe: `references/tailscale.md`.
   - **Combined (HTTPRoute + Tailscale)** — do both; they are independent and don't conflict.
3. **Wire any new manifest file** into `kubernetes/apps/<ns>/<app>/app/kustomization.yaml`. Annotation-only changes via chart values need no kustomization edit.
4. **If the hostname is on a secondary domain** (not `${SECRET_DOMAIN}`), also add a `DNSEndpoint` resource and verify the gateway's cert listener covers the domain — see `references/secondary-domain.md`. Skipping this is the single most common footgun in this skill. (Does not apply to Tailscale — MagicDNS handles its own.)
5. **Ship it.** `task configure` (validate + encrypt), commit + push, then `task reconcile` (or wait for the Flux interval).
6. **Verify.** Run the checks in `references/verify.md`; for the Tailscale path, also verify as documented in `references/tailscale.md`.

## Pre-commit checklist

Common:
- [ ] Path choice matches policy (LAN-only → internal; internal remote → Tailscale; external only when explicitly approved)
- [ ] `task configure` passes

HTTPRoute path:
- [ ] `parentRefs[0].name` is `envoy-external` or `envoy-internal` (never a Service name)
- [ ] `parentRefs[0].namespace: network` set (cross-namespace attach is required)
- [ ] `parentRefs[0].sectionName: https` set (attach to TLS listener, not port 80)
- [ ] `backendRefs[].name` matches an actual `Service` in the app's namespace
- [ ] HTTPRoute (and `DNSEndpoint`, if any) listed in `app/kustomization.yaml`
- [ ] If hostname is on `${SECRET_DOMAIN_TWO}` → `DNSEndpoint` resource present
- [ ] If a new second-domain cert was added → gateway listener's `tls.certificateRefs` updated

Tailscale path:
- [ ] Annotation is on the Service the chart produces, not on a wrapping resource
- [ ] `tailscale.com/hostname` is a short slug (no dots, no tailnet name embedded)
- [ ] No real tailnet name committed anywhere (use `<tailnet-name>.ts.net` placeholder in docs)

## Canonical in-tree examples

Read the live manifest rather than a frozen copy:

- **Public, app-template inline `route:` values** (Workflow B) → `kubernetes/apps/default/echo/app/helmrelease.yaml`
- **Internal, standalone HTTPRoute** (Workflow A) → `kubernetes/apps/observability/kube-prometheus-stack/app/httproute.yaml`
- **DNSEndpoint shape** (CNAME to tunnel on a secondary domain) → `kubernetes/apps/network/cloudflare-tunnel/app/dnsendpoint.yaml`

## Further reading

| Reference | When to read |
| --- | --- |
| `references/authoring-httproute.md` | Writing the HTTPRoute YAML (Workflow A standalone, Workflow B route-in-values) |
| `references/secondary-domain.md` | Hostname on `${SECRET_DOMAIN_TWO}` or any non-primary domain |
| `references/verify.md` | After deploy, or when an HTTPRoute exists but the app is unreachable |
| `references/envoy-gateway.md` | Background on the in-cluster gateway controller (Gateway specs, LB IPs, policies) |
| `references/cloudflare-tunnel.md` | Background on the public ingress path (`cloudflared`, http2 transport, origin config) |
| `references/tailscale.md` | What Tailscale does — and does **not** — do in this cluster |

## Related skills

- Architecture / traffic flow / debug commands → `kubernetes/apps/network/CLAUDE.md`
- Pattern reference for HelmRelease / ks.yaml → `anton-repo-conventions`
- Triaging an HTTPRoute that exists but the app is unreachable → `debug-flux-reconciliation`
