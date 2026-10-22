---
status: Accepted
date: 2026-04-15
deciders: ['@wcygan']
affects: networking
intent: concrete-need
supersedes: []
superseded-by: null
retrospective: false
edition: condensed-public
slug: /decisions/0010-persistent-tailscale-node-names
---

# 0010 — Persist Tailscale node identity

> Persist Tailscale state across reboots so each node keeps one identity.

_Public edition condensed on 2026-10-21; original decision date and meaning retained._

## Context

With in-memory state, a restarted node registered as a new Tailscale device, leaving stale device records behind. Fixed hostnames with ephemeral keys could briefly collide during a reboot and break name-based administration.

## Decision

Persist Tailscale state on disk and use one-time authentication, so a restarted node reuses its existing identity. Store the reusable, preauthorized auth key in encrypted Talos environment configuration; it is used only when the state directory is empty or erased.

The original decision placed state on Talos's persistent EPHEMERAL partition, which survives ordinary reboots and upgrades.

## Alternatives considered

- **Ephemeral keys with fixed hostnames:** collide during reboots.
- **API-driven cleanup of stale devices:** needs additional credentials and fragile lifecycle hooks.
- **A dedicated user volume:** unnecessary for the expected reboot and upgrade lifecycle.

## Consequences

Identity persistence depends on preserving that partition and protecting the bootstrap key. Wiping the state requires reauthentication. This decision does not approve other Tailscale features, such as subnet routing; those need their own evaluation.

Implementation paths and network identities from the original are intentionally left out of this public edition.
