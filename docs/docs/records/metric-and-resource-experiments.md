---
title: Metric and resource experiments
record_type: historical-experiment
period: 2026-08 to 2026-10
---

# Metric and resource experiments

From August to October 2026, metric work relied on written measurement contracts rather than dashboards or favorable snapshots. A contract made it possible to tell a real change from workload mix, scrape gaps, restarts, or instrumentation limits.

## What a contract named

| Part | Fields |
| --- | --- |
| Purpose | Beneficiary, scope, editable levers, authority |
| Measurement | Numerator and denominator, start and stop events, window, query, sample count |
| Judgment | Baseline, target, noise tolerance, independent guards |
| Safety | Rollback and a result record |

## What we learned

Early measurements exposed metric semantics that needed correcting:

- Restart estimates can be confounded by OOM kills.
- Counters reset.
- Aggregate snapshots cannot establish cause.

Record corrections next to the result instead of carrying the superseded reading forward.

Resource requests were right-sized from a bounded window of CPU and working-set data, leaving limits and replica counts unchanged. Lower requests change what the scheduler reserves. They do not change actual consumption or power draw.

## Using these results

The records are dated and say nothing about current utilization. To compare, repeat the measurement under its original contract or version the contract explicitly.
