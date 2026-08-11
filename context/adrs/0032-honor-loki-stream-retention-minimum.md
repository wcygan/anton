---
status: Accepted
date: 2026-08-11
deciders: ['@wcygan']
affects: observability
intent: concrete-need
supersedes: [0030]
superseded-by: null
retrospective: false
---

# 0032 — Honor Loki stream retention minimum

> Loki stream retention will use its supported 24-hour minimum.

## Status

Accepted.

## Context

ADR 0030 set debug and trace retention to six hours. Loki 3.7.4 rejects
stream retention below 24 hours. The invalid value prevents a Helm upgrade
from becoming Ready.

The corrective source uses 24 hours. This decision keeps every other ADR 0030
decision in force. Loki topology, storage path, severity vocabulary, indexed
labels, and security boundary remain unchanged.

## Decision

Anton will retain debug and trace streams for 24 hours. Loki rejects a
six-hour stream retention value. The logging contract rejects that source
value before Flux applies it.

## Alternatives considered

- **Keep six hours** — rejected because Loki cannot run that value.
- **Upgrade the chart** — rejected because the current chart enforces the same minimum.
- **Remove the stream rule** — rejected because the explicit policy aids review.

## Consequences

### Accepted costs

- Debug and trace data can remain available for up to 24 hours.
- Operators must continue to monitor Loki PVC and SeaweedFS capacity.
- This change adds no component, credential, or public route.

## Follow-ups

- [ ] With explicit operator approval, reconcile Flux and verify Loki
  convergence.
