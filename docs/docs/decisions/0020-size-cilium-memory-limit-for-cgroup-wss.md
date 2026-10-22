---
status: Superseded-by 0021
date: 2026-04-21
deciders: ['@wcygan']
affects: networking
intent: concrete-need
supersedes: []
superseded-by: 0021
retrospective: false
edition: condensed-public
slug: /decisions/0020-size-cilium-memory-limit-for-cgroup-wss
---

# 0020 — Size Cilium memory for cgroup working set

> Raise the Cilium agent memory limit to 2560 MiB, sized against cgroup working set rather than RSS.

_Public edition condensed on 2026-10-21; original decision date and meaning retained._

:::caution Superseded
Replaced by [ADR 0021](0021-raise-cilium-memory-and-clean-state-on-restart.md). Read it before applying this decision.
:::

## Context

A node rebooted repeatedly after its Cilium agent was killed by the cgroup OOM handler. RSS alone understated memory use: active page cache inside the container's cgroup pushed its working set toward the limit. Each restart repopulated that cache, so the failure recurred.

This was a per-container accounting problem. It did not show that other nodes had the same workload or that the whole node was out of memory.

## Decision

Raise the Cilium agent memory limit from the chart default to 2560 MiB, with headroom above the observed working-set peak. Keep the limit as a containment boundary, and add a warning alert at about 75% of it. Size future limits against observed container working set under realistic churn, not process RSS alone.

## Alternatives considered

- **No limit:** could hide a real leak and put the node under pressure.
- **A smaller increase:** little margin over the measured peak.
- **A much larger increase:** could hide regressions.

## Consequences

Monitoring on the affected node had gaps during the incident. The alert and the closure of the investigation plan were explicit follow-ups; do not assume they were done.

[ADR 0021](0021-raise-cilium-memory-and-clean-state-on-restart.md) superseded this decision. The evidence and the working-set lesson remain useful; read the current limit and restart behavior from the successors.
