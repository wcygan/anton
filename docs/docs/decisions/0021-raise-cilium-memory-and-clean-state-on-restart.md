---
status: Superseded-by 0022
date: 2026-04-23
deciders: ['@wcygan']
affects: networking
intent: concrete-need
supersedes: [0020]
superseded-by: 0022
retrospective: false
edition: condensed-public
slug: /decisions/0021-raise-cilium-memory-and-clean-state-on-restart
---

# 0021 — Raise Cilium memory and clean state on restart

> Raise the Cilium memory limit to 3584Mi and enable `cleanState` to guard against corrupted BPF state.

_Public edition condensed on 2026-10-21; original decision date and meaning retained._

:::caution Superseded
Replaced by [ADR 0022](0022-keep-3584mi-cilium-limit-reject-permanent-cleanstate.md). Read it before applying this decision.
:::

## Context

[ADR 0020](0020-size-cilium-memory-limit-for-cgroup-wss.md) raised Cilium agent memory after an OOM event. A later node instability during pod churn suggested a second risk: transient memory pressure might coincide with BPF map corruption. Upstream reports described similar behavior and recommended more memory headroom and rebuilding Cilium state after a restart. This diagnosis was a hypothesis, not a confirmed cause.

## Decision

- Raise the Cilium agent memory limit from 2560Mi to 3584Mi, giving transient peaks room.
- Enable `cleanState` on the clean-state init container, so a restart does not inherit corrupted BPF state.

This withdraws ADR 0020's claim that the earlier limit was a durable fix. Each restart now briefly interrupts the datapath while state is rebuilt.

The decision also called for monitoring memory, validating the first restart with the secondary CNI configuration, and exercising the setting under the same kind of scheduling churn. Those checks were meant to show whether the mitigation worked; they would not prove the hypothesized mechanism.

## Alternatives considered

- **Keep the old limit, or apply only one change:** leaves a suspected failure mode unaddressed.
- **A much larger memory increase:** could hide future regressions.
- **Run the agent outside container limits:** excessive without a recurrence.

## Consequences

The change reserves more memory and accepts short per-node connectivity blips on restart. It also showed that calling something a durable fix needs more evidence than a short stable period.

[ADR 0022](0022-keep-3584mi-cilium-limit-reject-permanent-cleanstate.md) keeps the memory increase but rejects permanent `cleanState`.
