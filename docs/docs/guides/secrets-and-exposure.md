---
title: Secrets and service exposure
---

# Secrets and service exposure

A Service is never exposed by default. To reach it from outside the cluster, you declare a route on a gateway that matches the audience. To give it credentials, you declare where they come from. This guide helps you pick both.

## Choose an exposure path

| Audience | Path | You declare |
| --- | --- | --- |
| LAN clients | Envoy internal gateway, resolved by split-horizon DNS | An `HTTPRoute` on the internal gateway |
| The public internet | Cloudflare DNS and the shared tunnel to Envoy's external gateway | An `HTTPRoute` on `envoy-external`; for a non-primary domain, also a `DNSEndpoint` |
| Operators over Tailscale | Tailscale ingress | A Tailscale ingress for the service |

Public and private listeners are separate trust boundaries. Every public service uses the one shared tunnel; apps do not run their own `cloudflared` ([ADR 0023](../decisions/0023-shared-cloudflare-tunnel-only.md)). Externally routed apps also carry default-deny network policies ([ADR 0029](../decisions/0029-restore-pod-security-isolate-public-workloads.md)).

## Choose a secret source

| Secret | Mechanism |
| --- | --- |
| Infrastructure values committed to the repository | SOPS-encrypted with age; edit through `sops <file>` |
| Application credentials | External Secrets Operator, fed by the 1Password SDK |

Never commit cleartext values. To diagnose delivery, check the `ExternalSecret` conditions and the target Secret's metadata, not its data.

## Before you author a route or secret

Start with the `anton-repo-conventions` skill and the exposure-specific skill (`expose-service`). Confirm each of these:

- The gateway reference and route parent.
- Which controller owns the DNS record.
- The TLS issuer.
- The authentication boundary.
- The secret source.

DNS provider updates and live credential operations have their own approval and verification steps. A route that is accepted in the cluster can still be unreachable if public DNS points somewhere else; see the [DNS ownership record](../records/dns-and-monitoring-lessons.md).
