---
title: Learning experiments and platform scope
record_type: historical-experiment
period: 2026
---

# Learning experiments and platform scope

Anton welcomes learning, but each experiment needs a reason, an owner, and a way out.

## The old playground

The earlier playground collected examples for ClickHouse, Dragonfly, Redpanda, ScyllaDB, and TiDB. They showed how to try each product; they were never a reliable list of what was deployed. Their install recipes are no longer current guidance.

Some older notes also ran applications imperatively, outside Flux. That was a different ownership model, not a way around today's GitOps and approval rules.

## The rule since the rebuild

[The structured rebuild](../decisions/0001-cluster-reset-and-structured-rebuild.md) separated two reasons to adopt a component: a concrete consumer, or contained learning. A learning experiment needs:

- a review date,
- agreement that its data is disposable, and
- an exit plan.

## How recent experiments ended

| Experiment | Outcome |
| --- | --- |
| [ClickStack](../decisions/0028-clickstack-learning-experiment.md) | Ended; Kubernetes logs moved to [OTel and Loki](../guides/logging.md) |
| Lakehouse and workflows | [Retired](lakehouse-retirement.md) |

Database operators still running today serve platform consumers; they do not revive the playground. The [capabilities map](../overview/capabilities.md) shows that boundary.
