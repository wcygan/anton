---
status: Accepted
date: 2026-08-11
deciders: ['@wcygan']
affects: observability
intent: concrete-need
supersedes: [0030]
superseded-by: null
retrospective: false
edition: condensed-public
slug: /decisions/0032-honor-loki-stream-retention-minimum
---

# 0032 — Honor Loki's stream retention minimum

> Raise Loki debug and trace retention from six to 24 hours, Loki's enforced minimum.

_Public edition condensed on 2026-10-21; original decision date and meaning retained._

## Context

[ADR 0030](0030-adopt-loki-for-kubernetes-logs.md) set debug and trace stream retention to six hours. Loki 3.7.4 rejects stream retention below 24 hours, so the setting kept a Helm upgrade from becoming Ready. The chart offers no way around the minimum.

## Decision

Set debug and trace retention to 24 hours. This supersedes only that value in ADR 0030; Loki's topology, storage path, severity vocabulary, labels, and security boundary stay as decided there.

Keep the explicit stream rule so the policy stays reviewable, and validate the value through the logging contract before reconciling.

## Alternatives considered

- **Keep six hours:** invalid.
- **Upgrade the chart:** does not change the enforced minimum.
- **Drop the rule:** makes retention intent less explicit.

## Consequences

Debug and trace records may now stay for up to a day, using more storage than first planned. Keep monitoring the Loki volume and SeaweedFS capacity. The change adds no component, credential, or public endpoint. Reconciling and verifying it require separate operator authorization.
