# Cluster metric evidence

These files retain sanitized read-only observations for plan 0022.

Each record omits Kubernetes context names, endpoints, addresses, condition
messages, and Secret data. The matching observer verifies the Anton target
before the first cluster read.

Treat each record as one immutable observation. Do not replace it with a later
sample. Add a new timestamped file instead.

## Evidence index

| Record | Scope | Limit |
|---|---|---|
| `2026-08-11T011440Z-m2.json` | One fixed-time critical revision observation | It is incomplete and does not measure convergence time. |
| `2026-08-11T005110Z-m4.json` | One fixed-time platform continuity observation | OOM is `no_data`, thresholds are unapproved, and coverage is partial. |
| `2026-08-11T013927Z-m4-restart-attribution.json` | M4-E4 restart attribution evidence | It does not replace the original restart rate. Overall M4 remains partial. |
| `2026-08-11T142625Z-m4-oom-restart-estimator.json` | M4-E5 guarded OOM restart estimator | It is not an authoritative OOM event counter. Overall M4 remains partial. |
| `2026-08-11T151847Z-cluster-metric-snapshot.json` | Initial aggregate M1-M4 observation | It is a comparison baseline. It does not prove improvement. |

## Longitudinal observations

Use aggregate snapshots for passive hill-climbing observations. Do not create
synthetic load or mutate the cluster to collect a snapshot.

Use one UTC timestamp for the M2 and M4 observers. Record the pushed Git
revision and current M1 validator result. Add M3 data only after a qualifying
incident or approved drill.

Keep each metric separate. Do not create a composite score. Use the metric
contract direction and tolerance before reporting improvement. If no tolerance
exists, report the values without a trend decision.

Keep missing evidence as `null`. Do not convert missing evidence to zero. Each
new observation must use a new timestamped file and the same schema version.

M1 and M3 experiment records remain in
`context/notes/cluster-metric-contracts.md`. They do not have separate JSON
evidence files. No approved M2 durable ledger exists.

Use `context/plans/0022-establish-cluster-metric-experiments.md` for the next
bounded step. Use `context/notes/cluster-metric-contracts.md` for metric
definitions, experiment records, guards, and authority boundaries.

These records describe past observations. Run the target-bound observers again
when the task requires current cluster state and has read-only authority.
