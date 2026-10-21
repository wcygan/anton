---
status: Accepted
date: 2026-07-09
deciders: ['@wcygan']
affects: security
intent: concrete-need
supersedes: [0025]
superseded-by: null
retrospective: false
edition: condensed-public
slug: /decisions/0029-restore-pod-security-isolate-public-workloads
---

# 0029 — Restore Pod Security and isolate public workloads

> Restore Talos's default Pod Security Admission and put default-deny network policies on externally routed workloads.

_Public edition condensed on 2026-10-21; original decision date and meaning retained._

## Context

A security review found that Pod Security Admission defaults had been removed, some namespaces had no explicit policy labels, and externally routed workloads had few network restrictions. An earlier probe incident ([ADR 0025](0025-keep-chart-networkpolicies-fix-probes-upstream.md)) also showed that inherited CNI behavior alone does not guarantee probe access. The threat model now calls for stronger isolation of public workloads.

## Decision

### Pod Security

Restore Talos's default Pod Security Admission policy: enforce baseline, audit and warn at restricted, and keep the system namespace exemption. Label every namespace explicitly.

- Infrastructure that needs host access, elevated capabilities, or privileged agents keeps a documented privileged label.
- Ordinary workloads enforce at least baseline, and move to restricted once their rendered manifests pass admission dry runs.

### Network policy

Keep chart-shipped NetworkPolicies enabled. Add pod-selective default-deny policies to externally routed applications, allowing only the Gateway, DNS, metrics, backend, and egress paths each one needs. Allow kubelet probes explicitly through namespaced Cilium policies.

Roll out one workload at a time, checking routes, probes, metrics, and dependencies before moving on.

## Alternatives considered

- **Leave the defaults unchanged:** keeps unnecessary admission and lateral-movement access.
- **Namespace-wide default deny everywhere:** risks breaking networking infrastructure, observability, storage, and other broad dependencies.

## Consequences

Namespace exceptions and per-app policies add ongoing design and review work. Roll back if probes, routes, metrics, storage, or backend traffic regress. Privileged infrastructure exceptions remain a hardening backlog.
