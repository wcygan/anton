---
name: expose-service
description: Expose a workload for access. Four paths: envoy-internal (LAN via split-horizon DNS), Tailscale Ingress (internal remote HTTP with browser-trusted TLS), Tailscale Service annotation (raw TCP / non-HTTP), envoy-external + Cloudflare tunnel (genuinely public, requires explicit approval). Handles HTTPRoute authoring, DNSEndpoint for secondary domains, and per-domain cert wiring.
allowed-tools: Read, Write, Edit, Glob, Grep
---

# Expose a service

Task skill for routing traffic to a workload. Anton has three supported access paths; architecture deep-dive lives in `kubernetes/apps/network/CLAUDE.md`.

## Exposure policy (ADR 0012, amended 2026-04-17)

Pick by **who needs to reach the workload**, not by what feels easiest:

1. **LAN clients only** → `envoy-internal` HTTPRoute. Split-horizon DNS via `k8s-gateway` returns the internal LB to LAN clients.
2. **Off-LAN HTTP admin UI (browser)** → **Tailscale `Ingress`** (`ingressClassName: tailscale` + `tls.hosts: [<slug>]`). The operator provisions a Let's Encrypt cert on `<slug>.<tailnet>.ts.net`; browsers trust it natively. Recipe A in `references/tailscale.md`.
3. **Off-LAN raw TCP or non-HTTP** → **Tailscale Service annotation** (`tailscale.com/expose: "true"`). No TLS termination on the proxy — clients reach whatever the backend serves on its target port. Recipe B in `references/tailscale.md`.
4. **LAN clients AND off-LAN HTTP access** → `envoy-internal` HTTPRoute **plus** a Tailscale `Ingress` for the same workload. LAN users keep the `<app>.${SECRET_DOMAIN}` URL; remote ops use `<slug>.<tailnet>.ts.net`.
5. **Genuinely public** (audience that cannot be required to join the tailnet) → `envoy-external` HTTPRoute + Cloudflare tunnel. **Requires explicit user approval** before authoring.

Do **not** pick `envoy-external` to solve "I want to reach this from my laptop off-LAN" — that is what Tailscale is for now (ADR 0012). Shipping something public and pulling it back is irreversible (cached DNS, search engines, external referrers); Tailscale is reversible.

> ⚠️ **Throughput caveat (ADR 0012 amendment).** Tailscale proxies default to userspace netstack and on v1.84+ hit upstream bug [tailscale/tailscale#16198](https://github.com/tailscale/tailscale/issues/16198); SPA payloads over the tailnet run ~12 KB/s from a macOS peer. LAN clients are unaffected. Use Tailscale for off-LAN admin access, not for heavy data paths, until the operator ships 1.98.x. Full context in `references/tailscale.md`.

## Gateway-choice matrix

| Use case | Path | Hostname | TLS in browser? | Reaches |
| --- | --- | --- | --- | --- |
| **LAN only (default)** | `envoy-internal` HTTPRoute | `<app>.${SECRET_DOMAIN}` | Yes (cert-manager) | LAN → `k8s-gateway` DNS → cluster |
| **Off-LAN HTTP admin UI** | Tailscale `Ingress` (`ingressClassName: tailscale`) | `<slug>.<tailnet>.ts.net` | Yes (Let's Encrypt via MagicDNS) | Tailnet device → operator proxy → Service |
| **Off-LAN raw TCP / non-HTTP** | Tailscale Service annotation | `<slug>.<tailnet>.ts.net` | **No** (TCP pass-through) | Tailnet device → operator proxy → Service |
| **LAN + off-LAN HTTP** | HTTPRoute **and** Tailscale `Ingress` | both above | Yes on both | either path resolves independently |
| **Public** (requires approval) | `envoy-external` HTTPRoute | `<app>.${SECRET_DOMAIN}` | Yes (Cloudflare) | Internet → Cloudflare tunnel → cluster |
| **App on a second domain** (`${SECRET_DOMAIN_TWO}`) | `envoy-external` HTTPRoute | `<app>.${SECRET_DOMAIN_TWO}` | Yes | **also needs an explicit `DNSEndpoint` — see `references/secondary-domain.md`** |

Both envoy gateways live in namespace `network`. HTTPRoutes must set `parentRefs[].namespace: network` (cross-namespace) and `sectionName: https` (attach to the TLS listener, not port 80). Tailscale exposure does **not** use a Gateway-API HTTPRoute — it uses either a `networking.k8s.io/v1` `Ingress` (Recipe A) or a Service annotation (Recipe B).

**No bundling.** Tailscale exposure changes ship on their own PR, never mixed with Cilium / gateway / CNI changes (ADR 0012).

## Workflow

1. **Confirm the path** against the exposure policy above. If `envoy-external` is on the table, verify the user has approved public exposure before writing anything. "I want to reach it off-LAN" is a **Tailscale** reason, not an `envoy-external` reason.
2. **Author the resource(s):**
   - **HTTPRoute path** (`envoy-internal` or `envoy-external`) — write `kubernetes/apps/<ns>/<app>/app/httproute.yaml` using the template in `references/authoring-httproute.md`, or use the chart-values variant (Workflow B) if the chart supports it (bjw-s `app-template`).
   - **Tailscale Ingress (Recipe A, HTTP admin UIs)** — write an `Ingress` with `ingressClassName: tailscale` and `tls.hosts: [<slug>]`. Prefer the chart's own `ingress.*` values knob when available. Recipe: `references/tailscale.md`.
   - **Tailscale Service annotation (Recipe B, raw TCP / non-HTTP)** — add `tailscale.com/expose: "true"` and `tailscale.com/hostname: <short-slug>` to the Service's annotations. Prefer the chart's `service.annotations` knob over a Kustomize patch. Recipe: `references/tailscale.md`.
   - **Combined (HTTPRoute + Tailscale Ingress)** — do both; they are independent and don't conflict. Same-PR bundling of Tailscale work with Cilium / gateway / CNI changes is forbidden (ADR 0012).
3. **Wire any new manifest file** into `kubernetes/apps/<ns>/<app>/app/kustomization.yaml`. Annotation-only changes via chart values need no kustomization edit.
4. **If the hostname is on a secondary domain** (not `${SECRET_DOMAIN}`), also add a `DNSEndpoint` resource and verify the gateway's cert listener covers the domain — see `references/secondary-domain.md`. Skipping this is the single most common footgun in this skill. (Does not apply to Tailscale — MagicDNS handles its own.)
5. **Ship it.** `task configure` (validate + encrypt), commit + push, then `task reconcile` (or wait for the Flux interval).
6. **Verify.** Run the checks in `references/verify.md`; for the Tailscale path, also verify as documented in `references/tailscale.md`.

## Pre-commit checklist

Common:
- [ ] Path choice matches policy (LAN-only → internal; off-LAN HTTP → Tailscale Ingress; off-LAN raw TCP → Tailscale annotation; external only when explicitly approved)
- [ ] Diff contains Tailscale changes only — no Cilium / gateway / CNI edits in the same commit (ADR 0012)
- [ ] `task configure` passes

HTTPRoute path:
- [ ] `parentRefs[0].name` is `envoy-external` or `envoy-internal` (never a Service name)
- [ ] `parentRefs[0].namespace: network` set (cross-namespace attach is required)
- [ ] `parentRefs[0].sectionName: https` set (attach to TLS listener, not port 80)
- [ ] `backendRefs[].name` matches an actual `Service` in the app's namespace
- [ ] HTTPRoute (and `DNSEndpoint`, if any) listed in `app/kustomization.yaml`
- [ ] If hostname is on `${SECRET_DOMAIN_TWO}` → `DNSEndpoint` resource present
- [ ] If a new second-domain cert was added → gateway listener's `tls.certificateRefs` updated

Tailscale Ingress path (Recipe A):
- [ ] `ingressClassName: tailscale` set; no `spec.rules[].host` (operator reads `tls.hosts`)
- [ ] `tls.hosts[0]` is a short slug (no dots, no tailnet name embedded)
- [ ] `defaultBackend.service` points at an actual `Service` in the app's namespace
- [ ] Ingress listed in `app/kustomization.yaml` (or delivered via chart `ingress.*` values)
- [ ] No real tailnet name committed anywhere (use `<tailnet-name>.ts.net` placeholder in docs)

Tailscale Service annotation path (Recipe B, non-HTTP / raw TCP only):
- [ ] Annotation is on the Service the chart produces, not on a wrapping resource
- [ ] `tailscale.com/hostname` is a short slug (no dots, no tailnet name embedded)
- [ ] Workload is genuinely non-HTTP — if it's a browser UI, use Recipe A instead
- [ ] No real tailnet name committed anywhere

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
