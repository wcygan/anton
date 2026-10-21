---
status: Accepted
date: 2026-05-04
deciders: ['@wcygan']
affects: observability
intent: concrete-need
supersedes: []
superseded-by: null
retrospective: false
edition: condensed-public
slug: /decisions/0026-adopt-self-hosted-ntfy-for-alerts
---

# 0026 — Use self-hosted ntfy for alert notifications

> Deliver critical Alertmanager notifications through a self-hosted ntfy server reached over Tailscale.

_Public edition condensed on 2026-10-21; original decision date and meaning retained._

## Context

Alertmanager had no real receiver, so alerts went nowhere. A controller sat in a crash loop for several days while its alert rule fired. A recoverable workload problem became a long, unnoticed incident.

## Decision

Run one self-hosted ntfy server in the observability namespace, and route critical Alertmanager notifications to it over the cluster network.

- **Topic:** a long random topic acts as the credential, delivered from 1Password through External Secrets.
- **Client:** the iOS app reaches the server over Tailscale.
- **Push:** ntfy.sh relays a wake-up through APNs. Message contents stay on the cluster; the client fetches them from the private server.
- **Routing:** start with critical alerts only, and adjust for observed noise.

Use a small hand-written deployment rather than an unmaintained third-party chart. A small persistent cache keeps recent notifications; it is disposable and needs no backup. This path sits downstream of Alertmanager and is not a Tier-0 service.

## Alternatives considered

- **Public ntfy:** exposes alert bodies to a third party.
- **Chat or email:** adds SaaS dependencies or delivery friction.
- **A full paging service:** excessive for a single-operator cluster.

## Consequences

Self-hosting adds a small deployment and volume, and mobile push still depends on the external relay. If the relay is down, messages wait on the server until the client polls. Rotating the topic means updating both the secret and the client subscription.
