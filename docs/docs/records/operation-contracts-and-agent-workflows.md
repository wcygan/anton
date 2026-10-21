---
title: Operation contracts and agent workflow lessons
record_type: historical-engineering
period: 2026-08 to 2026-10
---

# Operation contracts and agent workflow lessons

## What happened

A repository architecture review gathered repeated safety rules into small, tested contracts:

- Flux applications
- SeaweedFS bucket provisioning
- Kubernetes log semantics
- Cluster target selection
- Shared Claude and Codex policy

The policy is one semantic module with thin adapters for each client's events, tested with shared fixtures. A later independent review closed several remaining repository-level gaps. Neither review claimed live-cluster verification.

## What we learned

Before acting, establish the owner and the target. Fail closed when the context is ambiguous. Keep temporary evidence private, and verify actual behavior at each ownership layer.

Put shared invariants in a reusable contract with tests. Keep app-specific exceptions explicit.

## Retired records

The old agent memory files held local precedent and corrections, not authoritative cluster state. Durable lessons now live in shared procedures or dated records like this one.

Plan statuses are historical. An active-looking plan may be stale or superseded. The private working copies keep each plan's original status and pending tasks unless clear retirement evidence justified closing it. Their owners reconcile them; nobody marks them complete silently.
