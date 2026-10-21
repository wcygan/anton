---
status: Accepted
date: 2026-05-07
deciders: ['@wcygan']
affects: all
intent: concrete-need
supersedes: []
superseded-by: null
retrospective: false
edition: condensed-public
slug: /decisions/0027-platform-dependson-rule
---

# 0027 — Require explicit Flux dependencies for custom resources

> Every Flux Kustomization that creates custom resources must depend on, and wait for, the Kustomization that installs their CRDs or controller.

_Public edition condensed on 2026-10-21; original decision date and meaning retained._

## Context

During cold starts, Flux consumers often tried to create custom resources before their operators or CRDs were ready. Retries converged eventually, but recovery was slow and dependency order was hard to see. An audit added dependency edges and readiness waits. Reconciliation then converged promptly, and a later incident confirmed that downstream resources correctly waited for a database to become healthy.

## Decision

- A Kustomization that creates a resource whose CRD or controller comes from another Kustomization must declare `dependsOn` for it.
- A cross-namespace dependency must name the namespace explicitly.
- A platform Kustomization that others depend on must report real readiness with `wait: true`, `healthChecks`, or `healthCheckExprs`. Otherwise the dependency only confirms the objects were applied, not that they are healthy.

The rule covers Gateway API routes, external DNS endpoints, external secrets, Multus attachments, and operator-managed database or storage resources. Cilium and CoreDNS, installed at bootstrap by helmfile, are exceptions until they are migrated under Flux. App scaffolding and review should encode and check these edges.

## Alternatives considered

- **Dependencies without readiness waits:** races remain.
- **One global dependency tree:** a brittle central list.
- **Webhook-injected edges:** hides ordering from review.

## Consequences

Reconciliation takes a little longer because it waits on dependencies. In exchange, cold starts become deterministic, and a dependency failure shows up at the right boundary.
