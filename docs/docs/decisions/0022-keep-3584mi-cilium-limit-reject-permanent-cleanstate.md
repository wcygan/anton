---
status: Accepted
date: 2026-04-23
deciders: ['@wcygan']
affects: networking
intent: concrete-need
supersedes: [0021]
superseded-by: null
retrospective: false
edition: condensed-public
slug: /decisions/0022-keep-3584mi-cilium-limit-reject-permanent-cleanstate
---

# 0022 — Keep the Cilium memory limit; reject permanent clean-state

> Keep the 3584Mi Cilium memory limit, and use `cleanState` only as a one-shot manual recovery step.

_Public edition condensed on 2026-10-21; original decision date and meaning retained._

## Context

[ADR 0021](0021-raise-cilium-memory-and-clean-state-on-restart.md) paired a higher Cilium memory limit with `cleanState: true`. During a DaemonSet rolling update, the clean-state init container found a host pidfile left by the departing agent and failed its safety check repeatedly. The rollout stalled and Flux rolled it back. The chart documentation confirmed that clean-state is a cautious manual recovery control, not a safe permanent setting.

## Decision

Keep `cilium-agent.resources.limits.memory` at 3584Mi. Remove `cleanState: true` from the steady-state HelmRelease.

Reintroduce it only through the manual one-shot procedure:

1. Enable it for the selected pods.
2. Delete those pods so their state is rebuilt.
3. Disable it again.

The memory increase is a mitigation based on upstream reports, not proof of what caused the earlier instability. Monitoring and the planned stability window are still needed. If evidence later points directly at BPF state, use the recovery procedure or write a new decision.

## Alternatives considered

- **Bypass the pidfile check with hooks or another init container:** cleanup could run while the agent is still alive.
- **Use `cleanBpfState` instead:** same init mechanism, same rollout hazard.
- **Keep the flag on:** ordinary DaemonSet updates become unreliable.

## Consequences

Cilium keeps the extra memory headroom without a permanent rollout deadlock. The lasting lesson is to tell one-shot recovery settings apart from steady-state values. ADR 0021's body remains the record of the mistaken pairing.
