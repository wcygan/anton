---
status: Accepted
date: 2026-04-10
deciders: ['@wcygan']
affects: all
intent: concrete-need
supersedes: []
superseded-by: null
retrospective: true
---

# 0001 — Cluster reset and structured rebuild (April 2026)

> In April 2026 anton was reset to a near-empty cluster and is being rebuilt deliberately on top of ADRs, skills, agents, and hooks; previously trialled components are eligible for re-adoption.

## Status

Accepted

## Context (retrospective)

By early April 2026, anton had accumulated about a year of additions made *without* a structured intake process. Components were installed with the loose framing of "every real cluster has X" — full LGTM observability, CloudNativePG, Dragonfly, Harbor and its backing stores, TiDB, Scylla, Redpanda, demo apps, and assorted second-order integrations across Cilium and envoy-gateway. None of these were technically broken; they were a *governance* failure, not a software failure. The cluster was paying real RAM, real Renovate-PR tax, and real cognitive cost for components without concrete consumers.

Two things were missing:

1. **A gate at intake** — the moment of "should this thing exist on anton at all" had no checklist behind it.
2. **A durable home for decisions** — there was no way to record why something was added (or not), which meant the same arguments got re-litigated every few months.

Rather than try to fix governance retroactively on top of the existing state, the decision was to **wipe most workloads and rebuild from scratch with the governance built in from turn 0**. The reset is *not* a judgement on the individual components — it is a decision about how the cluster should be built up next.

## Decision

In April 2026, anton was reset to a near-empty cluster (Cilium CNI, cert-manager, ESO, envoy-gateway, Cloudflare tunnel, Spegel, and a handful of platform pieces remained; almost everything else was removed). The cluster is being rebuilt incrementally on top of:

- **ADRs** at `context/adrs/` — durable home for decisions, immutable, supersedable.
- **`cluster-intake` skill** + **`cluster-intake-gatekeeper` agent** — a gate at intake that requires declared intent (concrete need / honest learning), runs hard containment checks, and hands off accepted candidates to the new `adr` skill.
- **`adr` skill** — author/list/supersede ADRs, regenerate the index atomically.
- **Anton-local Claude Code skills, agents, hooks** — every recurring decision point or operator workflow is owned by a skill or subagent that accrues focused context.
- **SessionStart hooks** that inject cluster state and the ADR index, so every session (and every spawned subagent) starts informed.

The single explicit "this component does not return" decision is captured in **ADR 0002 (Rook-Ceph)**. Every other previously-trialled component is eligible for re-adoption under the standard intake gate.

## Alternatives considered

- **Retrofit governance onto the existing state** — write ADRs *for* the current cluster, gate future intake, leave the existing components in place. Rejected: the existing state was the result of the very pattern the new gate is designed to catch, and trying to retroactively legitimise it would have meant either lying in the ADRs or doing 17 individual deferral conversations.
- **Smaller, surgical removals** — remove only the most obvious regrets (LGTM stack, the database operators with no consumers) and leave the rest. Rejected: half-resets generate more work (residual integrations, partial cleanup) and don't actually establish the new governance pattern. A clean reset is paradoxically less disruptive.
- **Do nothing, accept the current state** — rejected because the maintenance tax was already non-trivial and growing (Renovate PR queue, second-order observability integrations to update on every chart bump).

## Consequences

### Accepted costs

- **Short-term reduction in cluster capability** — for a window measured in weeks, anton runs with much less than it did in March 2026. That is intentional: re-adoption is gated, not free.
- **The reset commits and the ADR system itself are now load-bearing context** for any future decision. Sessions that ignore the ADR index will repeat the same intake mistakes.
- **A graveyard of removal commits** in `git log` from early April 2026 that future readers will need to interpret correctly — the `git log` looks alarming if you don't know about this ADR.
- **One-time tooling investment**: writing the `cluster-intake` skill, `cluster-intake-gatekeeper` agent, `adr` skill, SessionStart hooks, and the convention docs.

### Components removed during the reset (all eligible for re-adoption)

This is a single inventory, not 16 separate decisions. Every entry below is **available for re-adoption** under the standard `cluster-intake` flow with declared intent — none of these were rejected on technical grounds.

| Category | Components removed | Re-adoption posture |
|---|---|---|
| Observability | kube-prometheus-stack, Alloy, Grafana, Loki (LGTM stack); Cilium scrape/dashboards/ServiceMonitor; envoy-gateway PodMonitor; Grafana external exposure | Likely to return, probably as a smaller scope first (single uptime probe, then build up). LGTM + Grafana are good software; the failure was scope, not the components. |
| Databases | CloudNativePG, Dragonfly, TiDB, Scylla, Redpanda | All on the re-adoption shortlist. CNPG and Dragonfly need a concrete app waiting; TiDB / Scylla / Redpanda are valid as declared learning intakes with timeboxes. |
| Registries | Harbor app + Harbor-Postgres + Harbor-Redis + harbor namespace; Spegel `harbor` mirror entry | Harbor itself is good software; the question is whether Spegel + public OCI is enough or whether a private registry has a real consumer. Worth re-evaluating. |
| Demos | `echo`, `echo-two` | Demo apps have a removal cost; treat future demos as implicit learning intakes with a timebox. |

The single component that does **not** appear above and does **not** return under standard intake is **Rook-Ceph** — see ADR 0002.

### Lessons (retrospective)

- **The failure mode was completionism, not the components.** "Every real cluster has X" is the sentence that produced almost every removal in this reset. The new intake gate's primary job is to catch that sentence and either reframe it as honest learning intake (timebox + exit plan) or reject it.
- **Most "production patterns" are mismatched at homelab scale.** Distributed databases, full observability stacks, private registries, HA storage — they're all reasonable in environments with the headcount and traffic to justify them. Anton has neither, and the rebuild should accept that explicitly rather than aspirationally.
- **Operator intake compounds.** Harbor was three intakes in a trench coat (app + Postgres + Redis). Future intake must count the *full* dependency surface, not just the headline component.
- **Second-order integrations are second removal waves.** When the LGTM stack came out, Cilium dashboards, ServiceMonitors, and the envoy-gateway PodMonitor came out with it. A future "remove an app" runbook should `grep -r <component-name>` across the manifest tree first.
- **`anton` is partly a learning cluster** — and that is now an explicit, supported intake path under the contained-learning rubric. Several of the previously-removed databases (TiDB, Scylla, Redpanda) were honest learning experiments that just lacked the framing. Under the new gate, the same intake is welcomed with a declared timebox and exit plan.

## Re-adoption guidance

Apply the standard `cluster-intake` flow with declared intent to any of the components in the table above. Specifically:

- **Concrete-need reframing** — there must be an app *already running* on anton that hits the limitation the new component would solve. Not "an app I'm about to add."
- **Learning-intake reframing** — timebox + exit plan + throwaway data acknowledgement. The 30-day learning intake is the canonical path for revisiting the database experiments.

The `cluster-intake-gatekeeper` will surface this ADR (via `affects: all`) on every intake, so the reset context is always available before a re-adoption decision is made.

## Follow-ups

- [ ] Evolve `RE-ADOPTION-RUBRIC.md` as components return, removing categories from the "needs framing" list as they're successfully re-adopted under the new gate.
- [ ] Periodically (every ~90 days) audit whether the rebuild is on track or whether the gate has become an obstacle to legitimate intake. The gate is a tool, not a religion.
