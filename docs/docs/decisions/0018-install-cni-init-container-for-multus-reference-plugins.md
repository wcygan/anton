---
status: Accepted
date: 2026-04-19
deciders: ['@wcygan']
affects: networking
intent: concrete-need
supersedes: []
superseded-by: null
retrospective: false
edition: condensed-public
slug: /decisions/0018-install-cni-init-container-for-multus-reference-plugins
---

# 0018 — Install CNI reference plugins for Multus

> Install the CNI reference plugins Multus needs with Sidero's `install-cni` init container.

_Public edition condensed on 2026-10-21; original decision date and meaning retained._

## Context

Multus ([ADR 0017](0017-adopt-multus-for-longhorn-storage-network.md)) needs the reference CNI plugins, including macvlan, to configure secondary interfaces. Talos did not supply the required set through the considered system extension.

## Decision

Run the upstream Sidero `install-cni` image as an init container on the Multus DaemonSet. It copies the reference plugins into the host's CNI binary directory. Pin the image and update it through the repository's normal image tracking. The shape follows Sidero's official Multus guidance.

## Alternatives considered

- **A Talos system extension:** did not provide the required plugins.
- **A custom long-running installer:** unnecessary machinery.

## Consequences

This adds a short-lived privileged init container and ties the available plugins to that image's contents. A future NetworkAttachmentDefinition that needs a missing plugin requires an explicit change. Verify the plugins on every node, and finish the deferred network-attachment smoke test, before treating the storage mesh as operational. Revisit if Talos bundles the plugins or upstream changes the documented install method.
