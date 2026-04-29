---
status: Accepted
date: 2026-04-29
deciders: ['@wcygan']
affects: networking
intent: concrete-need
supersedes: []
superseded-by: null
retrospective: false
---

# 0023 — All public ingress on anton uses the shared cloudflare-tunnel; per-app sidecar tunnels are forbidden

> Anton has exactly one Cloudflare Tunnel (`kubernetes`), managed by Flux at `kubernetes/apps/network/cloudflare-tunnel/`. New apps that need public exposure attach to it via `HTTPRoute` (parentRef `envoy-external`) plus a `DNSEndpoint` for any non-primary domain — they MUST NOT run their own `cloudflared` sidecar or register their own tunnel. Per-app tunnels become future orphans whose stale DNS records silently break later deploys.

## Status

Accepted

## Context

Anton's public ingress topology since plan 0001's bootstrap is intentionally minimal: one Cloudflare Tunnel running as a Flux-managed Deployment in the `network` namespace, terminating into `envoy-external` (Gateway API), which routes to per-app `HTTPRoute`s. ADR 0012 codified the higher-level "Cloudflare tunnel reserved for genuinely public; Tailscale operator for off-LAN admin" split. ADR 0012 did NOT address the question of how many Cloudflare tunnels the cluster runs.

On 2026-04-29 a redeploy of csgoplant onto anton failed end-to-end with Cloudflare error 1033 on `cs2plant.example.com` despite the cluster-side stack reporting healthy: pods Ready, HTTPRoute `Accepted=True`, DNSEndpoint resource present, app's own `/api/health` returning `{"status":"healthy"}`. The cause was discovered by querying the Cloudflare DNS API directly (orange-cloud-proxied records hide the true CNAME target from `dig`):

```
cs2plant.example.com CNAME → <orphan-uuid>.cfargotunnel.com  (proxied=true)
```

That UUID was not the shared `kubernetes` tunnel. It was a stale per-app tunnel named `csgoplant`, created on 2026-02-11 for an earlier incarnation of the app that ran with its own `cloudflared` sidecar (`k8s/cloudflared-deployment.yaml` + an ESO entry for `CLOUDFLARE_TUNNEL_TOKEN`). When that earlier deploy was decommissioned, four artifacts were left behind:

1. The tunnel registration in Cloudflare (`cloudflared tunnel list` showed it with 0 active connections).
2. The Public Hostname mapping in Cloudflare's Zero Trust dashboard.
3. The auto-created CNAME `cs2plant.example.com → <orphan>.cfargotunnel.com`.
4. The 1Password token entry for the tunnel.

`external-dns` saw the foreign CNAME (no `k8s.cname-…` TXT ownership marker) and silently refused to overwrite it under `policy: sync`. The new DNSEndpoint resource was applied to the cluster but never reached Cloudflare. Public requests followed the foreign CNAME to a tunnel with no live cloudflared on the other side, and Cloudflare returned 1033.

Recovery took one Cloudflare API DELETE call; once the foreign CNAME was gone, `external-dns` republished the correct record on its next 1-minute sync, and the deploy worked. Total wasted operator time was real but small. The deeper concern is that **the same failure mode is latent in every per-app tunnel ever created** — not just csgoplant's. The same triage of stale tunnels surfaced two more orphans in the account (`app-template-example`, `devchat-prod`) with corresponding foreign CNAMEs on a third-party domain.

The pattern that produces orphans is:

1. App is deployed with its own `cloudflared` sidecar Deployment, talking to a tunnel whose token is stored in 1Password.
2. Operator (or an automated flow) adds the app's hostname as a "Public Hostname" on that tunnel via Cloudflare's Zero Trust UI. Cloudflare auto-creates the CNAME.
3. App is later moved or retired. Manifests are deleted; the cluster-side cloudflared sidecar stops; the tunnel becomes inactive but stays registered.
4. The DNS record stays bound to the inactive tunnel.
5. Months later, the operator (or a different person, or future-self) tries to reuse the same hostname for a new deploy. `external-dns` refuses to overwrite the foreign record. Failure is silent at INFO log level.

The shared `kubernetes` tunnel does not produce orphans because (a) its DNS records (`external.<domain>`) are managed by an `external-dns`-owned `DNSEndpoint` resource, so they carry the ownership TXT marker and are reclaimable; and (b) per-app hostnames CNAME to the `external.<domain>` target rather than to the tunnel's `cfargotunnel.com` UUID directly, so retiring an app cleanly removes its DNS and leaves the tunnel target intact for the next app.

## Decision

All Cloudflare-fronted public ingress on anton goes through the single shared `cloudflare-tunnel` HelmRelease in `kubernetes/apps/network/cloudflare-tunnel/`. New apps that need public exposure MUST:

1. Author an `HTTPRoute` with `parentRefs[].name: envoy-external` and `sectionName: https`.
2. For any hostname on a non-primary domain, author a sibling `DNSEndpoint` whose `targets` is `external.<domain>` (a CNAME the shared tunnel's own `DNSEndpoint` already publishes).
3. Use the wildcard certificate that envoy-external's HTTPS listener already attaches for the domain.

Apps MUST NOT:

- Run a `cloudflared` Deployment, sidecar, or DaemonSet of their own.
- Register a separate Cloudflare tunnel via `cloudflared tunnel create`.
- Add Public Hostname entries on any tunnel via the Cloudflare Zero Trust dashboard (this auto-creates orphan-prone CNAMEs).
- Maintain a separate `CLOUDFLARE_TUNNEL_TOKEN` 1Password entry. The shared tunnel's token (`csgoplant/CLOUDFLARE_TUNNEL_TOKEN` in the prior pattern) should be removed from any app's `external-secret.yaml`.

The shared tunnel's ingress list is order-sensitive (apex before wildcard, catch-all 404 last). Adding a new top-level domain still requires editing it (covered by `adding-a-2nd-domain.md`); adding a new app under an already-onboarded domain does not.

## Alternatives considered

- **Allow per-app tunnels with a strict decommission checklist.** Rejected. Process discipline is the wrong layer to fix this; the failure is silent at the next deploy, not at decommission, so the operator who feels the pain is not the operator who skipped the cleanup. The orphan-DNS-record question is also independent of whether the tunnel itself is cleaned up, because Cloudflare's Public Hostname auto-CNAME outlives the tunnel registration.
- **Allow per-app tunnels with the policy that they MUST author their CNAMEs as `DNSEndpoint` resources rather than via the Zero Trust dashboard.** Better than (1) but still rejected: it adds a per-app `cloudflared` Deployment to operate, monitor, age out, and renovate. The shared tunnel already exists, has 4 active edge connections, has stable resource bounds, and is in the upgrade path. Splitting ingress across N tunnels is more moving parts for no operational benefit.
- **Run a second shared tunnel for staging vs production isolation.** Out of scope for anton (single homelab cluster, no staging/production split). Worth revisiting if the cluster ever bifurcates.
- **Status quo (no policy).** Rejected — that is what produced the 2026-04-29 incident and the two latent orphans (`app-template-example`, `devchat-prod`) still in the account at the time of writing.

## Consequences

### Accepted costs

- Apps that genuinely need a per-app tunnel (e.g. for a different Cloudflare account, or for a non-HTTP origin protocol the shared tunnel can't proxy) have no escape hatch under this ADR. If that need ever arises, write a successor ADR rather than a one-off exception. Today no app has that need.
- The shared tunnel becomes a single point of failure for all public ingress. It's already that today; the ADR codifies what was already true. Mitigation: cloudflared scales horizontally — `replicas` can be raised and rolled independently. Cloudflare's edge load-balances across active connections automatically.
- Decommissioning an app that previously ran its own tunnel still requires cleaning up the legacy tunnel + DNS records. That is one-time work per legacy app, not ongoing.

### Renovate-PR tax

None — no new component, no new chart.

### Restore-runbook obligation

Existing runbook for the shared tunnel (rotate `CLOUDFLARE_TUNNEL_TOKEN` via the `rotate-credential` skill) covers all public ingress under this ADR.

## Follow-ups

- [x] Delete the three latent orphan tunnels in the Cloudflare account (`csgoplant`, `app-template-example`, `devchat-prod`, all 0 connections). Done 2026-04-29 immediately after this ADR was written.
- [ ] Decide and act on the two foreign CNAMEs that pointed at the deleted orphan tunnels (the `chat.*` and `todo.*` records on the third-party domain). Now that the tunnels are gone, those subdomains will return 1033 indefinitely until the records are removed or repointed at `external.<domain>`.
- [ ] Consider scheduling a monthly Cloudflare zone audit (a `/schedule`-d agent) that lists DNS records pointing to `*.cfargotunnel.com` whose UUIDs are not in the current `cloudflared tunnel list` active set, and reports orphans. Defense-in-depth — does not replace the policy in this ADR but catches drift if the policy is ever bypassed.
