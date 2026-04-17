---
status: Accepted
date: 2026-04-16
deciders: ['@wcygan']
affects: networking
intent: concrete-need
supersedes: []
superseded-by: null
retrospective: false
---

# 0012 — Tailscale operator for internal remote workload access; Cloudflare tunnel reserved for genuinely public

> Internal-but-remote admin UIs (Grafana, Longhorn, future dashboards) go through the Tailscale operator; `envoy-external` + Cloudflare tunnel is reserved for workloads that must be publicly reachable.

## Status

`Accepted`

## Context

Anton has three network entry points today: `envoy-internal` (LAN-only LB at `192.168.1.103`, served to LAN clients via `k8s-gateway` split-horizon DNS), `envoy-external` (public LB at `192.168.1.104`, fronted by a Cloudflare tunnel and by public Cloudflare DNS), and `tailscale-operator` (currently only used to proxy the Kubernetes API server so `kubectl` / `flux` / `helm` work off-LAN). The Tailscale operator's footprint is documented in `expose-service/references/tailscale.md`, which, until this ADR, explicitly forbade routing workload HTTP through Tailscale.

When the operator is off the home LAN, the `envoy-internal` path is unreachable: `k8s-gateway` is on a LAN IP (`192.168.1.102`), no Tailscale subnet router advertises `192.168.1.0/24`, and public DNS has no record for internal hostnames (by design). That leaves two bad options for off-LAN access to admin UIs: either `kubectl port-forward` for every visit (ephemeral, auth-bypassing), or push the hostname out through `envoy-external` + Cloudflare tunnel (creates a public attack surface for something that has no reason to be public, stacks Cloudflare Access on top as a second identity provider, and leaks internal hostnames to public DNS).

The Tailscale operator already holds a privileged position in the cluster (it proxies cluster-admin kubectl), every operator device already has a Tailscale client for that reason, and the operator's `tailscale.com/expose: "true"` annotation on a Service materializes a tailnet-only reverse proxy with MagicDNS and Tailscale-issued TLS. That matches exactly what "internal remote access" should mean in a homelab: authenticated at the device layer, no public DNS, no Cloudflare origin cert to manage, one command to reach.

## Decision

We expose any internal workload that needs off-LAN access via the Tailscale operator — typically by annotating its Service with `tailscale.com/expose: "true"` (plus `tailscale.com/hostname: "<slug>"` when the default is not acceptable). `envoy-internal` remains the LAN path (no change). `envoy-external` + Cloudflare tunnel is reserved for workloads that must be publicly reachable to an audience we cannot ask to install Tailscale — demo pages, webhook receivers, status pages, the `echo` smoke-test app.

Operationally, when a workload needs off-LAN access, the `expose-service` skill chooses in this order: **Tailscale** (internal, authenticated at device layer) → `envoy-internal` (LAN only) → `envoy-external` (requires explicit public-exposure approval). The `references/tailscale.md` doc in that skill is rewritten to describe the new supported path; the previous prohibition is lifted for Services, not for the operator's other features (`serve`, `funnel`, subnet routers) which remain out-of-scope until a separate decision.

## Alternatives considered

- **Do nothing — keep LAN-only `envoy-internal`, rely on `kubectl port-forward` off-LAN.** Rejected: port-forward is ephemeral, requires a terminal session and cluster-admin kubeconfig, and is friction-heavy enough that it discourages actually *using* the observability stack remotely. Also bypasses Grafana's own auth unpleasantly.
- **Expose internal UIs via `envoy-external` + Cloudflare tunnel with Cloudflare Access in front.** Rejected: creates public DNS records and a public TLS surface for workloads that have no reason to be public, and stacks Cloudflare Access as a second identity provider to configure and audit alongside Tailscale's ACLs. Cloudflare tunnel should carry workloads whose audience cannot be required to install Tailscale — admin UIs are not that.
- **Advertise the LAN subnet `192.168.1.0/24` via a Tailscale subnet router on one of the k8s nodes.** Rejected: leaks the full LAN into the tailnet (all hosts, not only the cluster LBs), fails to restart cleanly on node reboot because `TS_STATE_DIR=mem:` is in effect per ADR 0010, and doesn't give hostnames — clients would still have to remember `192.168.1.103`.

## Consequences

### Accepted costs

- The Tailscale operator is now in the **workload ingress path**, not only the kubectl proxy path. An operator outage now affects remote admin-UI access, not only remote kubectl. Mitigations: the operator is already the most-exercised piece of the tailnet integration, and any outage there already blocks mutating cluster work, so the incremental blast radius is narrow.
- **Tailnet device slots.** Each exposed Service consumes a device on the tailnet; Tailscale's free tier cap is 100 devices. At current growth (1–2 new admin UIs a quarter) we do not approach the cap — but this becomes a real constraint if this pattern is used for many app-level Services.
- **Certs are Tailscale-issued, not cert-manager-issued.** Fine for internal UIs consumed in a browser that already trusts Tailscale's CA. Not suitable for third-party integrations that require a public CA cert — those must go through `envoy-external`.
- **MagicDNS hostname hygiene.** Tailscale-exposed Services land at `<hostname>.<tailnet>.ts.net`, which embeds the tailnet name. The hard rule about not committing the tailnet name still applies: Service annotations must set hostnames in short form, and any doc referencing the URL uses the `<tailnet-name>.ts.net` placeholder.
- **Renovate-PR tax for `tailscale/k8s-operator`.** The operator's image now affects workload availability, so image bumps move from "whenever" priority to the same tier as cert-manager and cilium — merge within the normal weekly window, don't let PRs pile up.

### Lessons (retrospective only)

N/A — forward-looking decision.

## Follow-ups

- [ ] Expose Grafana via Tailscale annotation on the kps-managed Service (first concrete application).
- [ ] Rewrite `expose-service/references/tailscale.md` to describe the supported annotation recipe and remove the blanket prohibition.
- [ ] Extend the gateway-choice matrix in `expose-service/SKILL.md` with a third row for Tailscale.
- [ ] Document tailnet device-count as a capacity metric the next time we touch `anton-cluster-health`.
