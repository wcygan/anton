---
title: Flux and platform reliability incidents
record_type: historical-incident
period: 2026-05 to 2026-10
---

# Flux and platform reliability incidents

## Probe port blocked after an upgrade

After a platform upgrade, the Flux operator entered a crash loop. A chart-created NetworkPolicy allowed metrics and UI traffic but not the health-probe port. The controllers started normally, failed their probes, and were restarted.

The repair changed policy ownership so probes could pass. [ADR 0025](../decisions/0025-keep-chart-networkpolicies-fix-probes-upstream.md) and its successor [ADR 0029](../decisions/0029-restore-pod-security-isolate-public-workloads.md) record the resulting policy.

**Lesson:** when probes fail on a process that started cleanly, check network enforcement before treating it as an application startup fault.

## Related cases

| Case | What it showed |
| --- | --- |
| Flux cold-start ordering | Consumers raced their operators until dependencies were explicit ([ADR 0027](../decisions/0027-platform-dependson-rule.md)) |
| Longhorn manager scrapes | A chart NetworkPolicy blocked Prometheus |
| Health-check address selection | Tooling picked storage-network addresses that were not routable everywhere |

Readiness, telemetry, and routing all depend on explicit network and dependency contracts. A passing manifest check does not show that a controller reconciled or that the service works. For a current diagnosis, check the source revision, applied policy, controller conditions, and workload behavior.
