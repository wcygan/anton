---
status: Superseded-by 0029
date: 2026-05-04
deciders: ['@wcygan']
affects: networking
intent: concrete-need
supersedes: []
superseded-by: 0029
retrospective: false
edition: condensed-public
slug: /decisions/0025-keep-chart-networkpolicies-fix-probes-upstream
---

# 0025 — Keep chart NetworkPolicies enabled and repair probe gaps

> Keep chart-managed NetworkPolicies on by default and repair probe gaps with targeted allows and upstream fixes.

_Public edition condensed on 2026-10-21; original decision date and meaning retained._

:::caution Superseded
Replaced by [ADR 0029](0029-restore-pod-security-isolate-public-workloads.md). Read it before applying this decision.
:::

## Context

A chart-shipped ingress policy omitted a health-probe port, so after a platform upgrade its controller failed kubelet probes. Disabling that chart's policy was a reasonable tactical recovery. A blanket opt-out, though, would weaken workload isolation and turn one chart defect into a general rule. Cilium's localhost allowance had been expected to keep probes working; the incident showed that was not enough protection.

## Decision

Keep chart-managed NetworkPolicies enabled by default. When a policy blocks probes, prefer a targeted in-repository allow policy, and file an upstream fix.

A component-specific opt-out is allowed as a documented tactical exception. Record the upstream issue and date, and revisit at the next chart upgrade. New app scaffolds must not disable chart policies by default.

At adoption, compare rendered policies against each workload's probe ports. A cluster-wide crash-loop alert serves as a related safety net. Namespace-wide default-deny design was deferred.

## Alternatives considered

- **Disable chart policies by default:** an overcorrection, at odds with the intended default-deny posture.
- **One universal probe policy:** ports vary, and it duplicates Cilium behavior.

## Consequences

The upstream-first approach can leave temporary exceptions to maintain, while keeping chart protections everywhere else. Each exception carries review debt, and a chart change should trigger reassessment.

[ADR 0029](0029-restore-pod-security-isolate-public-workloads.md) superseded this decision's probe and isolation posture.
