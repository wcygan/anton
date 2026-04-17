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

`Accepted`

> **Amended 2026-04-17** — in-place correction of factual errors in the body discovered during the first Grafana rollout. Decision direction is unchanged (Tailscale for internal remote; Cloudflare tunnel reserved for public). The mechanism described was wrong on two counts: the operator's Service-annotation recipe is a TCP pass-through with no TLS in the browser, and certs on the Ingress recipe are Let's Encrypt (via MagicDNS), not "Tailscale's CA". A throughput caveat ([tailscale/tailscale#16198](https://github.com/tailscale/tailscale/issues/16198)) has been added to Consequences, and a no-bundling operational rule has been added after a five-commit revert caused by mixing Tailscale changes with Cilium LB-mode changes.

## Context

Anton has three network entry points today: `envoy-internal` (LAN-only LB at `192.168.1.103`, served to LAN clients via `k8s-gateway` split-horizon DNS), `envoy-external` (public LB at `192.168.1.104`, fronted by a Cloudflare tunnel and by public Cloudflare DNS), and `tailscale-operator` (currently only used to proxy the Kubernetes API server so `kubectl` / `flux` / `helm` work off-LAN). The Tailscale operator's footprint is documented in `expose-service/references/tailscale.md`, which, until this ADR, explicitly forbade routing workload HTTP through Tailscale.

When the operator is off the home LAN, the `envoy-internal` path is unreachable: `k8s-gateway` is on a LAN IP (`192.168.1.102`), no Tailscale subnet router advertises `192.168.1.0/24`, and public DNS has no record for internal hostnames (by design). That leaves two bad options for off-LAN access to admin UIs: either `kubectl port-forward` for every visit (ephemeral, auth-bypassing), or push the hostname out through `envoy-external` + Cloudflare tunnel (creates a public attack surface for something that has no reason to be public, stacks Cloudflare Access on top as a second identity provider, and leaks internal hostnames to public DNS).

The Tailscale operator already holds a privileged position in the cluster (it proxies cluster-admin kubectl), every operator device already has a Tailscale client for that reason, and the operator offers two per-workload exposure recipes: an `Ingress` with `ingressClassName: tailscale` (tailnet-only reverse proxy at `<slug>.<tailnet>.ts.net` with TLS terminated on the proxy using a Let's Encrypt cert provisioned via MagicDNS — browser-trusted) and a Service annotation (`tailscale.com/expose: "true"`, same proxy but as a plain TCP forwarder with no TLS). For HTTP admin UIs consumed in a browser the Ingress recipe is what we actually want. Either recipe matches what "internal remote access" should mean in a homelab: authenticated at the device layer, no public DNS, no Cloudflare origin cert to manage, one command to reach.

## Decision

We expose any internal workload that needs off-LAN access via the Tailscale operator. HTTP admin UIs use an `Ingress` with `ingressClassName: tailscale` and `tls.hosts: [<slug>]` — the operator provisions a Let's Encrypt cert on `<slug>.<tailnet>.ts.net`, browsers trust it natively. Non-HTTP or raw-TCP workloads use a Service annotation (`tailscale.com/expose: "true"` plus `tailscale.com/hostname: "<slug>"`) — no TLS termination on the proxy, so this path is not for browser UIs. `envoy-internal` remains the LAN path (no change). `envoy-external` + Cloudflare tunnel is reserved for workloads that must be publicly reachable to an audience we cannot ask to install Tailscale — demo pages, webhook receivers, status pages, the `echo` smoke-test app.

Operationally, when a workload needs off-LAN access, the `expose-service` skill chooses in this order: **Tailscale** (internal, authenticated at device layer) → `envoy-internal` (LAN only) → `envoy-external` (requires explicit public-exposure approval). The `references/tailscale.md` doc in that skill is rewritten to describe the new supported path; the previous prohibition is lifted for Services, not for the operator's other features (`serve`, `funnel`, subnet routers) which remain out-of-scope until a separate decision.

## Alternatives considered

- **Do nothing — keep LAN-only `envoy-internal`, rely on `kubectl port-forward` off-LAN.** Rejected: port-forward is ephemeral, requires a terminal session and cluster-admin kubeconfig, and is friction-heavy enough that it discourages actually *using* the observability stack remotely. Also bypasses Grafana's own auth unpleasantly.
- **Expose internal UIs via `envoy-external` + Cloudflare tunnel with Cloudflare Access in front.** Rejected: creates public DNS records and a public TLS surface for workloads that have no reason to be public, and stacks Cloudflare Access as a second identity provider to configure and audit alongside Tailscale's ACLs. Cloudflare tunnel should carry workloads whose audience cannot be required to install Tailscale — admin UIs are not that.
- **Advertise the LAN subnet `192.168.1.0/24` via a Tailscale subnet router on one of the k8s nodes.** Rejected: leaks the full LAN into the tailnet (all hosts, not only the cluster LBs), fails to restart cleanly on node reboot because `TS_STATE_DIR=mem:` is in effect per ADR 0010, and doesn't give hostnames — clients would still have to remember `192.168.1.103`.

## Consequences

### Accepted costs

- The Tailscale operator is now in the **workload ingress path**, not only the kubectl proxy path. An operator outage now affects remote admin-UI access, not only remote kubectl. Mitigations: the operator is already the most-exercised piece of the tailnet integration, and any outage there already blocks mutating cluster work, so the incremental blast radius is narrow.
- **Tailnet device slots.** Each exposed Service consumes a device on the tailnet; Tailscale's free tier cap is 100 devices. At current growth (1–2 new admin UIs a quarter) we do not approach the cap — but this becomes a real constraint if this pattern is used for many app-level Services.
- **Certs on the Ingress recipe are Let's Encrypt, provisioned by the Tailscale operator via MagicDNS.** Browsers trust them natively — there is no private CA to distribute. The cert is bound to the MagicDNS hostname `<slug>.<tailnet>.ts.net`; third-party integrations that require a cert on a custom domain must go through `envoy-external`. The Service-annotation recipe does not terminate TLS on the proxy and therefore does not use a cert at all.
- **MagicDNS hostname hygiene.** Tailscale-exposed resources land at `<hostname>.<tailnet>.ts.net`, which embeds the tailnet name. The hard rule about not committing the tailnet name still applies: Ingress `hosts:`/`tls.hosts:` and Service annotations must use short form, and any doc referencing the URL uses the `<tailnet-name>.ts.net` placeholder.
- **Renovate-PR tax for `tailscale/k8s-operator`.** The operator's image now affects workload availability, so image bumps move from "whenever" priority to the same tier as cert-manager and cilium — merge within the normal weekly window, don't let PRs pile up.
- **Per-proxy throughput ceiling (discovered 2026-04-17 during Grafana rollout).** The operator defaults Ingress-resource proxies to userspace netstack (`TS_USERSPACE=true`), which caps throughput near 100 Kbps. Upstream bug [tailscale/tailscale#16198](https://github.com/tailscale/tailscale/issues/16198) additionally hits kernel-mode proxies on v1.84+ via oversized TCP segments past the 1280 MTU. Practical effect: SPA loads over the tailnet are slow (Grafana measured ~12 KB/s from a macOS peer); small API calls and text payloads feel fine. A `ProxyClass` for kernel-mode + privileged TUN is the prerequisite for the known workaround (`ethtool -k tailscale0 tso off gso off` inside the proxy) but does not itself fix throughput (no sidecar or postStart hook, and `ethtool` is not in the Alpine proxy image). LAN access goes through `envoy-internal` (unaffected); off-LAN users accept the slowness until upstream fix (milestone 1.98.x) lands. Revisit if the ceiling blocks a specific workflow.
- **No-bundling rule (added 2026-04-17).** Tailscale-exposure changes ship in isolation from Cilium / gateway / CNI changes. Bundling was the root cause of a five-commit revert on 2026-04-16 when a Grafana Ingress switch landed alongside a subnet-router + DSR→SNAT LB-mode change and destabilised `envoy-internal`. This is a durable operational rule, not a one-off.

### Lessons (retrospective only)

N/A — forward-looking decision.

## Follow-ups

- [ ] Validate Pattern 3 (`ingressClassName: tailscale`) on a low-risk workload before retrying Grafana — current candidate is the Hubble UI. Decision criterion: measure first-paint time over the tailnet from an off-LAN device. Pass → retry Grafana with a scoped Ingress manifest, no bundled changes. Fail → defer Grafana Ingress until operator 1.98.x (Renovate-tracked).
- [x] Rewrite `.claude/skills/expose-service/references/tailscale.md` with Recipe A (Ingress) + Recipe B (annotation) + throughput caveat (done 2026-04-17 as part of this amendment).
- [x] Extend the gateway-choice matrix in `.claude/skills/expose-service/SKILL.md` with Tailscale-Ingress and Tailscale-annotation rows (done 2026-04-17 as part of this amendment).
- [ ] Document tailnet device-count as a capacity metric the next time we touch `anton-cluster-health`.
- [ ] Revisit the throughput ceiling when Tailscale ships the TSO/GSO fix (tracked milestone 1.98.x) — if upstream doesn't land it, evaluate a custom proxy image with the `ethtool` workaround baked into the entrypoint.
