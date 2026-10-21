---
status: Accepted
date: 2026-04-16
deciders: ['@wcygan']
affects: networking
intent: concrete-need
supersedes: []
superseded-by: null
retrospective: false
edition: condensed-public
slug: /decisions/0012-tailscale-for-internal-remote-workload-access
---

# 0012 — Tailscale for internal remote workload access

> Use the Tailscale Kubernetes operator for private remote access to internal services.

_Public edition condensed on 2026-10-21; original decision date and meaning retained._

## Context

Some internal services need to be reachable from outside the LAN. Port-forwarding is temporary and awkward for regular administration.

## Decision

Use the Tailscale Kubernetes operator for internal services that need remote access:

- **HTTP interfaces:** Tailscale ingress, with browser-trusted certificates.
- **Raw TCP services:** the operator's service exposure path, which does not terminate browser TLS.

Keep the internal gateway for LAN access. Reserve the external gateway and Cloudflare Tunnel for services meant for a public audience. [ADR 0010](0010-persistent-tailscale-node-names.md) covers stable node identity.

## Alternatives considered

- **Port-forwarding:** temporary and inconvenient.
- **Public exposure:** creates public DNS and TLS surfaces and another access policy for internal tools.
- **Subnet router:** exposes more of the LAN than needed.

Device-level Tailscale access fits private administrative interfaces.

## Consequences

Tailscale ingress and service proxying behave differently on the wire; pick the one that matches the service. A Cilium interaction can affect throughput, so keep the documented device constraint when applying this design. Keep Tailscale and Cilium changes separately reviewable.

The original body was amended to correct TLS and networking details; this edition keeps the corrected direction. This decision does not approve other operator features.
