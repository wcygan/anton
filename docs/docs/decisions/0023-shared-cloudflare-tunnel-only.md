---
status: Accepted
date: 2026-04-29
deciders: ['@wcygan']
affects: networking
intent: concrete-need
supersedes: []
superseded-by: null
retrospective: false
edition: condensed-public
slug: /decisions/0023-shared-cloudflare-tunnel-only
---

# 0023 — Use one shared Cloudflare Tunnel for public ingress

> Route every Cloudflare-fronted public service through one shared, Flux-managed tunnel and `envoy-external`.

_Public edition condensed on 2026-10-21; original decision date and meaning retained._

## Context

A redeployed application was healthy in the cluster but unreachable from the internet, because its DNS record still pointed at an inactive per-app Cloudflare Tunnel. External DNS would not take ownership of a record it did not create, so the stale entry outlived the application. Whenever an app owns its own tunnel, hostname mapping, DNS record, and credential, any of them can be orphaned this way.

## Decision

All Cloudflare-fronted public services use the single Flux-managed shared tunnel and the `envoy-external` gateway. To publish a service:

1. Add an `HTTPRoute` attached to `envoy-external`.
2. For a non-primary domain, add a `DNSEndpoint` that targets the shared public hostname.

The shared listener's existing certificate serves the route.

Applications must not run their own `cloudflared`, register separate tunnels, add per-app Public Hostname mappings, or keep per-app tunnel credentials. A case that needs a separate account or an unsupported origin protocol needs a successor decision. [ADR 0012](0012-tailscale-for-internal-remote-workload-access.md) still separates public exposure from private remote access.

## Alternatives considered

- **Per-app tunnels with cleanup checklists:** more components, same stale-record failure.
- **Per-app records managed by external-dns:** same problem.
- **A second shared tunnel for environment separation:** outside the current single-cluster need.

## Consequences

The shared tunnel is a common failure point for public ingress, though it already played that role and scales across connections. Legacy per-app tunnels and records needed one-time cleanup. New services get one consistent, GitOps-managed path for routes and DNS ownership.
