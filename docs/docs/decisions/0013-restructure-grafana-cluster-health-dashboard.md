---
status: Accepted
date: 2026-04-17
deciders: ['@wcygan']
affects: observability
intent: concrete-need
supersedes: []
superseded-by: null
retrospective: false
edition: condensed-public
slug: /decisions/0013-restructure-grafana-cluster-health-dashboard
---

# 0013 — Restructure the cluster-health dashboard

> Restructure the single cluster-health dashboard for progressive disclosure.

_Public edition condensed on 2026-10-21; original decision date and meaning retained._

## Context

The cluster-health dashboard was the main view of Anton's state and needed a clearer structure.

## Decision

Restructure the dashboard into a compact summary that is always visible, followed by sections for capacity, control plane, nodes, workloads, storage, and network. Aim for roughly 16–20 panels in one scroll. Keep its stable dashboard identity and manage its configuration in Git.

- **Defer** etcd, scheduler, and controller-manager scrapes until a diagnostic need or chart review makes them useful. Exposing them requires Talos machine-configuration changes and careful rolling updates.
- **Reject**, for now, a Talos-specific OS metrics bridge. No concrete diagnostic need justified it, and existing Kubernetes metrics covered ordinary health questions.

## Alternatives considered

- **Several dashboards:** tab switching is not worth it at this scale. Split a section into its own board only if it, or the total, outgrows the stated size.
- **Generic community dashboards:** lose Anton-specific Flux and storage views.
- **Bundle Talos changes with the dashboard work:** couples two different risk levels.

## Consequences

Panel data needs verification, and scrape or query gaps need fixing. Revisit control-plane metrics when their triggers fire. Reconsider an OS exporter only after an incident shows a missing signal, or under a timeboxed learning intake.

The layout describes the decision. It does not prove every proposed panel or trigger was implemented.
