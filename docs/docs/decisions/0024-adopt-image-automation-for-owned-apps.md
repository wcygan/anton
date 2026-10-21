---
status: Accepted
date: 2026-05-01
deciders: ['@wcygan']
affects: compute
intent: concrete-need
supersedes: []
superseded-by: null
retrospective: false
edition: condensed-public
slug: /decisions/0024-adopt-image-automation-for-owned-apps
---

# 0024 — Use Flux image automation for owned applications

> Use Flux image automation to deploy operator-owned application images; keep Renovate for upstream artifacts.

_Public edition condensed on 2026-10-21; original decision date and meaning retained._

## Context

Renovate's periodic, reviewed pull requests suit upstream charts, third-party images, base images, and tooling. For operator-owned applications that may deploy several times a day, they are slow and add review friction. A separate private application also deployed with a local script outside GitOps, which caused drift.

## Decision

Use Flux's `image-reflector-controller` and `image-automation-controller` for owned application images. Each adopting app declares:

- an `ImageRepository`,
- an `ImagePolicy`,
- an `ImageUpdateAutomation`, and
- a setter marker on its image reference.

Flux commits image updates to the repository; application CI only builds and pushes. Public owned images go to GHCR. Private owned images go to Harbor, with separate pull credentials for workloads and for image scanning. Renovate keeps managing upstream artifacts, and the two mechanisms never share an image reference.

The first adopter is a public application. Migrating the private application is separate work and must first move its manifests into GitOps. At minimum, track Flux's image-automation commits and alert on relevant controller events. Avoid CI credentials that can write to the cluster repository.

## Alternatives considered

- **Renovate only:** too slow for owned apps.
- **CI commits from each app repository:** duplicates write credentials.
- **Mutating images in the cluster directly:** conflicts with GitOps.
- **Scheduled restarts:** conflicts with GitOps.

## Consequences

The cluster gains two Flux controllers and a few resources per app, but no new chart or restore obligation. A bot author appears in repository history; future push workflows must avoid triggering loops. Private image credentials stay on the existing secret delivery path.
