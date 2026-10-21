---
title: Observability and logging experiments
record_type: historical-experiment
period: 2026-04 to 2026-10
---

# Observability and logging experiments

Between April and October 2026, Anton moved from ad-hoc log reading to a defined logging contract with shared policy checks. The contract grew out of gaps found in practice and is enforced with repository fixtures.

## What happened

Two monitoring failures looked like platform failures but were not:

- **Longhorn metrics disappeared.** A chart-owned NetworkPolicy did not admit Prometheus traffic to the Longhorn managers. Storage itself was healthy.
- **Talos health checks chose unreachable addresses.** Health discovery picked addresses on the point-to-point storage fabric, which are not routable from every node. etcd was healthy.

## What we learned

A missing signal is first a question about the monitoring path. Check network policy and address selection before concluding the workload or control plane is down.

ClickStack, remote forensics, and a log lakehouse were tried and retired. Their results say nothing about current availability. When reusing an old metric or query, keep its meaning, source, sample window, and known blind spots with it.

Measurement practice from the same period is in [metric and resource experiments](metric-and-resource-experiments.md).
